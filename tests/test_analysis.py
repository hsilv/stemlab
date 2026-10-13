import json
import os
import sys
import threading

import numpy as np
import pytest
import soundfile as sf

from stemlab import filelock
from stemlab.analysis import _separator, inference_lock, main, measure
from stemlab.config import settings

RATE = 22050
A_MINOR = (57, 60, 64, 69, 72, 76)
C_MAJOR = (60, 62, 64, 65, 67, 69, 71, 72)


def clicks(bpm, duration, amplitude=1.0):
    """Impulses on a grid. The peak of each click is the beat."""
    frames = int(round(duration * RATE))
    wave = np.zeros(frames, dtype=np.float32)
    instant = 0.0
    while instant < duration - 0.01:
        index = int(round(instant * RATE))
        if index < frames:
            wave[index] = amplitude
        instant += 60.0 / bpm
    return wave


def tone(notes, duration, amplitude=0.25):
    frames = int(round(duration * RATE))
    times = np.arange(frames) / RATE
    wave = np.zeros(frames, dtype=np.float64)
    for midi in notes:
        frequency = 440.0 * 2.0 ** ((midi - 69) / 12.0)
        wave += np.sin(2.0 * np.pi * frequency * times)
    wave *= amplitude / len(notes)
    fade = int(0.01 * RATE)
    ramp = np.linspace(0.0, 1.0, fade)
    wave[:fade] *= ramp
    wave[-fade:] *= ramp[::-1]
    return wave.astype(np.float32)


def stereo(wave):
    return np.column_stack((wave, wave)).astype(np.float32)


def test_known_bpm_is_within_one_hundredth():
    reading = measure(clicks(128.04, 16)[:, None], RATE, lambda _stage: None, None)
    assert reading.bpm == pytest.approx(128.04, abs=0.01)
    assert reading.downbeat == pytest.approx(0.0, abs=0.02)
    assert reading.warning == ""
    assert (reading.camelot, reading.key_name) == (None, None)
    assert round(reading.bpm, 2) == reading.bpm


def test_majority_tempo_wins_and_names_the_rest():
    mixed = np.concatenate([clicks(118.06, 24), clicks(96, 8)])
    reading = measure(mixed[:, None], RATE, lambda _stage: None, None)
    assert reading.bpm == pytest.approx(118.06, abs=0.01)
    assert reading.warning == "Part of the track does not hold this grid."
    assert reading.downbeat == pytest.approx(0.0, abs=0.02)


@pytest.mark.parametrize(
    ("notes", "camelot", "key_name"),
    [(A_MINOR, "8A", "A minor"), (C_MAJOR, "8B", "C major")],
)
def test_constructed_key_maps_to_camelot(notes, camelot, key_name):
    reading = measure(tone(notes, 12)[:, None], RATE, lambda _stage: None, None)
    assert (reading.camelot, reading.key_name) == (camelot, key_name)


def test_full_song_includes_a_long_quiet_intro():
    intro = 40.3
    body = 16.0
    quiet = clicks(90.0, intro, amplitude=0.04) + tone(C_MAJOR, intro, amplitude=0.08)
    later = clicks(128.04, body) + tone(A_MINOR, body, amplitude=0.5)
    calls = []

    def separate_window(kind, start, end):
        calls.append((kind, start, end))
        length = max(end - start, 0.0)
        if kind == "drums":
            return clicks(90.0, length)[:, None]
        return tone(A_MINOR, length)[:, None]

    reading = measure(
        np.concatenate([quiet, later])[:, None],
        RATE,
        lambda _stage: None,
        separate_window,
    )
    assert reading.bpm == pytest.approx(128.04, abs=0.01)
    assert (reading.camelot, reading.key_name) == ("8A", "A minor")
    bar = 4.0 * 60.0 / reading.bpm
    expected = intro - np.floor(intro / bar) * bar
    assert reading.downbeat == pytest.approx(float(expected), abs=0.05)
    assert calls[-1][0] == "harmonic"
    for kind, start, end in calls:
        assert kind in {"drums", "harmonic"}
        if kind == "drums":
            assert end - start == pytest.approx(45, abs=1)
        else:
            # The whole 56 seconds is shorter than a harmony window, so a slice is the whole song.
            assert (start, end) == pytest.approx((0.0, intro + body), abs=0.05)


def test_clear_mix_still_asks_for_the_harmony_but_not_the_drums():
    wave = stereo(clicks(120, 12, amplitude=0.8) + tone(A_MINOR, 12, amplitude=0.5))
    calls = []
    stages = []
    reading = measure(wave, RATE, stages.append, lambda *args: calls.append(args))
    assert [call[0] for call in calls] == ["harmonic"]
    assert stages == ["Reading tempo and key"]
    assert reading.bpm == pytest.approx(120.0, abs=0.01)
    # The separator gave nothing back, so the full mix answers.
    assert (reading.camelot, reading.key_name) == ("8A", "A minor")
    assert reading.downbeat == pytest.approx(0.0, abs=0.02)
    assert reading.warning == ""
    assert set(reading.to_dict()) == {
        "bpm",
        "camelot",
        "key_name",
        "downbeat",
        "warning",
        "valence",
        "energy",
    }


def test_isolated_harmony_decides_the_key_unless_it_is_a_close_call():
    mix = stereo(clicks(120, 12, amplitude=0.8) + tone(A_MINOR, 12, amplitude=0.5))
    stems = {"clean": tone(C_MAJOR, 12)[:, None], "noise": clicks(100, 12)[:, None]}
    heard = {}
    for name, stem in stems.items():
        heard[name] = measure(mix, RATE, lambda _stage: None, lambda *_args, s=stem: s)
    assert (heard["clean"].camelot, heard["clean"].key_name) == ("8B", "C major")
    # Clicks have no harmony: that reading is a close call, so the full mix is kept.
    assert (heard["noise"].camelot, heard["noise"].key_name) == ("8A", "A minor")


def test_tied_mix_isolates_drums_then_harmony():
    duration = 30
    mixed = np.concatenate([clicks(100, duration), clicks(147, duration)])
    mixed = mixed + tone(A_MINOR, duration * 2, amplitude=0.35)
    calls = []

    def separate_window(kind, start, end):
        calls.append((kind, start, end))
        return None

    reading = measure(mixed[:, None], RATE, lambda _stage: None, separate_window)
    assert [call[0] for call in calls] == ["drums", "harmonic"]
    kind, start, end = calls[0]
    assert start >= 0
    assert end <= duration * 2 + 0.05
    assert end - start == pytest.approx(45, abs=1)
    assert calls[1][2] - calls[1][1] == pytest.approx(60, abs=0.1)
    assert reading.warning == "Part of the track does not hold this grid."
    assert (reading.camelot, reading.key_name) == ("8A", "A minor")


def dembow(bpm, duration, tresillo=0.7):
    """A kick on every beat plus the 3-3-2 accents, which pull autocorrelation toward 4:3."""
    beat = 60.0 / bpm
    wave = np.zeros(int(round(duration * RATE)), dtype=np.float32)
    count = 0
    while count * beat < duration - 0.05:
        for offset, level in ((0, 1.0), (0.75, tresillo), (1.5, tresillo)):
            if count % 4 == 0 or offset == 0:
                at = int(round((count + offset) * beat * RATE))
                if at < len(wave) and (count % 2 == 0 or offset == 0):
                    wave[at] = level
        count += 1
    return wave


def test_beats_from_the_tracker_decide_the_pulse_and_the_bar():
    bpm = 92.0
    wave = dembow(bpm, 30)
    beats = np.arange(0, 30, 60 / bpm)
    # The network says the bar starts on the third beat of the first group of four.
    downbeats = beats[2::4]
    seen = {}

    def track(samples, rate):
        seen["rate"] = rate
        return beats, downbeats

    reading = measure(wave[:, None], RATE, lambda _stage: None, None, track)
    assert seen["rate"] == RATE
    assert reading.bpm == pytest.approx(bpm, abs=0.05)
    assert reading.downbeat == pytest.approx(float(downbeats[0] % (4 * 60 / bpm)), abs=0.03)


@pytest.mark.parametrize(
    "answer",
    [None, (np.array([0.5, 1.0]), np.array([0.5])), (np.arange(0, 12, 0.5)[:8], np.array([]))],
)
def test_a_tracker_that_finds_too_little_leaves_the_signal_reading(answer):
    wave = clicks(120, 12)[:, None]
    reading = measure(wave, RATE, lambda _stage: None, None, lambda *_args: answer)
    assert reading.bpm == pytest.approx(120.0, abs=0.01)


def test_downbeats_that_disagree_fall_back_to_the_onset_weight():
    bpm = 120.0
    wave = clicks(bpm, 20, amplitude=0.4)
    wave[:: int(round(4 * 60 / bpm * RATE))] = 1.0  # a louder hit on every bar
    beats = np.arange(0, 20, 60 / bpm)
    scattered = beats[[1, 6, 11, 16, 21 - 1]]  # every phase of four, none a majority
    reading = measure(
        wave[:, None], RATE, lambda _stage: None, None, lambda *_a: (beats, scattered)
    )
    assert reading.downbeat == pytest.approx(0.0, abs=0.03)


def test_inference_lock_is_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    started, release = threading.Event(), threading.Event()

    def hold():
        with inference_lock():
            started.set()
            release.wait(2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert started.wait(2)
    fd = os.open(tmp_path / "inference.lock", os.O_RDWR)
    try:
        assert not filelock.try_lock(fd)
    finally:
        os.close(fd)
        release.set()
        thread.join()


def test_measure_does_not_lock_or_import_torch(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    def refuse_lock():
        raise AssertionError("measure took the inference lock")

    monkeypatch.setattr("stemlab.analysis.inference_lock", refuse_lock)
    loaded = "torch" in sys.modules
    measure(clicks(120, 8)[:, None], RATE, lambda _stage: None, lambda *_args: None)
    assert ("torch" in sys.modules) is loaded


def test_separator_holds_the_lock_while_isolating(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    seen = {}

    def fake_isolate(audio, _sample_rate, kind):
        fd = os.open(tmp_path / "inference.lock", os.O_RDWR)
        try:
            seen[kind] = not filelock.try_lock(fd)
            if not seen[kind]:
                filelock.unlock(fd)
        finally:
            os.close(fd)
        return audio

    monkeypatch.setattr("stemlab.inference.isolate_window", fake_isolate)
    stages = []
    audio = np.zeros((RATE, 1), dtype=np.float32)
    separate_window = _separator(audio, RATE, stages.append)
    drums = separate_window("drums", 0.0, 1.0)
    harmonic = separate_window("harmonic", 0.0, 1.0)
    assert seen == {"drums": True, "harmonic": True}
    assert drums.shape == harmonic.shape == (RATE, 1)
    assert stages == [
        "Waiting for the separator",
        "Isolating drums and bass",
        "Waiting for the separator",
        "Isolating the harmony",
    ]


def test_separator_gives_up_when_the_gpu_stays_busy(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("stemlab.analysis._LOCK_WAIT_SECONDS", 0.6)
    started, release = threading.Event(), threading.Event()

    def hold():
        with inference_lock():
            started.set()
            release.wait(5)

    def refuse(*_args):
        raise AssertionError("isolated while another job held the GPU")

    monkeypatch.setattr("stemlab.inference.isolate_window", refuse)
    thread = threading.Thread(target=hold)
    thread.start()
    assert started.wait(2)
    try:
        separate_window = _separator(np.zeros((RATE, 1), dtype=np.float32), RATE, lambda _s: None)
        assert separate_window("harmonic", 0.0, 1.0) is None
    finally:
        release.set()
        thread.join()


def test_module_prints_json_and_does_not_lock_a_clear_mix(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    # No separator or network here: neither answers, so the signal alone is read.
    monkeypatch.setattr("stemlab.analysis._separator", lambda *_args: lambda *_a: None)
    monkeypatch.setattr("stemlab.analysis._beat_tracker", lambda _announce: lambda *_a: None)
    path = tmp_path / "clear.wav"
    wave = stereo(clicks(120, 12, amplitude=0.8) + tone(A_MINOR, 12, amplitude=0.5))
    sf.write(path, wave, RATE, subtype="FLOAT")
    assert main([str(path)]) == 0
    captured = capsys.readouterr()
    reading = json.loads(captured.out)
    assert reading["bpm"] == pytest.approx(120.0, abs=0.01)
    assert (reading["camelot"], reading["key_name"]) == ("8A", "A minor")
    assert reading["downbeat"] == pytest.approx(0.0, abs=0.02)
    assert reading["warning"] == ""
    assert "STAGE:Checking the file" in captured.err
    assert "STAGE:Reading tempo and key" in captured.err
    assert "Isolating" not in captured.err
    assert not (tmp_path / "inference.lock").exists()


def test_mood_is_brighter_for_a_major_chord_than_a_minor_one_and_stays_in_range():
    def mood_of(notes, level):
        wave = clicks(100, 12, amplitude=0.6) + tone(notes, 12, amplitude=level)
        reading = measure(stereo(wave), RATE, lambda _stage: None)
        return reading.valence, reading.energy

    major, major_energy = mood_of((60, 64, 67, 72, 76, 79), 0.5)
    minor, _ = mood_of((57, 60, 64, 69, 72, 76), 0.5)
    _, quiet_energy = mood_of((60, 64, 67, 72, 76, 79), 0.05)
    assert major > minor
    assert 0.0 <= minor <= major <= 1.0
    # The same music, much quieter, is calmer.
    assert quiet_energy < major_energy


def test_a_track_without_a_key_has_no_mood():
    reading = measure(clicks(120, 12)[:, None], RATE, lambda _stage: None)
    assert (reading.valence, reading.energy) == (None, None)


def test_the_reading_is_the_only_thing_on_stdout(monkeypatch, tmp_path, capfd):
    """A model download prints to stdout; the parent must still be able to read the result."""
    from stemlab import analysis

    path = tmp_path / "tone.wav"
    sf.write(path, np.zeros((RATE, 1), "float32"), RATE)

    class Reading:
        def to_dict(self):
            return {"bpm": 120.0, "downbeat": 0.0}

    def noisy_measure(*_args):
        print('Downloading: "https://example.test/model.ckpt"')
        os.write(1, b"native library output\n")
        return Reading()

    monkeypatch.setattr(analysis, "measure", noisy_measure)
    monkeypatch.setattr(analysis, "_separator", lambda *_args: None)
    monkeypatch.setattr(analysis, "_beat_tracker", lambda *_args: None)
    assert analysis.main([str(path)]) == 0
    out = capfd.readouterr().out
    assert json.loads(out) == {"bpm": 120.0, "downbeat": 0.0}
