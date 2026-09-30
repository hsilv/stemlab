import sqlite3

import pytest
from fastapi.testclient import TestClient

from stemlab.config import settings
from stemlab.main import app

SCHEMA = """
CREATE TABLE track_locations (id INTEGER PRIMARY KEY, filename TEXT, fs_deleted INTEGER);
CREATE TABLE library (id INTEGER PRIMARY KEY, location INTEGER, samplerate INTEGER,
                      mixxx_deleted INTEGER);
CREATE TABLE cues (id INTEGER PRIMARY KEY, track_id INTEGER, type INTEGER, position REAL,
                   hotcue INTEGER, label TEXT);
"""


@pytest.fixture
def mixxx_db(tmp_path, monkeypatch):
    path = tmp_path / "mixxxdb.sqlite"
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    monkeypatch.setattr(settings, "mixxx_db", path)
    yield db
    db.close()


def add_track(db, track_id, filename, *, rate=44100, deleted=0):
    db.execute("INSERT INTO track_locations VALUES (?, ?, 0)", (track_id, filename))
    db.execute("INSERT INTO library VALUES (?, ?, ?, ?)", (track_id, track_id, rate, deleted))


def add_cue(db, track_id, kind, position, hotcue, label=""):
    db.execute(
        "INSERT INTO cues (track_id, type, position, hotcue, label) VALUES (?, ?, ?, ?, ?)",
        (track_id, kind, position, hotcue, label),
    )
    db.commit()


def cues(name):
    with TestClient(app) as client:
        return client.get("/api/mixxx/cues", params={"filename": name}).json()


def test_hot_cues_are_converted_to_seconds_and_sorted(mixxx_db):
    add_track(mixxx_db, 1, "song.mp3")
    add_cue(mixxx_db, 1, 1, 2 * 44100 * 30, 1, "Drop")  # interleaved stereo samples -> 30 s
    add_cue(mixxx_db, 1, 1, 2 * 44100 * 5, 0)
    assert cues("song.mp3") == [
        {"label": "Hot cue 1", "time": 5.0},
        {"label": "Drop", "time": 30.0},
    ]


def test_only_hot_cues_are_returned(mixxx_db):
    add_track(mixxx_db, 1, "song.mp3")
    add_cue(mixxx_db, 1, 2, 88200, -1)  # main cue
    add_cue(mixxx_db, 1, 6, 88200, -1)  # intro
    add_cue(mixxx_db, 1, 1, 88200, -1)  # hot cue slot that is not set
    assert cues("song.mp3") == []


@pytest.mark.parametrize("name", ["unknown.mp3", "SONG.MP3"])
def test_unknown_track_gives_no_cues(mixxx_db, name):
    add_track(mixxx_db, 1, "song.mp3")
    add_cue(mixxx_db, 1, 1, 88200, 0)
    assert cues(name) == []


def test_ambiguous_or_deleted_tracks_give_no_cues(mixxx_db):
    add_track(mixxx_db, 1, "same.mp3")
    add_track(mixxx_db, 2, "same.mp3")
    add_track(mixxx_db, 3, "gone.mp3", deleted=1)
    for track_id in (1, 2, 3):
        add_cue(mixxx_db, track_id, 1, 88200, 0)
    assert cues("same.mp3") == []
    assert cues("gone.mp3") == []


def test_missing_database_gives_no_cues(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mixxx_db", tmp_path / "absent.sqlite")
    assert cues("song.mp3") == []
