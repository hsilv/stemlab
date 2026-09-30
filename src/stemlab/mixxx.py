"""Hot cues from a local Mixxx library. Mixxx keeps them in its own database, not in the files."""

import sqlite3

from stemlab.config import settings

HOT_CUE = 1  # Mixxx's cue type for hot cues; main cue, intro and outro markers use other types.


def hot_cues(filename):
    """Return [{label, time}] (seconds) for the library track with this file name.

    Empty when Mixxx is not installed, the track is unknown, or the name matches several tracks.
    """
    if not settings.mixxx_db.is_file():
        return []
    # Read-only, so Mixxx (which may be running) is never disturbed.
    with sqlite3.connect(f"file:{settings.mixxx_db}?mode=ro", uri=True, timeout=2) as db:
        tracks = db.execute(
            "SELECT library.id, library.samplerate FROM library "
            "JOIN track_locations ON track_locations.id = library.location "
            "WHERE track_locations.filename = ? AND library.mixxx_deleted = 0 "
            "AND track_locations.fs_deleted = 0",
            (filename,),
        ).fetchall()
        if len(tracks) != 1:
            return []
        track_id, rate = tracks[0]
        cues = db.execute(
            "SELECT position, hotcue, label FROM cues "
            "WHERE track_id = ? AND type = ? AND hotcue >= 0",
            (track_id, HOT_CUE),
        ).fetchall()
    # Positions count interleaved stereo samples.
    return sorted(
        (
            {"label": label or f"Hot cue {hotcue + 1}", "time": position / (2 * rate)}
            for position, hotcue, label in cues
        ),
        key=lambda cue: cue["time"],
    )
