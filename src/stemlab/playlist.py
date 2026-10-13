"""Order readable tracks into one Camelot and tempo path."""

# Faster pulse / slower pulse. 128/138 and 100/216 pass; 128/139 and 100/217 do not.
_TEMPO_RATIO = 1.08
# Valence runs 0 (dark) to 1 (bright). Two neighbors may differ by this much: a song cannot be
# followed at once by a much happier or sadder one, whatever its key and tempo.
_MOOD_GAP = 0.2


def order_tracks(tracks, pinned=None):
    """tracks: dicts with path, filename, bpm (float), camelot (str), key_name (str or None),
    and optionally valence and energy (0 to 1, None when unread: that track fits anywhere).
    pinned: path or None. Every track is readable and not held out.
    Returns a list of {path, filename, bpm, camelot, key_name, break, band}.
    break is false on the first row. band is None, "half", or "double".
    """
    remaining = list(tracks)
    if not remaining:
        return []
    current = _opener(remaining, pinned)
    ordered = [_row(current, False, None)]
    remaining = [track for track in remaining if track is not current]
    while remaining:
        chosen, is_break, band = _choose_next(current, remaining)
        ordered.append(_row(chosen, is_break, band))
        remaining = [track for track in remaining if track is not chosen]
        current = chosen
    return ordered


def _opener(tracks, pinned):
    if pinned is not None:
        for track in tracks:
            if track["path"] == pinned:
                return track
    return min(tracks, key=lambda track: (track["bpm"], track["filename"], track["path"]))


def _choose_next(current, remaining):
    legal = []
    for track in remaining:
        placement = _legal_placement(current, track)
        if placement is not None:
            legal.append((track, placement))
    if legal:
        track, placement = min(legal, key=lambda item: _tempo_key(item[0], item[1]))
        return track, False, placement[2]
    track = min(remaining, key=lambda item: _break_key(current, item))
    return track, True, _placement(current["bpm"], track["bpm"])[2]


def _mood_gap(left, right):
    """How far apart two tracks feel, by valence; 0 when either has no reading."""
    first, second = left.get("valence"), right.get("valence")
    if first is None or second is None:
        return 0.0
    return abs(first - second)


def _legal_placement(current, track):
    if _camelot_step(current["camelot"], track["camelot"]) > 1:
        return None
    if _mood_gap(current, track) > _MOOD_GAP:
        return None
    placement = _placement(current["bpm"], track["bpm"])
    if placement[0] > 1:
        return None
    return placement


def _tempo_key(track, placement):
    return (placement[0], placement[1], track["filename"], track["path"])


def _break_key(current, track):
    placement = _placement(current["bpm"], track["bpm"])
    step = _camelot_step(current["camelot"], track["camelot"])
    # A jump in mood is the worst break: take a track that keeps the mood before one that does not.
    mood = _mood_gap(current, track) > _MOOD_GAP
    return (mood, step, placement[0], placement[1], track["filename"], track["path"])


def _placement(current, bpm):
    """(rank, gap, band). Rank 0 is the written octave inside 8%, 1 is half or double inside 8%."""
    same = _pulse_ratio(current, bpm)
    half = _pulse_ratio(current / 2.0, bpm)
    double = _pulse_ratio(current * 2.0, bpm)
    # A written-tempo neighbor stays in that octave even when a half or double is exact.
    if same <= _TEMPO_RATIO:
        return (0, same, None)
    if half <= double and half <= _TEMPO_RATIO:
        return (1, half, "half")
    if double <= _TEMPO_RATIO:
        return (1, double, "double")
    gap, band = min(
        ((same, None), (half, "half"), (double, "double")),
        key=lambda item: (item[0], item[1] is not None),
    )
    return (2, gap, band)


def _pulse_ratio(left, right):
    faster = left if left > right else right
    slower = right if left > right else left
    return faster / slower


def _camelot_step(left, right):
    left_number, left_letter = int(left[:-1]), left[-1]
    right_number, right_letter = int(right[:-1]), right[-1]
    difference = abs(left_number - right_number)
    # 12 meets 1: the wheel is a circle of twelve, not a line.
    number_steps = min(difference, 12 - difference)
    letter_steps = 0 if left_letter == right_letter else 1
    return number_steps + letter_steps


def _row(track, is_break, band):
    return {
        "path": track["path"],
        "filename": track["filename"],
        "bpm": track["bpm"],
        "camelot": track["camelot"],
        "key_name": track["key_name"],
        "valence": track.get("valence"),
        "energy": track.get("energy"),
        "break": is_break,
        "band": band,
    }
