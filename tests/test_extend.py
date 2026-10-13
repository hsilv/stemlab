import numpy as np
import pytest

from stemlab import extend
from stemlab.extend import RATE, build, validate

BPM = 120.0
BAR = 240 / BPM
DOWNBEAT = 0.5
SECONDS = 62.0


def click_train(starts, level, drift=0.0, width=0.004):
    wave = np.zeros(int(SECONDS * RATE), dtype=np.float32)
    count = int(width * RATE)
    for time in starts:
        at = int(round((time + drift) * RATE))
        wave[at : at + count] = level * np.hanning(count + 2)[1:-1]
    return wave


def tone(frequency, level, bars=((0, 30),)):
    """A steady tone that sounds only in the given bars of the song, so the lead-in is silent."""
    times = np.arange(int(SECONDS * RATE)) / RATE
    wave = (level * np.sin(2 * np.pi * frequency * times)).astype(np.float32)
    keep = np.zeros_like(wave)
    for first, last in bars:
        lo, hi = int((DOWNBEAT + first * BAR) * RATE), int((DOWNBEAT + last * BAR) * RATE)
        keep[lo:hi] = 1
    return wave * keep


def make_song(drift=0.0, quiet_start=(0, 2), fading_end=True):
    """Stems of a 30-bar song: drums every beat, quiet in its first bars and faded at the end."""
    beats = [DOWNBEAT + k * BAR / 4 for k in range(116)]
    levels = []
    for k, time in enumerate(beats):
        bar = k // 4
        level = 1.0 if k % 4 == 0 else 0.6
        if quiet_start[0] <= bar < quiet_start[1]:
            level *= 0.05
        if fading_end and bar >= 28:
            level *= 0.02
        levels.append(level)
    drums = np.zeros(int(SECONDS * RATE), dtype=np.float32)
    for time, level in zip(beats, levels, strict=True):
        drums += click_train([time], level, drift)
    stems = {
        "drums": drums,
        "bass": tone(100.0, 0.3),
        "other": tone(440.0, 0.2),
        "vocals": tone(880.0, 0.2, bars=[(4, 8)]),
    }
    stems = {name: np.stack([wave, wave]) for name, wave in stems.items()}
    return stems


STEMS = make_song()
ORIGINAL = sum(STEMS.values())


def stems_for(stems):
    def provide(start, end):
        lo, hi = round(start * RATE), round(end * RATE)
        return {name: stem[:, lo:hi] for name, stem in stems.items()}

    return provide


def run(params, stems=STEMS, original=None, **kwargs):
    original = ORIGINAL if original is None else original
    params = validate(params, original.shape[1] / RATE)
    return build(original, BPM, DOWNBEAT, params, stems_for(stems), **kwargs)


def level_at(audio, frequency, start, length=BAR / 2):
    """Strength of one frequency in audio from start seconds (a single-bin Fourier sum)."""
    lo = int(start * RATE)
    chunk = audio[0, lo : lo + int(length * RATE)]
    times = np.arange(len(chunk)) / RATE
    return float(abs(np.sum(chunk * np.exp(-2j * np.pi * frequency * times))) / len(chunk))


def test_validate_normalizes_and_rejects_bad_choices():
    ok = validate({"intro": {"bars": 8}, "outro": {"bars": 0}}, 100)
    assert ok == {
        "intro": {"bars": 8, "source": "stable_drums", "fragment": None, "treatment": "layered"},
        "outro": None,
    }
    for bad in (
        None,
        {},
        {"intro": {"bars": 0}},
        {"intro": {"bars": 5}},
        {"intro": {"bars": 8, "source": "x"}},
        {"intro": {"bars": 8, "treatment": "x"}},
        {"intro": {"bars": 8, "source": "fragment"}},
        {"intro": {"bars": 8, "source": "fragment", "fragment": [5, 2]}},
        {"outro": {"bars": 8, "source": "fragment", "fragment": [5, 500]}},
        {"outro": {"bars": 8, "source": "first_bars"}},
    ):
        with pytest.raises(ValueError):
            validate(bad, 100)


def test_the_song_starts_exactly_where_the_intro_ends_and_is_untouched():
    audio, info = run({"intro": {"bars": 4}})
    assert info["intro"]["bars"] == 4 and info["downbeat"] == 0.0
    # Silent lead-in: the song starts 10 ms before its first downbeat, which lands on bar 4.
    start = round((4 * BAR - 0.01) * RATE)
    assert info["original_start"] == pytest.approx(4 * BAR - 0.01, abs=1e-4)
    first = round((DOWNBEAT - 0.01) * RATE)
    seam = round(extend.SEAM * RATE)
    count = 40 * RATE
    np.testing.assert_array_equal(
        audio[:, start + 2 * seam : start + count], ORIGINAL[:, first + 2 * seam : first + count]
    )
    assert audio.shape[1] == start + ORIGINAL.shape[1] - first
    # The first drum hit of the song is on the downbeat of bar 4, to a millisecond.
    hit = start + 2 * seam + int(np.argmax(np.abs(audio[0, start + 2 * seam : start + RATE])))
    # (the click peaks 2 ms after it starts)
    assert hit / RATE == pytest.approx(4 * BAR + 0.002, abs=0.001)


def test_layered_intro_adds_drums_then_bass_then_other_and_never_the_voice():
    audio, _info = run({"intro": {"bars": 8, "source": "first_bars", "treatment": "layered"}})
    bar = lambda n: n * BAR + 0.1  # noqa: E731 - just past each bar line
    assert level_at(audio, 100, bar(0)) < 0.005 and level_at(audio, 440, bar(0)) < 0.005
    assert level_at(audio, 100, bar(1)) < 0.005 and level_at(audio, 100, bar(2)) > 0.1
    assert level_at(audio, 440, bar(3)) < 0.005 and level_at(audio, 440, bar(4)) > 0.07
    assert max(level_at(audio, 880, bar(n)) for n in range(8)) < 0.005


@pytest.mark.parametrize(
    ("treatment", "bass", "other", "voice"),
    [
        ("drums_bass", True, False, False),
        ("instrumental", True, True, False),
        ("mix", True, True, True),
    ],
)
def test_other_treatments_choose_their_layers_from_the_first_bar(treatment, bass, other, voice):
    # The voice sings in bars 4 to 8 of the song, so loop those bars.
    audio, _info = run(
        {
            "intro": {
                "bars": 4,
                "source": "fragment",
                "fragment": [4.5 + 4 * BAR, 4.5 + 8 * BAR - 1],
                "treatment": treatment,
            }
        }
    )
    heard = [level_at(audio, f, 0.1) > 0.04 for f in (100, 440, 880)]
    assert heard == [bass, other, voice]


def test_a_steady_groove_is_found_after_a_quiet_start():
    _audio, info = run({"intro": {"bars": 4, "source": "stable_drums"}})
    # The drums are quiet in the first two bars, so the loop starts at bar 2.
    assert info["intro"]["loop_start"] == pytest.approx(DOWNBEAT + 2 * BAR, abs=0.003)
    assert info["intro"]["loop_bars"] == 4
    _audio, first = run({"intro": {"bars": 4, "source": "first_bars"}})
    assert first["intro"]["loop_start"] == pytest.approx(DOWNBEAT, abs=0.003)


def test_a_loop_cut_from_drifted_drums_is_aligned_to_the_real_hits():
    drifted = make_song(drift=0.03)
    original = sum(drifted.values())
    _audio, info = run({"intro": {"bars": 4, "source": "stable_drums"}}, drifted, original)
    assert info["intro"]["loop_start"] == pytest.approx(DOWNBEAT + 2 * BAR + 0.03, abs=0.004)


def test_loop_seams_repeat_the_loop_exactly_and_do_not_click():
    audio, _info = run({"intro": {"bars": 16, "source": "stable_drums", "treatment": "drums_bass"}})
    loop = round(4 * BAR * RATE)
    seam = round(extend.SEAM * RATE)
    # Outside the crossfades, the second copy is the first, sample for sample.
    first = audio[:, 2 * seam : loop - 2 * seam]
    second = audio[:, loop + 2 * seam : 2 * loop - 2 * seam]
    np.testing.assert_allclose(first, second, atol=1e-6)
    # The seam itself is no louder a jump than anything inside the loop.
    steps = np.abs(np.diff(audio[0, : 3 * loop]))
    around = steps[loop - 3 * seam : loop + 3 * seam].max()
    assert around <= 1.5 * steps[2 * seam : loop - 2 * seam].max()


def test_outro_cuts_the_song_where_its_groove_ends_and_strips_the_layers():
    audio, info = run({"outro": {"bars": 8}})
    # The drums fade away in the last two bars of the song, so it is cut after bar 27.
    cut = DOWNBEAT + 28 * BAR
    assert info["original_end"] == pytest.approx(cut - (DOWNBEAT - 0.01), abs=0.005)
    assert info["duration"] == pytest.approx(info["original_end"] + 8 * BAR, abs=1e-3)
    end = info["original_end"]
    # Voice out at once, other instruments after two bars, bass after four, drums last.
    assert level_at(audio, 880, end + 0.1) < 0.005
    assert (
        level_at(audio, 440, end + 0.1) > 0.07 and level_at(audio, 440, end + 2 * BAR + 0.1) < 0.005
    )
    assert (
        level_at(audio, 100, end + 3 * BAR + 0.1) > 0.1
        and level_at(audio, 100, end + 4 * BAR + 0.1) < 0.005
    )
    # The drums go to silence over the last bar.
    assert np.max(np.abs(audio[:, -200:])) < 1e-3
    assert audio.shape[1] == round(info["duration"] * RATE)


def test_intro_and_outro_together_and_the_preview_keeps_only_the_joins():
    audio, info = run({"intro": {"bars": 4}, "outro": {"bars": 4}})
    assert info["duration"] == pytest.approx(info["original_end"] + 4 * BAR, abs=1e-3)
    assert info["original_start"] == pytest.approx(4 * BAR - 0.01, abs=1e-3)
    preview, brief = run({"intro": {"bars": 4}, "outro": {"bars": 4}}, preview=True)
    assert brief["duration"] == pytest.approx(
        4 * BAR + extend.PREVIEW_SECONDS + extend.PREVIEW_GAP + extend.PREVIEW_SECONDS + 4 * BAR,
        abs=0.05,
    )
    assert preview.shape[1] < 0.7 * audio.shape[1]


def test_a_song_with_an_audible_lead_keeps_it_over_the_intro():
    lead = np.zeros_like(ORIGINAL)
    lead[:, : int(0.3 * RATE)] = 0.2
    audio, info = run({"intro": {"bars": 4}}, original=ORIGINAL + lead)
    assert info["original_start"] == pytest.approx(4 * BAR - DOWNBEAT, abs=1e-3)


def test_too_short_a_song_or_fragment_is_refused():
    short = ORIGINAL[:, : 6 * RATE]
    with pytest.raises(ValueError, match="too short"):
        run({"intro": {"bars": 8}}, original=short)
    with pytest.raises(ValueError, match="at least one bar"):
        run({"intro": {"bars": 8, "source": "fragment", "fragment": [5.0, 5.5]}})


# Manual edits

ALL = {"vocals": 1.0, "drums": 1.0, "bass": 1.0, "other": 1.0}


def operation(action, fragment, **kwargs):
    base = {"action": action, "fragment": fragment, "stems": ALL, "bars": 4}
    return {**base, **kwargs}


def manual(operations, only=None, stems=STEMS, original=None):
    original = ORIGINAL if original is None else original
    checked = validate({"operations": operations}, original.shape[1] / RATE)
    extend.check_length(checked, BPM, DOWNBEAT, original.shape[1] / RATE)
    provide = stems_for(stems)

    def piece_for(index, start, end):
        return provide(start, end)

    return extend.build_manual(original, BPM, DOWNBEAT, checked["operations"], piece_for, only)


def bars(audio):
    return audio.shape[1] / RATE / BAR


# Bars 4 to 8 of the song carry the voice (880 Hz); bars 2 to 6 are the loud, steady drums.
VOICE_BARS = [DOWNBEAT + 4 * BAR, DOWNBEAT + 8 * BAR]
# The song has a silent lead-in, so it starts 10 ms before its first downbeat.
LEAD = DOWNBEAT - 0.01
SONG = ORIGINAL.shape[1] / RATE
WHOLE_BARS = int((SONG - DOWNBEAT) / BAR)


def test_a_fragment_pasted_at_the_start_comes_before_the_song_on_the_bar_line():
    audio, _info = manual([operation("start", VOICE_BARS, bars=8)])
    # 8 bars of the fragment (the last 10 ms are the song's lead-in), then the whole song.
    assert audio.shape[1] / RATE == pytest.approx(8 * BAR - 0.01 + (SONG - LEAD), abs=1e-3)
    # The fragment is bars 4 to 8, which carry the voice, repeated to fill 8 bars.
    assert level_at(audio, 880, 0.1) > 0.07 and level_at(audio, 880, 4 * BAR + 0.1) > 0.07
    start = round((8 * BAR - 0.01) * RATE)
    first = round(LEAD * RATE)
    seam = round(extend.SEAM * RATE)
    np.testing.assert_array_equal(
        audio[:, start + 2 * seam : start + 20 * RATE],
        ORIGINAL[:, first + 2 * seam : first + 20 * RATE],
    )


def test_inserting_in_the_middle_delays_the_rest_of_the_song_by_whole_bars():
    audio, _info = manual([operation("insert", VOICE_BARS, at=12, bars=4)])
    assert audio.shape[1] / RATE == pytest.approx(SONG - LEAD + 4 * BAR, abs=0.02)
    seam = round(extend.SEAM * RATE)
    lead = round(LEAD * RATE)
    cut = round((DOWNBEAT + 12 * BAR) * RATE)
    # Before the join the song is untouched; after the four inserted bars it carries on.
    np.testing.assert_array_equal(
        audio[:, 20 * RATE - lead : cut - lead - 2 * seam], ORIGINAL[:, 20 * RATE : cut - 2 * seam]
    )
    later = cut - lead + round(4 * BAR * RATE)
    count = 10 * RATE
    np.testing.assert_allclose(
        audio[:, later + 2 * seam : later + count],
        ORIGINAL[:, cut + 2 * seam : cut + count],
        atol=1e-6,
    )
    # The inserted bars are the fragment: the voice sings there, and not just before it.
    assert level_at(audio, 880, DOWNBEAT + 12 * BAR - LEAD + 0.2) > 0.07
    assert level_at(audio, 880, DOWNBEAT + 11 * BAR - LEAD) < 0.005


def test_replacing_bars_swaps_exactly_those_bars_and_keeps_the_length():
    audio, _info = manual([operation("replace", VOICE_BARS, span=[14, 18])])
    assert audio.shape[1] / RATE == pytest.approx(SONG - LEAD, abs=0.02)
    # The voice (880 Hz) sings only in bars 4 to 8 of the song, and now also in 14 to 18.
    at = lambda bar: bar * BAR + (DOWNBEAT - LEAD) + 0.2  # noqa: E731
    assert level_at(audio, 880, at(15)) > 0.07
    assert level_at(audio, 880, at(10)) < 0.005 and level_at(audio, 880, at(20)) < 0.005


def test_a_fragment_longer_than_the_hole_is_trimmed_and_shorter_is_repeated():
    long, _ = manual([operation("replace", [DOWNBEAT, DOWNBEAT + 8 * BAR], span=[20, 22])])
    short, _ = manual(
        [operation("replace", [DOWNBEAT + 2 * BAR, DOWNBEAT + 3 * BAR], span=[20, 24])]
    )
    for audio in (long, short):
        assert audio.shape[1] / RATE == pytest.approx(SONG - LEAD, abs=0.02)


def test_the_end_operation_cuts_at_the_last_whole_bar_and_appends():
    audio, _info = manual([operation("end", VOICE_BARS, bars=4)])
    assert audio.shape[1] / RATE == pytest.approx(0.01 + WHOLE_BARS * BAR + 4 * BAR, abs=0.03)
    assert level_at(audio, 880, 0.01 + WHOLE_BARS * BAR + 0.2) > 0.07


def test_volumes_and_muting_decide_what_the_fragment_plays():
    stems = {"vocals": 0.0, "drums": 1.0, "bass": 0.5, "other": 0.0}
    audio, _info = manual([operation("start", VOICE_BARS, bars=4, stems=stems)])
    assert level_at(audio, 880, 0.2) < 0.005 and level_at(audio, 440, 0.2) < 0.005
    assert level_at(audio, 100, 0.2) == pytest.approx(0.3 * 0.5 / 2, rel=0.2)


def test_a_provider_that_gives_the_instrumental_or_the_mix_is_used_as_given():
    instrumental = {"instrumental": ORIGINAL - STEMS["vocals"]}
    voiceless = {"vocals": 0.0, "drums": 1.0, "bass": 1.0, "other": 1.0}
    audio, _info = manual(
        [operation("start", VOICE_BARS, bars=4, stems=voiceless)], stems=instrumental
    )
    assert level_at(audio, 880, 0.2) < 0.005 and level_at(audio, 100, 0.2) > 0.1
    mixed = {"mix": ORIGINAL}
    audio, _info = manual([operation("start", VOICE_BARS, bars=4)], stems=mixed)
    assert level_at(audio, 880, 0.2) > 0.07


def test_several_operations_apply_to_the_original_bars_in_any_order_given():
    audio, _info = manual(
        [
            operation("insert", VOICE_BARS, at=20, bars=2),
            operation("start", VOICE_BARS, bars=4),
            operation("end", VOICE_BARS, bars=2),
        ]
    )
    # 4 bars in front, the song to its last whole bar, 2 bars inserted and 2 at the end.
    assert audio.shape[1] / RATE == pytest.approx((4 + WHOLE_BARS + 2 + 2) * BAR, abs=0.03)


def test_a_preview_keeps_one_operation_and_its_surroundings():
    operations = [
        operation("insert", VOICE_BARS, at=12, bars=4),
        operation("start", VOICE_BARS, bars=4),
    ]
    audio, info = manual(operations, only=0)
    # 4 inserted bars plus 12 seconds on either side.
    assert info["duration"] == pytest.approx(4 * BAR + 2 * extend.PREVIEW_AROUND, abs=0.05)
    assert audio.shape[1] / RATE == pytest.approx(info["duration"], abs=1e-3)


@pytest.mark.parametrize(
    "operations",
    [
        [],
        [operation("move", VOICE_BARS)],
        [operation("insert", VOICE_BARS, at=3, bars=0)],
        [operation("insert", VOICE_BARS, at=3, bars=65)],
        [operation("replace", VOICE_BARS, span=[5, 5])],
        [operation("start", VOICE_BARS, stems={"vocals": 0, "drums": 0, "bass": 0, "other": 0})],
        [operation("start", VOICE_BARS, stems={"vocals": 2, "drums": 1, "bass": 1, "other": 1})],
        [operation("start", [10, 5])],
        [operation("start", VOICE_BARS, model="nope")],
        [operation("start", VOICE_BARS, shifts=99)],
        [operation("start", VOICE_BARS), operation("start", VOICE_BARS)],
        [operation("insert", VOICE_BARS, at=10), operation("replace", VOICE_BARS, span=[8, 12])],
        [operation("insert", VOICE_BARS, at=0, bars=2)],
        [operation("insert", VOICE_BARS, at=999, bars=2)],
        [operation("replace", VOICE_BARS, span=[20, 99])],
    ],
)
def test_manual_operations_that_make_no_sense_are_refused(operations):
    with pytest.raises(ValueError):
        manual(operations)
