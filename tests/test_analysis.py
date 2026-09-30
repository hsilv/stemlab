import fcntl
import json
import os
import sys
import threading

import numpy as np
import pytest
import soundfile as sf

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
        return tone(C_MAJOR, length)[:, None]

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
    for kind, start, end in calls:
        assert kind in {"drums", "instrumental"}
        assert end - start == pytest.approx(45, abs=1)


def test_clear_mix_does_not_isolate():
    wave = stereo(clicks(120, 12, amplitude=0.8) + tone(A_MINOR, 12, amplitude=0.5))
    calls = []
    stages = []
    reading = measure(wave, RATE, stages.append, lambda *args: calls.append(args))
    assert calls == []
    assert stages == ["Reading tempo and key"]
    assert reading.bpm == pytest.approx(120.0, abs=0.01)
    assert (reading.camelot, reading.key_name) == ("8A", "A minor")
    assert reading.downbeat == pytest.approx(0.0, abs=0.02)
    assert reading.warning == ""
    assert set(reading.to_dict()) == {"bpm", "camelot", "key_name", "downbeat", "warning"}


def test_tied_mix_isolates_drums():
    duration = 30
    mixed = np.concatenate([clicks(100, duration), clicks(147, duration)])
    mixed = mixed + tone(A_MINOR, duration * 2, amplitude=0.35)
    calls = []

    def separate_window(kind, start, end):
        calls.append((kind, start, end))
        return None

    reading = measure(mixed[:, None], RATE, lambda _stage: None, separate_window)
    assert len(calls) == 1
    kind, start, end = calls[0]
    assert kind == "drums"
    assert start >= 0
    assert end <= duration * 2 + 0.05
    assert end - start == pytest.approx(45, abs=1)
    assert reading.warning == "Part of the track does not hold this grid."
    assert (reading.camelot, reading.key_name) == ("8A", "A minor")


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
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            seen[kind] = True
        else:
            seen[kind] = False
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        return audio

    monkeypatch.setattr("stemlab.inference.isolate_window", fake_isolate)
    stages = []
    audio = np.zeros((RATE, 1), dtype=np.float32)
    separate_window = _separator(audio, RATE, stages.append)
    drums = separate_window("drums", 0.0, 1.0)
    instrumental = separate_window("instrumental", 0.0, 1.0)
    assert seen == {"drums": True, "instrumental": True}
    assert drums.shape == instrumental.shape == (RATE, 1)
    assert stages == [
        "Waiting for the separator",
        "Isolating drums and bass",
        "Waiting for the separator",
        "Isolating the instrumental",
    ]


def test_module_prints_json_and_does_not_lock_a_clear_mix(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
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
