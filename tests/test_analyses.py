import io
import json
import threading
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "queue_mode", "local")
    with TestClient(app) as client:
        yield client


def wav(*, channels=2, rate=16000, seconds=1.1, invalid=False, format="WAV"):
    data = np.zeros((int(rate * seconds), channels), dtype="float32")
    if invalid:
        data[100] = np.nan
    buffer = io.BytesIO()
    sf.write(buffer, data, rate, format=format, subtype="FLOAT" if format == "WAV" else None)
    return buffer.getvalue()


READING = {
    "bpm": 128.04,
    "camelot": "8A",
    "key_name": "A minor",
    "downbeat": 0.5,
    "warning": "",
}


def post_analysis(client, content=None, filename="track.wav"):
    body = wav() if content is None else content
    return client.post(f"/api/analyses?filename={filename}", content=body)


def wait_analysis(client, analysis_id):
    deadline = time.monotonic() + 5
    body = None
    while time.monotonic() < deadline:
        body = client.get(f"/api/analyses/{analysis_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(body)


def test_analysis_returns_running_then_the_reading(client, monkeypatch):
    source = {}

    def fake(command, **kwargs):
        source["path"] = command[-1]
        assert command[0] == str(analysis_interpreter())
        assert command[1:-1] == ["-m", "stemlab.analysis"]
        kwargs["stderr"].write("STAGE:Reading tempo and key\n")
        kwargs["stdout"].write(json.dumps(READING))
        return Finished(0)

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    response = post_analysis(client)
    assert response.status_code == 202
    started = response.json()
    assert set(started) == {"id", "status", "stage", "error"}
    assert started["status"] == "running"
    assert started["stage"] == "Checking the file"
    assert started["error"] is None
    done = wait_analysis(client, started["id"])
    assert done["status"] == "completed"
    assert done["stage"] == "Reading tempo and key"
    assert done["error"] is None
    assert done["bpm"] == pytest.approx(128.04)
    assert (done["camelot"], done["key_name"]) == ("8A", "A minor")
    assert done["downbeat"] == pytest.approx(0.5)
    assert done["warning"] == ""
    path = Path(source["path"])
    assert path.is_relative_to(settings.data_dir / "analyses")
    assert path.name == "source.wav"
    assert not path.exists()


def test_poll_reads_the_stage_the_child_writes(client, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def fake(command, **kwargs):
        kwargs["stderr"].write("STAGE:Waiting for the separator\n")
        kwargs["stderr"].flush()
        started.set()
        assert release.wait(5)
        kwargs["stderr"].write("Isolating drums and bass\n")
        kwargs["stdout"].write(json.dumps({**READING, "warning": "The outro drifts"}))
        return Finished(0)

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    response = post_analysis(client)
    try:
        assert response.json()["stage"] == "Checking the file"
        assert started.wait(5)
        running = client.get(f"/api/analyses/{response.json()['id']}").json()
        assert running["status"] == "running"
        assert running["stage"] == "Waiting for the separator"
        assert "bpm" not in running
    finally:
        release.set()
    done = wait_analysis(client, response.json()["id"])
    assert done["stage"] == "Isolating drums and bass"
    assert done["warning"] == "The outro drifts"


def test_analysis_failure_sets_status_and_error(client, monkeypatch):
    def fake(command, **kwargs):
        kwargs["stderr"].write("Isolating the instrumental\nmodel failed\n")
        return Finished(1)

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    response = post_analysis(client)
    body = wait_analysis(client, response.json()["id"])
    assert body["status"] == "failed"
    assert body["stage"] == "Isolating the instrumental"
    assert body["error"] == "model failed"
    assert "bpm" not in body


def test_unreadable_analysis_result_fails(client, monkeypatch):
    def fake(command, **kwargs):
        kwargs["stdout"].write("not json")
        return Finished(0)

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    response = post_analysis(client)
    body = wait_analysis(client, response.json()["id"])
    assert body["status"] == "failed"
    assert "unreadable" in body["error"]


def test_analysis_child_that_does_not_start_fails(client, monkeypatch):
    def fake(command, **kwargs):
        raise OSError("Cannot start analysis")

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    response = post_analysis(client)
    body = wait_analysis(client, response.json()["id"])
    assert body["status"] == "failed"
    assert "Cannot start analysis" in body["error"]


@pytest.mark.parametrize(
    "options",
    [
        {"channels": 3},
        {"rate": 4000},
        {"seconds": 0.1},
        {"invalid": True},
        {"format": "FLAC"},
    ],
)
def test_analysis_rejects_invalid_audio_like_job_upload(client, monkeypatch, options):
    def fake(*args, **kwargs):
        raise AssertionError("invalid audio must not start analysis")

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", fake)
    assert post_analysis(client, content=wav(**options)).status_code == 422
    analyses = settings.data_dir / "analyses"
    assert not analyses.exists() or not any(analyses.iterdir())


def test_analysis_rejects_corrupt_and_oversized_bodies(client, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("invalid audio must not start analysis")

    monkeypatch.setattr("stemlab.routes.subprocess.Popen", refuse)
    assert post_analysis(client, content=b"not audio").status_code == 422
    assert post_analysis(client, content=b"not audio", filename="bad.mp3").status_code == 422
    assert post_analysis(client, filename="notes.txt").status_code == 422
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    assert post_analysis(client).status_code == 413
    analyses = settings.data_dir / "analyses"
    assert not analyses.exists() or not any(analyses.iterdir())


def test_unknown_analysis_is_not_found(client):
    assert client.get("/api/analyses/not-a-uuid").status_code == 422
    assert client.get(f"/api/analyses/{uuid4()}").status_code == 404
