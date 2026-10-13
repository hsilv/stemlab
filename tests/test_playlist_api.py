import io
import json
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from stemlab import jobs
from stemlab.config import settings
from stemlab.main import app
from stemlab.routes import analysis_interpreter


class Finished:
    def __init__(self, code):
        self.returncode = code

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class Holding:
    """Stays running until release is set, then exits 0."""

    def __init__(self):
        self.returncode = None
        self.release = threading.Event()
        self.entered = threading.Event()

    def poll(self):
        self.entered.set()
        if self.release.is_set() and self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self.release.set()

    def kill(self):
        self.returncode = -9
        self.release.set()

    def wait(self, timeout=None):
        if not self.release.wait(timeout):
            raise subprocess.TimeoutExpired("analysis", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class Stubborn:
    """terminate does not stop it; kill does."""

    def __init__(self):
        self.returncode = None
        self.entered = threading.Event()
        self.terminated = False
        self.killed = False

    def poll(self):
        self.entered.set()
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("analysis", timeout)
        return self.returncode


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "queue_mode", "local")
    with TestClient(app) as test_client:
        yield test_client


def wav():
    data = np.zeros((16000, 2), dtype="float32")
    buffer = io.BytesIO()
    sf.write(buffer, data, 16000, format="WAV", subtype="FLOAT")
    return buffer.getvalue()


READING = {
    "bpm": 128.04,
    "camelot": "8A",
    "key_name": "A minor",
    "downbeat": 0.5,
    "warning": "",
}


def install_order_tracks(monkeypatch, fn):
    name = "stemlab.playlist"
    module = sys.modules.get(name)
    if module is None:
        try:
            module = __import__(name, fromlist=["order_tracks"])
        except (ImportError, SyntaxError):
            module = types.ModuleType(name)
            monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(module, "order_tracks", fn, raising=False)


def wait_scan(client, scan_id):
    deadline = time.monotonic() + 5
    body = None
    while time.monotonic() < deadline:
        body = client.get(f"/api/playlist/scans/{scan_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(body)


def settle(client, scan_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body = client.get(f"/api/playlist/scans/{scan_id}").json()
        if body["status"] != "running":
            return
        time.sleep(0.02)


def write_audio(folder):
    folder.mkdir(parents=True, exist_ok=True)
    track = folder / "track.wav"
    track.write_bytes(wav())
    return track


def test_browse_lists_child_folders(client, tmp_path):
    library = tmp_path / "library"
    (library / "USB").mkdir(parents=True)
    (library / "Alpha").mkdir()
    (library / ".hidden").mkdir()
    (library / "song.wav").write_bytes(wav())
    body = client.get("/api/playlist/browse", params={"path": str(library)}).json()
    assert body["path"] == str(library.resolve())
    assert body["parent"] == str(library.parent.resolve())
    assert body["directories"] == [{"name": "Alpha"}, {"name": "USB"}]
    root = client.get("/api/playlist/browse", params={"path": "/"}).json()
    assert root["path"] == "/"
    assert root["parent"] is None
    assert client.get("/api/playlist/browse", params={"path": "relative"}).status_code == 404
    track = write_audio(tmp_path / "loose")
    assert client.post("/api/playlist/scans", json={"path": str(track)}).status_code == 422
    missing = tmp_path / "missing"
    assert client.post("/api/playlist/scans", json={"path": str(missing)}).status_code == 404
    assert client.get(f"/api/playlist/scans/{uuid4()}").status_code == 404


class _Dialog:
    def __init__(self, code, stdout="", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


def test_pick_uses_zenity_and_validates_without_scanning(client, monkeypatch, tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    calls = []

    def which(name):
        return "/usr/bin/zenity" if name == "zenity" else None

    def run(argv, **kwargs):
        calls.append(list(argv))
        return _Dialog(0, f"{library}\n")

    monkeypatch.setattr("stemlab.routes.shutil.which", which)
    monkeypatch.setattr("stemlab.routes.subprocess.run", run)
    response = client.post("/api/playlist/pick")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "cancelled": False,
        "path": str(library.resolve()),
        "name": "library",
    }
    assert calls == [
        ["/usr/bin/zenity", "--file-selection", "--directory", "--title=Choose a folder"]
    ]
    assert "id" not in body


def test_pick_cancel_does_not_scan(client, monkeypatch):
    def which(name):
        return "/usr/bin/zenity" if name == "zenity" else None

    monkeypatch.setattr("stemlab.routes.shutil.which", which)
    monkeypatch.setattr("stemlab.routes.subprocess.run", lambda argv, **kwargs: _Dialog(1))
    assert client.post("/api/playlist/pick").json() == {"cancelled": True}


def test_pick_missing_directory_is_not_found(client, monkeypatch, tmp_path):
    missing = tmp_path / "missing"

    def which(name):
        return "/usr/bin/zenity" if name == "zenity" else None

    monkeypatch.setattr("stemlab.routes.shutil.which", which)
    monkeypatch.setattr(
        "stemlab.routes.subprocess.run",
        lambda argv, **kwargs: _Dialog(0, str(missing)),
    )
    response = client.post("/api/playlist/pick")
    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found."


def test_pick_without_a_dialog(client, monkeypatch):
    monkeypatch.setattr("stemlab.routes.shutil.which", lambda name: None)

    def unavailable():
        raise OSError("tkinter")

    monkeypatch.setattr("stemlab.routes._tk_directory", unavailable)
    response = client.post("/api/playlist/pick")
    assert response.status_code == 503
    assert response.json()["detail"] == "No folder dialog is available."


def test_scan_skips_nested_other_types_dotfiles_and_escaped_symlinks(client, monkeypatch, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    keep = folder / "keep.wav"
    keep.write_bytes(wav())
    (folder / "alias.wav").symlink_to(keep)
    (folder / "notes.txt").write_bytes(b"notes")
    (folder / "song.flac").write_bytes(b"flac")
    (folder / ".hidden.wav").write_bytes(wav())
    nested = folder / "nested"
    nested.mkdir()
    inner = nested / "inner.wav"
    inner.write_bytes(wav())
    (folder / "nested.wav").symlink_to(inner)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.wav"
    secret.write_bytes(wav())
    (folder / "escape.wav").symlink_to(secret)
    (folder / "linked").symlink_to(outside)
    calls = []

    def fake(command, **kwargs):
        calls.append(Path(command[-1]))
        assert command[0] == str(analysis_interpreter())
        assert command[1:-1] == ["-m", "stemlab.analysis"]
        kwargs["stdout"].write(json.dumps(READING))
        return Finished(0)

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    response = client.post("/api/playlist/scans", json={"path": str(folder)})
    assert response.status_code == 202
    started = response.json()
    assert set(started) == {"id", "status", "done", "total"}
    assert started["status"] == "running"
    assert (started["done"], started["total"]) == (0, 1)
    done = wait_scan(client, started["id"])
    assert done["status"] == "completed"
    assert done["current"] is None
    assert done["done"] == 1
    assert [row["path"] for row in done["tracks"]] == [str(keep.resolve())]
    assert done["unread"] == []
    assert calls == [keep.resolve()]
    assert keep.is_file()
    assert secret.resolve() not in calls
    assert inner.resolve() not in calls


def test_readings_cache_skips_the_analyzer_until_the_file_changes(client, monkeypatch, tmp_path):
    track = write_audio(tmp_path / "music")
    calls = []

    def fake(command, **kwargs):
        calls.append(command[-1])
        assert Path(command[-1]) == track.resolve()
        kwargs["stdout"].write(json.dumps(READING))
        return Finished(0)

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    first = client.post("/api/playlist/scans", json={"path": str(track.parent)}).json()
    done = wait_scan(client, first["id"])
    assert done["tracks"][0]["bpm"] == pytest.approx(128.04)
    assert done["tracks"][0]["camelot"] == "8A"
    with jobs.database() as db:
        columns = [row["name"] for row in db.execute("PRAGMA table_info(readings)")]
    assert columns == [
        "path",
        "size",
        "mtime",
        "bpm",
        "camelot",
        "key_name",
        "downbeat",
        "warning",
        "valence",
        "energy",
    ]
    stat = track.stat()
    cached = jobs.get_reading(str(track.resolve()), stat.st_size, stat.st_mtime_ns)
    assert cached["camelot"] == "8A"
    assert cached["key_name"] == "A minor"
    second = client.post("/api/playlist/scans", json={"path": str(track.parent)}).json()
    assert wait_scan(client, second["id"])["status"] == "completed"
    assert calls == [str(track.resolve())]
    bumped = stat.st_mtime_ns + 1_000_000
    os.utime(track, ns=(stat.st_atime_ns, bumped))
    third = client.post("/api/playlist/scans", json={"path": str(track.parent)}).json()
    assert wait_scan(client, third["id"])["status"] == "completed"
    assert calls == [str(track.resolve()), str(track.resolve())]
    assert track.is_file()


def test_rows_stay_empty_until_completed_and_one_child_runs(client, monkeypatch, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "a.wav").write_bytes(wav())
    (folder / "b.wav").write_bytes(wav())
    first = Holding()
    second = Holding()
    scan_id = None

    def fake(command, **kwargs):
        kwargs["stdout"].write(json.dumps({**READING, "warning": "The outro drifts"}))
        return first if Path(command[-1]).name == "a.wav" else second

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    try:
        response = client.post("/api/playlist/scans", json={"path": str(folder)})
        scan_id = response.json()["id"]
        assert first.entered.wait(5)
        assert not second.entered.is_set()
        running = client.get(f"/api/playlist/scans/{scan_id}").json()
        assert running["status"] == "running"
        assert running["current"] == "a.wav"
        assert running["done"] == 0
        assert running["tracks"] == []
        assert running["unread"] == []
        first.release.set()
        assert second.entered.wait(5)
        mid = client.get(f"/api/playlist/scans/{scan_id}").json()
        assert mid["status"] == "running"
        assert mid["done"] == 1
        assert mid["current"] == "b.wav"
        assert mid["tracks"] == []
        assert mid["unread"] == []
        second.release.set()
        done = wait_scan(client, scan_id)
    finally:
        first.release.set()
        second.release.set()
        if scan_id:
            settle(client, scan_id)
    assert done["status"] == "completed"
    assert done["current"] is None
    assert [row["filename"] for row in done["tracks"]] == ["a.wav", "b.wav"]
    assert done["tracks"][0]["warning"] == "The outro drifts"
    assert done["unread"] == []


def test_missing_reading_is_unread_when_the_scan_completes(client, monkeypatch, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "blank.wav").write_bytes(wav())
    (folder / "good.wav").write_bytes(wav())

    def fake(command, **kwargs):
        name = Path(command[-1]).name
        if name == "blank.wav":
            payload = {**READING, "bpm": None, "camelot": None, "warning": "No steady tempo"}
        else:
            payload = {**READING, "warning": ""}
        kwargs["stdout"].write(json.dumps(payload))
        return Finished(0)

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    started = client.post("/api/playlist/scans", json={"path": str(folder)}).json()
    done = wait_scan(client, started["id"])
    assert done["status"] == "completed"
    assert [row["filename"] for row in done["tracks"]] == ["good.wav"]
    assert done["unread"] == [
        {
            "path": str((folder / "blank.wav").resolve()),
            "filename": "blank.wav",
            "reason": "No steady tempo",
        }
    ]


def test_cancel_kills_the_analysis_child(client, monkeypatch, tmp_path):
    track = write_audio(tmp_path / "music")
    child = Stubborn()
    commands = []

    def fake(command, **kwargs):
        commands.append(command)
        return child

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    scan_id = None
    try:
        started = client.post("/api/playlist/scans", json={"path": str(track.parent)}).json()
        scan_id = started["id"]
        assert child.entered.wait(5)
        running = client.get(f"/api/playlist/scans/{scan_id}").json()
        assert running["tracks"] == []
        assert running["unread"] == []
        response = client.delete(f"/api/playlist/scans/{scan_id}")
        assert response.status_code == 200
        assert child.terminated
        assert child.killed
        done = wait_scan(client, scan_id)
    finally:
        if child.returncode is None:
            child.kill()
        if scan_id:
            settle(client, scan_id)
    assert done["status"] == "cancelled"
    assert done["current"] is None
    assert done["tracks"] == []
    assert done["unread"] == []
    assert track.is_file()
    assert commands[0][1:-1] == ["-m", "stemlab.analysis"]
    assert Path(commands[0][-1]) == track.resolve()


def test_failed_child_hides_rows(client, monkeypatch, tmp_path):
    write_audio(tmp_path / "music")

    def fake(command, **kwargs):
        kwargs["stderr"].write("model failed\n")
        return Finished(1)

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    started = client.post("/api/playlist/scans", json={"path": str(tmp_path / "music")}).json()
    done = wait_scan(client, started["id"])
    assert done["status"] == "failed"
    assert done["current"] is None
    assert done["tracks"] == []
    assert done["unread"] == []


def test_order_drops_held_and_unread_tracks(client, monkeypatch):
    seen = {}

    def fake(tracks, pinned=None):
        seen["tracks"] = tracks
        seen["pinned"] = pinned
        return [
            {
                "path": tracks[0]["path"],
                "filename": tracks[0]["filename"],
                "bpm": tracks[0]["bpm"],
                "camelot": tracks[0]["camelot"],
                "key_name": tracks[0]["key_name"],
                "break": False,
                "band": None,
            }
        ]

    install_order_tracks(monkeypatch, fake)
    response = client.post(
        "/api/playlist/order",
        json={
            "pinned": "/music/opener.wav",
            "held": ["/music/held.wav"],
            "tracks": [
                {
                    "path": "/music/opener.wav",
                    "filename": "opener.wav",
                    "bpm": 100.0,
                    "camelot": "8A",
                    "key_name": "A minor",
                    "warning": "",
                },
                {
                    "path": "/music/held.wav",
                    "filename": "held.wav",
                    "bpm": 120.0,
                    "camelot": "9A",
                    "key_name": "E minor",
                    "warning": "",
                },
                {
                    "path": "/music/blank.wav",
                    "filename": "blank.wav",
                    "bpm": None,
                    "camelot": None,
                    "key_name": None,
                    "warning": "No steady tempo",
                },
                {
                    "path": "/music/nokey.wav",
                    "filename": "nokey.wav",
                    "bpm": 118.0,
                    "camelot": "",
                    "key_name": None,
                    "warning": "",
                },
            ],
        },
    )
    assert response.status_code == 200
    assert [track["path"] for track in seen["tracks"]] == ["/music/opener.wav"]
    assert seen["pinned"] == "/music/opener.wav"
    assert response.json()["order"][0]["break"] is False


def test_playback_allowlist_and_range(client, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    track = folder / "track.wav"
    track.write_bytes(wav())
    alias = folder / "alias.wav"
    alias.symlink_to(track)
    nested = folder / "cd"
    nested.mkdir()
    inner = nested / "inner.wav"
    inner.write_bytes(wav())
    outside = tmp_path / "secret.wav"
    outside.write_bytes(wav())
    escape = folder / "escape.wav"
    escape.symlink_to(outside)
    (folder / "notes.txt").write_bytes(b"notes")
    (folder / "song.flac").write_bytes(b"flac")
    (folder / "dir.wav").mkdir()
    tune = folder / "tune.mp3"
    tune.write_bytes(b"not-really-mp3-but-enough-bytes-for-a-read")

    ranged = client.get(
        "/api/playlist/audio",
        params={"path": str(track)},
        headers={"Range": "bytes=0-31"},
    )
    assert ranged.status_code == 206
    assert ranged.headers["accept-ranges"] == "bytes"
    assert ranged.headers["content-type"].startswith("audio/wav")
    assert len(ranged.content) == 32
    alias_ranged = client.get(
        "/api/playlist/audio",
        params={"path": str(alias)},
        headers={"Range": "bytes=0-31"},
    )
    assert alias_ranged.status_code == 206
    assert len(alias_ranged.content) == 32
    inner_ranged = client.get(
        "/api/playlist/audio",
        params={"path": str(inner)},
        headers={"Range": "bytes=0-7"},
    )
    assert inner_ranged.status_code == 206
    assert len(inner_ranged.content) == 8
    direct = client.get("/api/playlist/audio", params={"path": str(outside)})
    assert direct.status_code == 200
    assert direct.headers["content-type"].startswith("audio/wav")
    mpeg = client.get("/api/playlist/audio", params={"path": str(tune)})
    assert mpeg.status_code == 200
    assert mpeg.headers["content-type"].startswith("audio/mpeg")
    for blocked in (escape, folder / "notes.txt", folder / "song.flac", folder / "dir.wav"):
        assert client.get("/api/playlist/audio", params={"path": str(blocked)}).status_code == 404
    missing = folder / "missing.wav"
    assert client.get("/api/playlist/audio", params={"path": str(missing)}).status_code == 404
    assert client.get("/api/playlist/audio", params={"path": "track.wav"}).status_code == 404


def test_the_analysis_child_uses_the_server_python_without_a_checkout_environment(
    monkeypatch, tmp_path
):
    from stemlab import routes

    monkeypatch.setattr(routes, "venv_python", lambda _venv: tmp_path / "missing" / "python")
    assert routes.analysis_interpreter() == Path(sys.executable)
    present = tmp_path / "python"
    present.write_text("")
    monkeypatch.setattr(routes, "venv_python", lambda _venv: present)
    assert routes.analysis_interpreter() == present
