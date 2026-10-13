"""SQLite metadata shared by the API and single-host worker."""

import json
import sqlite3
import time
from contextlib import closing, contextmanager
from uuid import uuid4

from stemlab import filelock
from stemlab.config import settings
from stemlab.outputs import STEMS, stem_file

TERMINAL = {"completed", "failed", "cancelled"}
# Songs are kept under their own extension. Jobs of any other name were stored as WAV.
INPUT_SUFFIXES = (".wav", ".mp3", ".flac")
# Columns added after the first release. Defaults describe how older jobs were processed.
MIGRATED_COLUMNS = {
    "mode": "TEXT NOT NULL DEFAULT 'all'",
    "keep": "TEXT",
    "model": "TEXT NOT NULL DEFAULT 'htdemucs'",
    "shifts": "INTEGER NOT NULL DEFAULT 0",
    "overlap": "REAL NOT NULL DEFAULT 0.25",
    "vocals": "TEXT NOT NULL DEFAULT 'demucs'",
    "instruments_from": "TEXT NOT NULL DEFAULT 'mix'",
    "range_start": "REAL",
    "range_end": "REAL",
    "ranges": "TEXT",
    "bpm": "REAL",
    "camelot": "TEXT",
    "key_name": "TEXT",
    "downbeat": "REAL",
    "analysis_warning": "TEXT",
    # The first job of the song this one edits. NULL on jobs from before edits were grouped:
    # such a job is its own song.
    "song_id": "TEXT",
    # JSON: the intro and outro of an "extend" job. NULL for every other mode.
    "extend": "TEXT",
    # JSON: the prompt, length and seed of a "generate" job. NULL for every other mode.
    "generate": "TEXT",
}
ANALYSIS_FIELDS = {"status", "stage", "error", "bpm", "camelot", "key_name", "downbeat", "warning"}


@contextmanager
def database():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(settings.data_dir / "jobs.sqlite3", timeout=15)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL,
            stage TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
            duration REAL NOT NULL, sample_rate INTEGER NOT NULL, channels INTEGER NOT NULL,
            error TEXT, task_id TEXT NOT NULL)""")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
        if not MIGRATED_COLUMNS.keys() <= columns:
            db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            for name, definition in MIGRATED_COLUMNS.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            # Jobs from when Roformer + Demucs was a single model choice.
            db.execute(
                "UPDATE jobs SET model='htdemucs_ft', vocals='ensemble', "
                "instruments_from='residual' WHERE model='roformer_htdemucs_ft'"
            )
        db.execute("""CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, stage TEXT NOT NULL,
            error TEXT, bpm REAL, camelot TEXT, key_name TEXT, downbeat REAL,
            warning TEXT, created REAL NOT NULL, updated REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS readings (
            path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime INTEGER NOT NULL,
            bpm REAL, camelot TEXT, key_name TEXT, downbeat REAL, warning TEXT,
            valence REAL, energy REAL)""")
        # Readings cached before moods existed lack the two columns.
        cached = {row["name"] for row in db.execute("PRAGMA table_info(readings)")}
        for name in ("valence", "energy"):
            if name not in cached:
                db.execute(f"ALTER TABLE readings ADD COLUMN {name} REAL")
        yield db


def create(
    job_id,
    filename,
    info,
    quality,
    mode="all",
    keep=None,
    section=None,
    ranges=None,
    analysis=None,
    song_id=None,
    extend=None,
    generate=None,
):
    now = time.time()
    analysis = analysis or {}
    bpm = analysis.get("bpm")
    if bpm is not None:
        bpm = round(float(bpm), 2)
    with database() as db:
        db.execute(
            "INSERT INTO jobs "
            "(id, filename, status, stage, created, updated, duration, sample_rate, channels, "
            "error, task_id, mode, keep, model, vocals, instruments_from, shifts, overlap, "
            "range_start, range_end, ranges, bpm, camelot, key_name, downbeat, "
            "analysis_warning, song_id, extend, generate) VALUES "
            "(?, ?, 'queued', 'Waiting for worker', ?, ?, ?, ?, ?, NULL, "
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                filename,
                now,
                now,
                info.duration,
                info.samplerate,
                info.channels,
                str(uuid4()),
                mode,
                json.dumps(keep) if keep is not None else None,
                quality["model"],
                quality["vocals"],
                quality["instruments_from"],
                quality["shifts"],
                quality["overlap"],
                *(section or (None, None)),
                json.dumps(ranges) if ranges else None,
                bpm,
                analysis.get("camelot"),
                analysis.get("key_name"),
                analysis.get("downbeat"),
                analysis.get("analysis_warning"),
                song_id or job_id,
                json.dumps(extend) if extend else None,
                json.dumps(generate) if generate else None,
            ),
        )
    return get(job_id)


def get(job_id):
    with database() as db:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return decode(row) if row else None


def decode(row):
    result = dict(row)
    result["keep"] = json.loads(result["keep"]) if result["keep"] is not None else None
    result["ranges"] = json.loads(result["ranges"]) if result.get("ranges") else None
    result["extend"] = json.loads(result["extend"]) if result.get("extend") else None
    result["generate"] = json.loads(result["generate"]) if result.get("generate") else None
    return result


def full_stems_folder(song_id):
    """The stems folder of a finished whole-song 'all' edit of this song, or None.

    A later extended edit slices its loops out of it instead of separating them again.
    """
    with database() as db:
        rows = db.execute(
            "SELECT id FROM jobs WHERE status = 'completed' AND mode = 'all' "
            "AND range_start IS NULL AND (ranges IS NULL OR ranges = '') "
            "AND (song_id = ? OR id = ?) ORDER BY created DESC",
            (song_id, song_id),
        ).fetchall()
    for row in rows:
        folder = settings.data_dir / row["id"] / "stems"
        if all(stem_file(folder, name) for name in STEMS):
            return folder
    return None


def input_suffix(filename):
    lowered = filename.lower()
    return next((suffix for suffix in INPUT_SUFFIXES if lowered.endswith(suffix)), ".wav")


def source_path(row):
    return settings.data_dir / row["id"] / f"source{input_suffix(row['filename'])}"


def has_source(row):
    """False for a generated track, which has no uploaded song."""
    return source_path(row).is_file()


def reference_path(row):
    """The audio a generated track was asked to sound like, or None."""
    for suffix in (".wav", ".mp3", ".flac"):
        path = settings.data_dir / row["id"] / f"reference{suffix}"
        if path.is_file():
            return path
    return None


def recent():
    with database() as db:
        rows = db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 100").fetchall()
    return [decode(row) for row in rows]


def update(job_id, *, expected=None, **values):
    allowed = {"status", "stage", "error", "task_id"}
    assert values.keys() <= allowed
    values["updated"] = time.time()
    query = "UPDATE jobs SET " + ", ".join(f"{key} = ?" for key in values) + " WHERE id = ?"
    args = [*values.values(), job_id]
    if expected:
        query += " AND status IN (" + ",".join("?" for _ in expected) + ")"
        args.extend(expected)
    with database() as db:
        return db.execute(query, args).rowcount == 1


def claim(job_id, task_id):
    with database() as db:
        return (
            db.execute(
                "UPDATE jobs SET status='running', stage='Loading model', updated=? "
                "WHERE id=? AND task_id=? AND status='queued'",
                (time.time(), job_id, task_id),
            ).rowcount
            == 1
        )


def recover_stale():
    with database() as db:
        rows = db.execute(
            "SELECT id FROM jobs WHERE status IN ('running', 'cancelling') AND updated < ?",
            (time.time() - 120,),
        ).fetchall()
    for row in rows:
        folder = settings.data_dir / row["id"]
        if not folder.exists():
            continue
        with (folder / ".lock").open("a") as lock:
            if not filelock.try_lock(lock.fileno()):
                continue
            update(
                row["id"],
                expected=["running", "cancelling"],
                status="failed",
                stage="Worker interrupted",
                error="The worker stopped responding. You can retry this job.",
            )


def delete(job_id):
    with database() as db:
        db.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def create_analysis(analysis_id):
    now = time.time()
    with database() as db:
        db.execute(
            "INSERT INTO analyses (id, status, stage, error, created, updated) "
            "VALUES (?, 'running', 'Checking the file', NULL, ?, ?)",
            (analysis_id, now, now),
        )
    return get_analysis(analysis_id)


def get_analysis(analysis_id):
    with database() as db:
        row = db.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    return dict(row) if row else None


def update_analysis(analysis_id, **values):
    assert values.keys() <= ANALYSIS_FIELDS
    values["updated"] = time.time()
    query = "UPDATE analyses SET " + ", ".join(f"{key} = ?" for key in values) + " WHERE id = ?"
    with database() as db:
        return db.execute(query, [*values.values(), analysis_id]).rowcount == 1


READING_FIELDS = ("bpm", "camelot", "key_name", "downbeat", "warning", "valence", "energy")


def get_reading(path, size, mtime):
    """Return the cached reading when path, size, and mtime all match.

    mtime is st_mtime_ns so an unchanged file hits exactly.
    """
    with database() as db:
        row = db.execute("SELECT * FROM readings WHERE path = ?", (str(path),)).fetchone()
    if row is None or row["size"] != size or row["mtime"] != mtime:
        return None
    return {key: row[key] for key in READING_FIELDS}


def save_reading(path, size, mtime, reading):
    """Store one analysis result for this resolved path."""
    values = tuple(reading[key] for key in READING_FIELDS)
    with database() as db:
        db.execute(
            "INSERT INTO readings (path, size, mtime, bpm, camelot, key_name, downbeat, warning, "
            "valence, energy) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET size = excluded.size, mtime = excluded.mtime, "
            "bpm = excluded.bpm, camelot = excluded.camelot, key_name = excluded.key_name, "
            "downbeat = excluded.downbeat, warning = excluded.warning, "
            "valence = excluded.valence, energy = excluded.energy",
            (str(path), size, mtime, *values),
        )
