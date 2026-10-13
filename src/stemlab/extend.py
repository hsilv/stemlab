"""A DJ edit around one song: an intro before it and an outro after it.

Both are made from the song's own stems, cut on its bar grid. The song itself is copied
untouched between them, so only the stretches that feed the intro and the outro are ever
separated. `build` is pure numpy; `main` is the process entry point that loads audio,
separates those stretches and writes the file, and is the only place that imports torch.

Layout of the result, in bars of the song's own tempo:

    intro (N bars) | the song, its first bar starting exactly at the intro's end | outro (N bars)

The song is cut where its last steady groove ends, and the outro loops that groove while
its layers leave one by one.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from stemlab.analysis import attack_positions, inference_lock
from stemlab.config import MAX_SHIFTS, MODELS, OVERLAP_RANGE, VOCAL_MODELS, settings
from stemlab.outputs import STEM_SUFFIX, STEMS

RATE = 44100
BAR_COUNTS = (4, 8, 16, 32)
INTRO_SOURCES = ("stable_drums", "first_bars", "fragment")
INTRO_TREATMENTS = ("layered", "drums_bass", "instrumental", "mix")
OUTRO_SOURCES = ("last_bars", "fragment")
# A loop repeats this many bars of the song unless a fragment says otherwise.
LOOP_BARS = 4
# How far from the start or end of the song a steady groove is searched, in bars.
LOOK_BARS = 28
# A bar belongs to a steady groove when its drums are at least this share of the loud ones.
STABLE_SHARE = 0.5
LAYER_FADE = 0.02
# Half-width of every crossfade: loop seams and the joins with the song.
SEAM = 0.005
# A lead-in quieter than this (RMS) before the first bar is silence, not a pickup.
SILENT_LEAD = 0.003
PREVIEW_SECONDS = 12.0
PREVIEW_GAP = 1.0
BUSY = 75  # exit code when the separator stayed busy


def validate(params, duration):
    """Return the normalized parameters, or raise ValueError with a message for the listener."""
    if not isinstance(params, dict):
        raise ValueError("Choose an intro, an outro or both.")
    if "operations" in params:
        return {"operations": _operations(params["operations"], duration)}
    intro = _side(params.get("intro"), "intro", INTRO_SOURCES, INTRO_TREATMENTS, duration)
    outro = _side(params.get("outro"), "outro", OUTRO_SOURCES, None, duration)
    if intro is None and outro is None:
        raise ValueError("Choose an intro, an outro or both.")
    return {"intro": intro, "outro": outro}


def check_length(params, bpm, downbeat, duration):
    """Raise ValueError when the edit needs more bars than the song has."""
    bars = int((duration - downbeat) * bpm / 240)
    if "operations" in params:
        _check_positions(params["operations"], bars, bpm, downbeat, duration)
        return
    for name in ("intro", "outro"):
        side = params[name]
        if side and bars < min(LOOP_BARS, side["bars"]):
            raise ValueError("The song is too short for that many bars.")


def _side(raw, name, sources, treatments, duration):
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"Choose the {name} again.")
    if not raw.get("bars"):
        return None
    bars = raw["bars"]
    if bars not in BAR_COUNTS:
        raise ValueError(f"The {name} must be {', '.join(map(str, BAR_COUNTS))} bars.")
    source = raw.get("source") or sources[0]
    if source not in sources:
        raise ValueError(f"Unknown {name} source.")
    side = {"bars": bars, "source": source, "fragment": None}
    if treatments is not None:
        treatment = raw.get("treatment") or treatments[0]
        if treatment not in treatments:
            raise ValueError("Unknown intro treatment.")
        side["treatment"] = treatment
    if source == "fragment":
        fragment = raw.get("fragment")
        try:
            start, end = (float(value) for value in fragment)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Choose the {name} fragment on the waveform.") from exc
        if not (0 <= start < end <= duration + 1e-6) or not np.isfinite([start, end]).all():
            raise ValueError(f"The {name} fragment must lie inside the song.")
        side["fragment"] = [start, end]
    return side


# Manual edits: an ordered list of operations, each placing a processed fragment of the song.
ACTIONS = ("start", "end", "insert", "replace")
MAX_OPERATIONS = 12
MAX_PIECE_BARS = 64
PREVIEW_AROUND = 12.0


def _operations(raw, duration):
    if not isinstance(raw, list) or not raw:
        raise ValueError("Add at least one operation.")
    if len(raw) > MAX_OPERATIONS:
        raise ValueError(f"At most {MAX_OPERATIONS} operations.")
    return [_operation(item, number, duration) for number, item in enumerate(raw, 1)]


def _operation(raw, number, duration):
    name = f"Operation {number}"
    if not isinstance(raw, dict) or raw.get("action") not in ACTIONS:
        raise ValueError(f"{name}: choose start, end, insert or replace.")
    action = raw["action"]
    try:
        start, end = (float(value) for value in raw.get("fragment"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: choose the fragment on the waveform.") from exc
    if not (0 <= start < end <= duration + 1e-6):
        raise ValueError(f"{name}: the fragment must lie inside the song.")
    operation = {"action": action, "fragment": [start, end]}
    if action == "insert":
        operation["at"] = _bar_index(raw.get("at"), name, "position")
    elif action == "replace":
        span = raw.get("span")
        if not isinstance(span, list) or len(span) != 2:
            raise ValueError(f"{name}: choose the bars to replace.")
        first, last = _bar_index(span[0], name, "span"), _bar_index(span[1], name, "span")
        if last <= first:
            raise ValueError(f"{name}: the bars to replace must cover at least one bar.")
        operation["span"] = [first, last]
    if action != "replace":
        bars = raw.get("bars")
        if not isinstance(bars, int) or isinstance(bars, bool) or not 1 <= bars <= MAX_PIECE_BARS:
            raise ValueError(f"{name}: the length must be 1 to {MAX_PIECE_BARS} bars.")
        operation["bars"] = bars
    gains = raw.get("stems")
    try:
        operation["stems"] = {stem: _gain(gains[stem]) for stem in STEMS}
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError(f"{name}: give each sound a volume from 0 to 1.") from exc
    if not any(operation["stems"].values()):
        raise ValueError(f"{name}: choose at least one sound.")
    model = raw.get("model", settings.model)
    vocals = raw.get("vocals", settings.vocals)
    shifts = raw.get("shifts", settings.shifts)
    overlap = raw.get("overlap", settings.overlap)
    if model not in MODELS or vocals not in VOCAL_MODELS:
        raise ValueError(f"{name}: unknown model.")
    if not isinstance(shifts, int) or not 0 <= shifts <= MAX_SHIFTS:
        raise ValueError(f"{name}: shifts must be 0 to {MAX_SHIFTS}.")
    if not isinstance(overlap, (int, float)) or not OVERLAP_RANGE[0] <= overlap <= OVERLAP_RANGE[1]:
        raise ValueError(f"{name}: overlap must be {OVERLAP_RANGE[0]} to {OVERLAP_RANGE[1]}.")
    operation.update(model=model, vocals=vocals, shifts=shifts, overlap=float(overlap))
    return operation


def _gain(value):
    value = float(value)
    if not 0 <= value <= 1:
        raise ValueError("volume")
    return value


def _bar_index(value, name, what):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name}: choose the {what} as a bar number.")
    return value


def _check_positions(operations, bars, bpm, downbeat, duration):
    """Raise ValueError when an operation does not fit the song or overlaps another."""
    bar = 240 / bpm
    taken = []
    for number, operation in enumerate(operations, 1):
        name = f"Operation {number}"
        first = round((operation["fragment"][0] - downbeat) / bar)
        last = round((operation["fragment"][1] - downbeat) / bar)
        if last - first < 1:
            raise ValueError(f"{name}: the fragment must cover at least one bar.")
        if first < -1 or last > bars + 1:
            raise ValueError(f"{name}: the fragment must lie inside the song.")
        action = operation["action"]
        if action == "insert" and not 1 <= operation["at"] <= bars - 1:
            raise ValueError(f"{name}: insert between bar 2 and bar {bars}.")
        if action == "replace" and operation["span"][1] > bars:
            raise ValueError(f"{name}: the bars to replace go past the end of the song.")
        taken.append((action, number))
    for action in ("start", "end"):
        if sum(1 for kind, _ in taken if kind == action) > 1:
            raise ValueError(f"Only one {action} operation is allowed.")
    places = sorted(_place(operation) for operation in operations if _place(operation))
    for (first, last, _), (next_first, next_last, _) in zip(places, places[1:], strict=False):
        if next_first < last or (next_first == first and next_last == last):
            raise ValueError("Two operations touch the same bars.")


def _place(operation):
    """(first bar, last bar, action) an insert or replace occupies; None for start and end."""
    if operation["action"] == "insert":
        return (operation["at"], operation["at"], "insert")
    if operation["action"] == "replace":
        return (operation["span"][0], operation["span"][1], "replace")
    return None


class _Window:
    """Four stems of one stretch of the song, addressable by song time."""

    def __init__(self, stems, start):
        self.stems = stems
        self.start = start

    def cut(self, name, start, count):
        """count samples of one stem from song time start; zeros where the window has none."""
        stem = self.stems[name]
        first = round((start - self.start) * RATE)
        out = np.zeros((stem.shape[0], count), dtype=np.float32)
        lo, hi = max(0, first), min(stem.shape[1], first + count)
        if hi > lo:
            out[:, lo - first : hi - first] = stem[:, lo:hi]
        return out


class _Song:
    def __init__(self, original, bpm, downbeat, stems_for):
        self.original = original
        self.bar = 240.0 / bpm
        self.downbeat = downbeat
        self.duration = original.shape[1] / RATE
        self.stems_for = stems_for
        self.margin = self.bar / 8 + 0.05

    def window(self, start, end):
        start = max(0.0, start)
        end = min(self.duration, end)
        return _Window(self.stems_for(start, end), start)

    def bar_start(self, index):
        return self.downbeat + index * self.bar

    def bars_inside(self):
        """Number of whole bars from the first downbeat to the end of the song."""
        return int((self.duration - self.downbeat) / self.bar)


def build(original, bpm, downbeat, params, stems_for, preview=False, only=None):
    """Return (audio, info): the song with the intro and outro of params around it.

    original: float32 (2, frames) at RATE. params: the output of `validate`. stems_for(start,
    end) returns the four stems of that stretch of the song, each (2, samples) at RATE.
    With preview, only the joins are kept: the intro and the start of the song, then the
    end of the song and the outro, a second apart.
    """
    if "operations" in params:
        return build_manual(original, bpm, downbeat, params["operations"], stems_for, only)
    song = _Song(original, bpm, downbeat, stems_for)
    seam = round(SEAM * RATE)
    intro, outro = params["intro"], params["outro"]
    info = {"bpm": bpm}
    lead = original[:, : round(downbeat * RATE)]
    silent = lead.size == 0 or float(np.sqrt(np.mean(lead**2))) < SILENT_LEAD
    # Start the song at its first downbeat (less 10 ms) when what precedes it is silence.
    start = max(0.0, downbeat - 0.01) if silent else 0.0
    start_sample = round(start * RATE)

    if intro:
        loop = _intro_loop(song, intro)
        info["intro"] = {"bars": intro["bars"], "loop_start": loop[0], "loop_bars": loop[1]}
        intro_audio = _render(
            loop, song, intro["bars"], _intro_schedule(intro["treatment"], intro["bars"]), False
        )
        intro_length = round(intro["bars"] * song.bar * RATE)
        join_in = intro_length - round((downbeat - start) * RATE)
    else:
        join_in = 0

    cut = song.original.shape[1]
    if outro:
        cut_time, loop = _outro_loop(song, outro)
        cut = round(cut_time * RATE)
        info["outro"] = {"bars": outro["bars"], "loop_start": loop[0], "loop_bars": loop[1]}
        outro_audio = _render(
            loop, song, outro["bars"], _outro_schedule(outro["bars"]), True, final_fade=True
        )
    join_out = join_in + (cut - start_sample)
    outro_length = round(outro["bars"] * song.bar * RATE) if outro else 0
    total = join_out + outro_length

    out = np.zeros((original.shape[0], total + 2 * seam), dtype=np.float32)
    ramp = (np.arange(2 * seam, dtype=np.float32) + 0.5) / (2 * seam)
    if intro:
        part = intro_audio[:, : join_in + 2 * seam].copy()
        part[:, -2 * seam :] *= 1 - ramp
        out[:, : part.shape[1]] += part
    body = _slice(original, start_sample - seam, cut - start_sample + 2 * seam)
    if intro:
        body[:, : 2 * seam] *= ramp
    if outro:
        body[:, -2 * seam :] *= 1 - ramp
    out[:, join_in : join_in + body.shape[1]] += body
    if outro:
        out[:, join_out : join_out + outro_audio.shape[1]] += outro_audio
    audio = out[:, seam : seam + total]
    info["original_start"] = join_in / RATE
    info["original_end"] = join_out / RATE
    info["duration"] = total / RATE
    info["downbeat"] = 0.0 if intro else downbeat - start
    if preview:
        audio = _preview(audio, join_in, join_out, bool(intro), bool(outro))
        info["duration"] = audio.shape[1] / RATE
    return audio, info


def _slice(audio, start, count):
    """count samples from start, zeros outside the audio."""
    out = np.zeros((audio.shape[0], count), dtype=np.float32)
    lo, hi = max(0, start), min(audio.shape[1], start + count)
    if hi > lo:
        out[:, lo - start : hi - start] = audio[:, lo:hi]
    return out


def _preview(audio, join_in, join_out, has_intro, has_outro):
    keep = round(PREVIEW_SECONDS * RATE)
    parts = []
    if has_intro:
        parts.append(audio[:, : join_in + keep])
    if has_outro:
        parts.append(audio[:, max(0, join_out - keep) :])
    gap = np.zeros((audio.shape[0], round(PREVIEW_GAP * RATE)), dtype=np.float32)
    joined = []
    for part in parts:
        if joined:
            joined.append(gap)
        joined.append(part)
    return np.concatenate(joined, axis=1)


# Manual edits


def build_manual(original, bpm, downbeat, operations, piece_for, only=None):
    """Return (audio, info): the song with each operation's fragment placed as it asks.

    Positions are bars of the original song (bar 0 starts at downbeat). piece_for(index, start,
    end) returns the stems of the song from start to end seconds for operation number index:
    a dict with the four stems, or "instrumental" (all but the voice) or "mix" (the song as it
    is). Each fragment is mixed at its volumes and repeated or trimmed to its bars. With only,
    just that operation is built, cropped to PREVIEW_AROUND seconds either side of it.
    """
    song = _Song(original, bpm, downbeat, None)
    seam = round(SEAM * RATE)
    mix = _Window({"drums": original}, 0.0)
    chosen = [
        (index, operation)
        for index, operation in enumerate(operations)
        if only is None or index == only
    ]
    last = song.bars_inside()
    lead = original[:, : round(downbeat * RATE)]
    silent = lead.size == 0 or float(np.sqrt(np.mean(lead**2))) < SILENT_LEAD
    begin = max(0.0, downbeat - 0.01) if silent else 0.0

    def boundary(bar_index):
        """Where bar bar_index really starts: the grid, aligned to the song's own hits there."""
        start = song.bar_start(bar_index)
        return start + _phase_shift(mix, song, start, min(2, max(1, last - bar_index)))

    def piece(index, operation, bars):
        first, count = _fragment_bars(song, operation["fragment"], None)
        start = song.bar_start(first)
        start += _phase_shift(mix, song, start, min(count, 8))
        low = max(0.0, start - song.margin)
        high = min(song.duration, start + count * song.bar + song.margin)
        window = _Window(piece_for(index, low, high), low)
        loop_length = round(count * song.bar * RATE)
        segment = _mix_stems(window, start - SEAM, loop_length + 2 * seam, operation["stems"])
        return segment, loop_length, count

    # The song in pieces, cut on bar lines, with each fragment between them.
    items = []
    cursor = begin
    starts = [(i, o) for i, o in chosen if o["action"] == "start"]
    ends = [(i, o) for i, o in chosen if o["action"] == "end"]
    middle = sorted(
        ((i, o) for i, o in chosen if o["action"] in ("insert", "replace")),
        key=lambda item: _place(item[1])[0],
    )
    lead_cut = round((downbeat - begin) * RATE)
    for index, operation in starts:
        bars = operation["bars"]
        items.append(("piece", index, operation, bars, lead_cut))
    for index, operation in middle:
        first, after = _place(operation)[:2]
        items.append(("song", cursor, boundary(first)))
        bars = operation["bars"] if operation["action"] == "insert" else after - first
        items.append(("piece", index, operation, bars, 0))
        cursor = boundary(first) if operation["action"] == "insert" else boundary(after)
    finish = original.shape[1] / RATE
    if ends:
        finish = boundary(last)
    items.append(("song", cursor, finish))
    for index, operation in ends:
        items.append(("piece", index, operation, operation["bars"], 0))

    parts, spans = [], {}
    position = 0
    for item in items:
        if item[0] == "song":
            _kind, a, b = item
            length = round((b - a) * RATE)
            audio = _slice(original, round(a * RATE) - seam, length + 2 * seam)
        else:
            _kind, index, operation, bars, trim = item
            segment, loop_length, _count = piece(index, operation, bars)
            length = round(bars * song.bar * RATE) - trim
            audio = _tile(segment, loop_length, length, seam, True)
            spans[index] = (position, position + length)
        parts.append((audio, length))
        position += length
    audio = _assemble(parts, seam)
    info = {"duration": audio.shape[1] / RATE, "operations": len(chosen)}
    if only is not None and only in spans:
        around = round(PREVIEW_AROUND * RATE)
        first, last_sample = spans[only]
        audio = audio[:, max(0, first - around) : last_sample + around]
        info["duration"] = audio.shape[1] / RATE
    return audio, info


def _assemble(parts, seam):
    """Join (audio with seam extra samples either side, length) parts head to tail, each join a
    crossfade of 2 * seam samples centered on the boundary."""
    total = sum(length for _, length in parts)
    out = np.zeros((parts[0][0].shape[0], total + 2 * seam), dtype=np.float32)
    ramp = (np.arange(2 * seam, dtype=np.float32) + 0.5) / (2 * seam)
    at = 0
    for number, (audio, length) in enumerate(parts):
        piece = audio[:, : length + 2 * seam].copy()
        if number > 0:
            piece[:, : 2 * seam] *= ramp
        if number < len(parts) - 1:
            piece[:, -2 * seam :] *= 1 - ramp
        out[:, at : at + piece.shape[1]] += piece
        at += length
    return out[:, seam : seam + total]


def _mix_stems(window, start, count, gains):
    """The stems of window from start seconds, mixed at their volumes: (2, count)."""
    names = window.stems.keys()
    if "mix" in names:
        return window.cut("mix", start, count) * max(gains.values())
    if "instrumental" in names:
        # The three instruments share one volume when they come as one (original minus voice).
        level = max(gains["drums"], gains["bass"], gains["other"])
        return window.cut("instrumental", start, count) * level
    mixed = np.zeros((2, count), dtype=np.float32)
    for name in STEMS:
        if gains[name] and name in names:
            mixed += window.cut(name, start, count) * gains[name]
    return mixed


# Intro and outro loops


def _intro_loop(song, side):
    """(start in song seconds, bars, window): which bars repeat to make the intro."""
    bars = min(LOOP_BARS, side["bars"])
    if side["source"] == "fragment":
        first, bars = _fragment_bars(song, side["fragment"], side["bars"])
        start = song.bar_start(first)
        window = song.window(start - song.margin, start + bars * song.bar + song.margin)
    elif side["source"] == "first_bars":
        start = song.downbeat
        _need_bars(song, bars)
        window = song.window(start - song.margin, start + bars * song.bar + song.margin)
    else:
        _need_bars(song, bars)
        look = min(LOOK_BARS, song.bars_inside())
        window = song.window(song.downbeat - song.margin, song.bar_start(look) + song.margin)
        levels = _bar_levels(window, song, 0, look)
        found = _steady_run(levels, bars, from_end=False)
        start = song.bar_start(0 if found is None else found)
    start += _phase_shift(window, song, start, bars)
    return start, bars, window


def _outro_loop(song, side):
    """(song second where the song is cut, (loop start, bars, window))."""
    bars = min(LOOP_BARS, side["bars"])
    _need_bars(song, bars)
    last = song.bars_inside()
    look = min(LOOK_BARS, last)
    first = last - look
    window = song.window(song.bar_start(first) - song.margin, song.bar_start(last) + song.margin)
    levels = _bar_levels(window, song, first, look)
    found = _steady_run(levels, bars, from_end=True)
    # The song ends where its last steady groove does; with none, at its last whole bar.
    end_bar = first + (look if found is None else found + bars)
    groove = song.bar_start(end_bar - bars)
    end_window = song.window(groove - song.margin, song.bar_start(end_bar) + song.margin)
    shift = _phase_shift(end_window, song, groove, bars)
    cut = song.bar_start(end_bar) + shift
    if side["source"] == "fragment":
        index, bars = _fragment_bars(song, side["fragment"], side["bars"])
        start = song.bar_start(index)
        window = song.window(start - song.margin, start + bars * song.bar + song.margin)
        return cut, (start + _phase_shift(window, song, start, bars), bars, window)
    return cut, (groove + shift, bars, end_window)


def _need_bars(song, count):
    if song.bars_inside() < count:
        raise ValueError("The song is too short for that many bars.")


def _fragment_bars(song, fragment, limit):
    """(first bar index, bars) of the whole bars a fragment covers, at most limit."""
    start = round((fragment[0] - song.downbeat) / song.bar)
    end = round((fragment[1] - song.downbeat) / song.bar)
    if end - start < 1:
        raise ValueError("The fragment must cover at least one bar.")
    if song.bar_start(start) < -song.margin or song.bar_start(end) > song.duration + song.margin:
        raise ValueError("The fragment must lie inside the song.")
    return start, end - start if limit is None else min(end - start, limit)


def _bar_levels(window, song, first, count):
    levels = []
    size = round(song.bar * RATE)
    for index in range(count):
        drums = window.cut("drums", song.bar_start(first + index), size)
        levels.append(float(np.sqrt(np.mean(drums**2))))
    return levels


def _steady_run(levels, length, from_end):
    """Index of the first (or last) run of length bars whose drums keep up, or None."""
    levels = np.asarray(levels)
    reference = float(np.percentile(levels, 75))
    if reference < 1e-4 or len(levels) < length:
        return None
    steady = levels >= STABLE_SHARE * reference
    starts = range(len(levels) - length, -1, -1) if from_end else range(len(levels) - length + 1)
    for index in starts:
        if steady[index : index + length].all():
            return index
    return None


def _phase_shift(window, song, start, bars):
    """Seconds by which the drums' real hits sit after the grid over these bars (median).

    The song's tempo is fixed to a hundredth of a BPM, which still drifts a few hundredths of
    a second over a whole song; a loop cut from the middle or the end is aligned locally.
    """
    pad = 0.1
    drums = window.cut("drums", start - pad, round((bars * song.bar + 2 * pad) * RATE))
    centers = pad + np.arange(bars * 4) * song.bar / 4
    found = attack_positions(drums.mean(axis=0), RATE, centers, min(0.04, song.bar / 16))
    if found.shape[1] < 8:
        return 0.0
    index, seconds, strength = found
    solid = strength >= 0.3 * float(np.median(strength))
    if not solid.any():
        return 0.0
    shift = float(np.median(seconds[solid] - centers[index.astype(int)][solid]))
    return float(np.clip(shift, -song.bar / 8, song.bar / 8))


# Rendering


def _intro_schedule(treatment, bars):
    """stem -> [(bar, gain)]: which layers play from which bar of the intro."""
    schedule = {"vocals": [(0, 0.0)], "drums": [(0, 1.0)], "bass": [(0, 0.0)], "other": [(0, 0.0)]}
    if treatment == "layered":
        schedule["bass"] = [(0, 0.0), (bars // 4, 1.0)]
        schedule["other"] = [(0, 0.0), (bars // 2, 1.0)]
    elif treatment == "drums_bass":
        schedule["bass"] = [(0, 1.0)]
    elif treatment == "instrumental":
        schedule["bass"] = schedule["other"] = [(0, 1.0)]
    else:
        schedule["bass"] = schedule["other"] = schedule["vocals"] = [(0, 1.0)]
    return schedule


def _outro_schedule(bars):
    """Voice out first, then the other instruments, then the bass; drums fade in the last bar."""
    return {
        "vocals": [(0, 0.0)],
        "drums": [(0, 1.0)],
        "bass": [(0, 1.0), (bars // 2, 0.0)],
        "other": [(0, 1.0), (bars // 4, 0.0)],
    }


def _render(loop, song, bars, schedule, head, final_fade=False):
    """Audio for bars bars of loop, layers following schedule: (2, length + 2 * seam) from
    seam samples before the first bar."""
    start, loop_bars, window = loop
    seam = round(SEAM * RATE)
    length = round(bars * song.bar * RATE)
    loop_length = round(loop_bars * song.bar * RATE)
    first = round(start * RATE) - seam
    result = np.zeros((2, length + 2 * seam), dtype=np.float32)
    for name in STEMS:
        steps = schedule[name]
        if not any(gain for _, gain in steps):
            continue
        segment = window.cut(name, first / RATE, loop_length + 2 * seam)
        tiled = _tile(segment, loop_length, length, seam, head)
        envelope = _envelope(steps, song.bar, length)
        if final_fade and name == "drums":
            envelope *= _last_bar_fade(length, round(song.bar * RATE))
        result += tiled * np.pad(envelope, seam, mode="edge")
    return result


def _tile(segment, loop_length, length, seam, head):
    """segment repeated to length samples, each seam a crossfade of 2 * seam samples.

    segment holds seam extra samples before and after its loop. The first copy has no head
    ramp unless head, which an outro needs to blend into the song.
    """
    out = np.zeros((segment.shape[0], length + 2 * seam), dtype=np.float32)
    ramp = (np.arange(2 * seam, dtype=np.float32) + 0.5) / (2 * seam)
    for copy in range((length + loop_length - 1) // loop_length):
        at = copy * loop_length
        piece = segment[:, : min(loop_length + 2 * seam, out.shape[1] - at)].copy()
        if copy > 0 or head:
            piece[:, : 2 * seam] *= ramp
        if at + loop_length < length:
            piece[:, -2 * seam :] *= 1 - ramp
        out[:, at : at + piece.shape[1]] += piece
    return out


def _envelope(steps, bar, length):
    """Gain per sample from (bar, gain) steps. Each change ramps in the LAYER_FADE before its
    bar, so a layer is whole on the downbeat it enters and gone from the one it leaves."""
    fade = round(LAYER_FADE * RATE)
    envelope = np.full(length, steps[0][1], dtype=np.float32)
    for index in range(1, len(steps)):
        at = round(steps[index][0] * bar * RATE)
        before, after = steps[index - 1][1], steps[index][1]
        low = max(0, at - fade)
        envelope[at:] = after
        if at > low:
            envelope[low:at] = np.linspace(before, after, at - low + 1)[1:]
    return envelope


def _last_bar_fade(length, bar_samples):
    fade = np.ones(length, dtype=np.float32)
    count = min(bar_samples, length)
    fade[-count:] = 0.5 * (1 + np.cos(np.linspace(0, np.pi, count)))
    return fade


# Process entry point


def _announce(stage):
    print(f"STAGE:{stage}", file=sys.stderr, flush=True)


def _load(path):
    """The source as float32 (2, frames) at RATE."""
    import soxr

    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    if rate != RATE:
        audio = soxr.resample(audio, rate, RATE).astype(np.float32)
    return np.ascontiguousarray(audio[:, :2].T)


def _stems_from_files(folder):
    """stems_for that slices stems an earlier full-song separation already wrote."""
    paths = {}
    for name in STEMS:
        paths[name] = next(
            (
                folder / f"{name}{suffix}"
                for suffix in (STEM_SUFFIX, ".wav")
                if (folder / f"{name}{suffix}").is_file()
            ),
            None,
        )

    def stems_for(start, end):
        first, last = round(start * RATE), round(end * RATE)
        return {
            name: sf.read(path, start=first, stop=last, dtype="float32", always_2d=True)[0].T
            for name, path in paths.items()
        }

    return stems_for


def _stems_by_separating(original, announce, model, shifts, overlap):
    def stems_for(start, end):
        from stemlab.inference import isolate_stems

        announce("Isolating the stems")
        audio = original[:, round(start * RATE) : round(end * RATE)].T
        return isolate_stems(audio, RATE, model, shifts, overlap)

    return stems_for


def _fragment_provider(original, announce, operations):
    """piece_for for manual edits: each operation separates its own fragment as it asks."""
    from stemlab.inference import separate_fragment

    instruments = {"drums", "bass", "other"}

    def piece_for(index, start, end):
        operation = operations[index]
        gains = operation["stems"]
        clip = original[:, round(start * RATE) : round(end * RATE)]
        on = {name for name, gain in gains.items() if gain}
        if len(on) == len(STEMS) and len(set(gains.values())) == 1:
            return {"mix": clip}
        # Everything but the voice at one volume: the song minus the voice, always.
        inverse = on == instruments and len({gains[name] for name in instruments}) == 1
        announce(f"Separating fragment {index + 1}")
        return separate_fragment(
            clip.T,
            RATE,
            sorted(on, key=STEMS.index),
            inverse,
            operation["model"],
            operation["vocals"],
            operation["shifts"],
            operation["overlap"],
        )

    return piece_for


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write an intro and outro around one song.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, help="folder to write into")
    parser.add_argument("--name", default="extended")
    parser.add_argument("--params", required=True)
    parser.add_argument("--bpm", type=float, required=True)
    parser.add_argument("--downbeat", type=float, required=True)
    parser.add_argument("--model", default="htdemucs")
    parser.add_argument("--shifts", type=int, default=0)
    parser.add_argument("--overlap", type=float, default=0.25)
    parser.add_argument("--parts", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--only", type=int, help="manual edits: build just this operation")
    args = parser.parse_args(argv)

    _announce("Reading the song")
    original = _load(args.source)
    params = validate(json.loads(args.params), original.shape[1] / RATE)
    manual = "operations" in params
    if manual:
        stems_for = _fragment_provider(original, _announce, params["operations"])
    elif args.parts:
        stems_for = _stems_from_files(args.parts)
    else:
        stems_for = _stems_by_separating(original, _announce, args.model, args.shifts, args.overlap)
    uses_gpu = manual or not args.parts
    try:
        if args.preview and uses_gpu:
            # Only a preview can be asked to wait: a job already holds the lock.
            with inference_lock(wait=30):
                audio, _info = build(
                    original, args.bpm, args.downbeat, params, stems_for, True, args.only
                )
        else:
            audio, _info = build(
                original, args.bpm, args.downbeat, params, stems_for, args.preview, args.only
            )
    except TimeoutError:
        print("The separator is busy. Try again in a moment.", file=sys.stderr)
        return BUSY
    _announce("Writing FLAC")
    from stemlab.inference import encode_all

    encode_all([(audio, {"id": args.name})], RATE, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
