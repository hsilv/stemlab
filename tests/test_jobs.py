import fcntl
import io
import time
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from stemlab import jobs
from stemlab.config import settings
from stemlab.main import app
from stemlab.worker import range_options, separate_job


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


def upload(client, **kwargs):
    return client.post("/api/jobs?filename=track.wav", content=wav(**kwargs))


def test_upload_persist_list_original_and_cancel(client):
    response = upload(client)
    assert response.status_code == 202
    row = response.json()
    assert row["status"] == "queued"
    assert "task_id" not in row
    assert client.get("/api/jobs").json()[0]["id"] == row["id"]
    path = f"/api/jobs/{row['id']}"
    audio = client.get(path + "/audio/original", headers={"Range": "bytes=0-31"})
    assert audio.status_code == 206
    assert len(audio.content) == 32
    assert client.get(path + "/audio/vocals").status_code == 409
    assert client.get(path + "/download").status_code == 409
    assert client.delete(path).status_code == 409
    assert client.post(path + "/cancel").json()["status"] == "cancelled"
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert not (settings.data_dir / row["id"]).exists()


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
def test_reject_invalid_audio(client, options):
    assert upload(client, **options).status_code == 422
    assert client.get("/api/jobs").json() == []
    assert not any(path.is_dir() for path in settings.data_dir.iterdir())


def test_reject_corrupt_and_oversized_uploads(client, monkeypatch):
    assert client.post("/api/jobs?filename=bad.wav", content=b"not audio").status_code == 422
    assert client.post("/api/jobs?filename=bad.mp3", content=b"not audio").status_code == 422
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    assert upload(client).status_code == 413


def test_limits_duration(client, monkeypatch):
    monkeypatch.setattr(settings, "max_duration_seconds", 1)
    assert upload(client).status_code == 422


def test_sanitize_filename_and_reject_path_traversal(client):
    row = client.post("/api/jobs?filename=../../song.wav", content=wav()).json()
    assert row["filename"] == "song.wav"
    assert client.get(f"/api/jobs/{row['id']}/audio/worker.log").status_code == 404
    assert client.get("/api/jobs/not-a-uuid").status_code == 422
    assert client.get(f"/api/jobs/{uuid4()}").status_code == 404


def test_cross_origin_upload_rejected(client):
    response = client.post(
        "/api/jobs?filename=song.wav", content=wav(), headers={"Origin": "https://other.test"}
    )
    assert response.status_code == 403


def test_queue_failure_visible_and_retry_gets_new_task_id(client, monkeypatch):
    monkeypatch.setattr(settings, "queue_mode", "celery")
    with patch("stemlab.routes.separate_job.apply_async", side_effect=ConnectionError):
        row = upload(client).json()
    assert row["status"] == "failed"
    old_task_id = jobs.get(row["id"])["task_id"]
    with patch("stemlab.routes.separate_job.apply_async") as dispatch:
        retry = client.post(f"/api/jobs/{row['id']}/retry")
    assert retry.status_code == 202
    assert retry.json()["status"] == "queued"
    assert jobs.get(row["id"])["task_id"] != old_task_id
    dispatch.assert_called_once()
    assert not jobs.claim(row["id"], old_task_id)
    assert client.post(f"/api/jobs/{row['id']}/retry").status_code == 409


def test_claim_once_and_cancel_running(client):
    row = upload(client).json()
    task_id = jobs.get(row["id"])["task_id"]
    assert jobs.claim(row["id"], task_id)
    assert not jobs.claim(row["id"], task_id)
    assert client.post(f"/api/jobs/{row['id']}/cancel").json()["status"] == "cancelling"
    assert client.delete(f"/api/jobs/{row['id']}").status_code == 409


def test_recover_interrupted_job(client):
    row = upload(client).json()
    with jobs.database() as db:
        db.execute("UPDATE jobs SET status='running', updated=?", (time.time() - 180,))
    response = client.get(f"/api/jobs/{row['id']}")
    assert response.json()["status"] == "failed"
    assert "retry" in response.json()["error"]


def test_worker_failure_is_persisted_and_partial_outputs_removed(client):
    row = upload(client).json()
    task_id = jobs.get(row["id"])["task_id"]
    with patch("stemlab.worker.subprocess.Popen", side_effect=OSError("Cannot start inference")):
        separate_job.apply(args=[row["id"]], task_id=task_id)
    assert jobs.get(row["id"])["status"] == "failed"
    assert (settings.data_dir / row["id"] / "source.wav").exists()
    assert not (settings.data_dir / row["id"] / "stems").exists()


def test_cancelled_job_never_starts_inference(client):
    row = upload(client).json()
    client.post(f"/api/jobs/{row['id']}/cancel")
    with patch("stemlab.worker.subprocess.Popen") as process:
        separate_job.apply(args=[row["id"]], task_id=jobs.get(row["id"])["task_id"])
    process.assert_not_called()


def test_completed_downloads(client):
    row = upload(client).json()
    folder = settings.data_dir / row["id"]
    (folder / "stems").mkdir()
    (folder / "stems" / "vocals.wav").write_bytes(wav())
    (folder / "stems.zip").write_bytes(b"test-archive")
    jobs.update(row["id"], status="completed", stage="Ready")
    response = client.get(f"/api/jobs/{row['id']}/audio/vocals?download=true")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert client.get(f"/api/jobs/{row['id']}/download").content == b"test-archive"


def test_running_cancellation_stops_subprocess_before_terminal_state(client):
    row = upload(client).json()
    task_id = jobs.get(row["id"])["task_id"]
    with patch("stemlab.worker.subprocess.Popen") as start:
        process = start.return_value
        process.poll.return_value = None
        with patch(
            "stemlab.worker.time.sleep",
            side_effect=lambda _: jobs.update(
                row["id"], status="cancelling", stage="Stopping worker"
            ),
        ):
            separate_job.apply(args=[row["id"]], task_id=task_id)
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
    assert jobs.get(row["id"])["status"] == "cancelled"


def test_timeout_stops_subprocess_and_can_retry(client, monkeypatch):
    row = upload(client).json()
    monkeypatch.setattr(settings, "job_timeout_seconds", -1)
    with patch("stemlab.worker.subprocess.Popen") as start:
        start.return_value.poll.return_value = None
        separate_job.apply(args=[row["id"]], task_id=jobs.get(row["id"])["task_id"])
        start.return_value.terminate.assert_called_once()
    result = jobs.get(row["id"])
    assert result["status"] == "failed"
    assert "time limit" in result["error"]


def test_stale_recovery_does_not_release_live_process_lock(client):
    row = upload(client).json()
    with jobs.database() as db:
        db.execute("UPDATE jobs SET status='running', updated=?", (time.time() - 180,))
    with (settings.data_dir / row["id"] / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        jobs.recover_stale()
        assert jobs.get(row["id"])["status"] == "running"
    jobs.recover_stale()
    assert jobs.get(row["id"])["status"] == "failed"


def test_custom_selection_persists_through_retry_and_restricts_downloads(client):
    response = client.post(
        "/api/jobs?filename=custom.wav&mode=custom&keep=vocals,bass", content=wav()
    )
    assert response.status_code == 202
    row = response.json()
    assert row["mode"] == "custom"
    assert row["keep"] == ["vocals", "bass"]
    assert row["outputs"] == [{"id": "mix", "label": "Custom mix", "sources": ["vocals", "bass"]}]
    path = f"/api/jobs/{row['id']}"
    client.post(path + "/cancel")
    retry = client.post(path + "/retry").json()
    assert retry["outputs"] == row["outputs"] and retry["keep"] == row["keep"]
    folder = settings.data_dir / row["id"] / "stems"
    folder.mkdir()
    (folder / "mix.wav").write_bytes(wav())
    jobs.update(row["id"], status="completed", stage="Ready")
    assert client.get(path + "/audio/mix").status_code == 200
    assert client.get(path + "/audio/vocals").status_code == 404
    assert client.get(path).json()["mode"] == "custom"


@pytest.mark.parametrize(
    "query",
    [
        "mode=unknown",
        "mode=custom",
        "mode=custom&keep=",
        "mode=custom&keep=../source",
        "mode=custom&keep=bass,bass",
        "mode=all&keep=vocals",
    ],
)
def test_invalid_selection_rejected_before_upload(client, query):
    assert client.post(f"/api/jobs?filename=track.wav&{query}", content=wav()).status_code == 422
    assert client.get("/api/jobs").json() == []


def test_mp3_upload_original_playback_and_retry(client):
    content = wav(format="MP3", rate=44100)
    row = client.post(
        "/api/jobs?filename=music.MP3&mode=instrumental",
        content=content,
        headers={"Content-Type": "audio/mpeg"},
    ).json()
    assert row["status"] == "queued"
    assert row["outputs"][0]["sources"] == ["drums", "bass", "other"]
    assert jobs.source_path(row).name == "source.mp3"
    original = client.get(f"/api/jobs/{row['id']}/audio/original?download=true")
    assert original.content == content
    assert original.headers["content-type"] == "audio/mpeg"
    assert "music-original.mp3" in original.headers["content-disposition"]
    partial = client.get(f"/api/jobs/{row['id']}/audio/original", headers={"Range": "bytes=0-31"})
    assert partial.status_code == 206 and partial.content == content[:32]
    client.post(f"/api/jobs/{row['id']}/cancel")
    retry = client.post(f"/api/jobs/{row['id']}/retry").json()
    assert retry["mode"] == "instrumental"
    with patch("stemlab.worker.subprocess.Popen", side_effect=OSError("test")) as process:
        separate_job.apply(args=[row["id"]], task_id=jobs.get(row["id"])["task_id"])
    assert str(jobs.source_path(row)) in process.call_args.args[0]
    assert "--mode" in process.call_args.args[0] and "instrumental" in process.call_args.args[0]


def test_reject_disguised_mp3_and_mp3_duration_limit(client, monkeypatch):
    assert client.post("/api/jobs?filename=bad.mp3", content=wav()).status_code == 422
    assert client.post("/api/jobs?filename=bad.wav", content=wav(format="MP3")).status_code == 422
    monkeypatch.setattr(settings, "max_duration_seconds", 1)
    assert (
        client.post("/api/jobs?filename=long.mp3", content=wav(format="MP3", seconds=2)).status_code
        == 422
    )


def test_quality_persists_through_retry_and_defaults_to_settings(client):
    default = upload(client).json()
    assert (default["model"], default["vocals"], default["instruments_from"]) == (
        settings.model,
        settings.vocals,
        settings.instruments_from,
    )
    assert (default["shifts"], default["overlap"]) == (settings.shifts, settings.overlap)
    query = "model=ft_mmi&vocals=bs&instruments_from=mix&shifts=4&overlap=0.75"
    row = client.post(f"/api/jobs?filename=track.wav&{query}", content=wav()).json()
    chosen = ("ft_mmi", "bs", "mix", 4, 0.75)
    assert (
        tuple(row[k] for k in ("model", "vocals", "instruments_from", "shifts", "overlap"))
        == chosen
    )
    jobs.update(row["id"], status="failed")
    client.post(f"/api/jobs/{row['id']}/retry")
    saved = jobs.get(row["id"])
    assert (
        tuple(saved[k] for k in ("model", "vocals", "instruments_from", "shifts", "overlap"))
        == chosen
    )


@pytest.mark.parametrize(
    "query",
    [
        "model=other",
        "model=roformer_htdemucs_ft",
        "vocals=other",
        "instruments_from=other",
        "shifts=-1",
        "shifts=6",
        "overlap=0",
        "overlap=1",
    ],
)
def test_invalid_quality_rejected_before_upload(client, query):
    response = client.post(f"/api/jobs?filename=track.wav&{query}", content=wav())
    assert response.status_code == 422
    assert client.get("/api/jobs").json() == []


def test_section_persists_through_retry_and_whole_track_has_none(client):
    assert upload(client).json()["range_start"] is None
    row = client.post("/api/jobs?filename=track.wav&start=0.1&end=1.1", content=wav()).json()
    assert (row["range_start"], row["range_end"]) == (0.1, 1.1)
    jobs.update(row["id"], status="failed")
    client.post(f"/api/jobs/{row['id']}/retry")
    saved = jobs.get(row["id"])
    assert (saved["range_start"], saved["range_end"]) == (0.1, 1.1)
    open_ended = client.post("/api/jobs?filename=track.wav&start=0.1", content=wav()).json()
    assert open_ended["range_end"] == pytest.approx(1.1)


@pytest.mark.parametrize(
    "query", ["start=0.5&end=1.2", "start=0.9&end=0.5", "start=0.5&end=0.6", "start=-1", "end=0"]
)
def test_invalid_section_rejected_and_cleaned_up(client, query):
    response = client.post(f"/api/jobs?filename=track.wav&{query}", content=wav(seconds=1.1))
    assert response.status_code == 422
    assert client.get("/api/jobs").json() == []
    assert not any(path.is_dir() for path in settings.data_dir.iterdir())


@pytest.mark.parametrize(
    "query,status",
    [
        ("mode=instrumental&instruments_from=inverse", 202),
        ("mode=custom&keep=drums,bass,other&instruments_from=inverse", 202),
        ("mode=all&instruments_from=inverse", 422),
        ("mode=vocals&instruments_from=inverse", 422),
        ("mode=custom&keep=vocals,bass&instruments_from=inverse", 422),
    ],
)
def test_mix_minus_vocals_only_for_no_vocals_outputs(client, query, status):
    response = client.post(f"/api/jobs?filename=track.wav&{query}", content=wav())
    assert response.status_code == status
    if status == 202:
        assert response.json()["instruments_from"] == "inverse"
    else:
        assert client.get("/api/jobs").json() == []


def test_range_options_cover_one_section_several_ranges_or_the_whole_track():
    assert range_options({"ranges": None, "range_start": None, "range_end": None}) == []
    assert range_options({"ranges": None, "range_start": 0.1, "range_end": 1.1}) == [
        "--start",
        "0.1",
        "--end",
        "1.1",
    ]
    assert range_options({"ranges": [[0.0, 1.0], [2.0, 3.5]], "range_start": None}) == [
        "--ranges",
        "0.0-1.0,2.0-3.5",
    ]


def test_several_ranges_persist_through_retry(client):
    row = client.post(
        "/api/jobs?filename=track.wav&ranges=0-1,2-3.5", content=wav(seconds=10)
    ).json()
    assert row["range_start"] is None
    assert row["ranges"] == [[0.0, 1.0], [2.0, 3.5]]
    jobs.update(row["id"], status="failed")
    client.post(f"/api/jobs/{row['id']}/retry")
    assert jobs.get(row["id"])["ranges"] == [[0.0, 1.0], [2.0, 3.5]]
    single = client.post("/api/jobs?filename=track.wav&ranges=0.1-1.1", content=wav()).json()
    assert (single["range_start"], single["range_end"]) == (0.1, 1.1)
    assert single["ranges"] == [[0.1, 1.1]]


@pytest.mark.parametrize(
    "query",
    [
        "ranges=0-0.4",
        "ranges=0-2",
        "ranges=0-1,0.5-2",
        "ranges=nope",
        "start=0.1&end=1.1&ranges=0-1,2-3",
    ],
)
def test_invalid_ranges_rejected_and_cleaned_up(client, query):
    response = client.post(f"/api/jobs?filename=track.wav&{query}", content=wav(seconds=1.1))
    assert response.status_code == 422
    assert client.get("/api/jobs").json() == []
    assert not any(path.is_dir() for path in settings.data_dir.iterdir())
