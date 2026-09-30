"""SQLite metadata shared by the API and single-host worker."""

import fcntl
import json
import sqlite3
import time
from contextlib import closing, contextmanager
from uuid import uuid4

from stemlab.config import settings

TERMINAL = {"completed", "failed", "cancelled"}
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
        yield db


def create(
    job_id, filename, info, quality, mode="all", keep=None, section=None, ranges=None, analysis=None
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
            "analysis_warning) VALUES "
            "(?, ?, 'queued', 'Waiting for worker', ?, ?, ?, ?, ?, NULL, "
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    return result


def source_path(row):
    suffix = ".mp3" if row["filename"].lower().endswith(".mp3") else ".wav"
    return settings.data_dir / row["id"] / f"source{suffix}"


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
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
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
