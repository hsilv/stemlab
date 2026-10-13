import io
import json
import sqlite3
import time
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from stemlab import exports, filelock, jobs, tags
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


def test_new_stems_are_flac_and_old_wav_stems_still_play(client):
    row = upload(client).json()
    folder = settings.data_dir / row["id"] / "stems"
    folder.mkdir()
    (folder / "vocals.flac").write_bytes(b"flac")
    (folder / "drums.wav").write_bytes(wav())
    jobs.update(row["id"], status="completed", stage="Ready")
    path = f"/api/jobs/{row['id']}"
    assert client.get(path + "/audio/vocals").headers["content-type"] == "audio/flac"
    assert client.get(path + "/audio/drums").headers["content-type"] == "audio/wav"


def test_another_edit_reuses_the_upload_without_a_body(client):
    first = upload(client).json()
    params = "from_job=" + first["id"] + "&mode=vocals&start=0.1&end=1.1&bpm=120"
    second = client.post(f"/api/jobs?{params}")
    assert second.status_code == 202
    second = second.json()
    assert second["id"] != first["id"]
    assert (second["filename"], second["mode"], second["bpm"]) == ("track.wav", "vocals", 120)
    # Every edit, including an edit of an edit, belongs to the song's first job.
    third = client.post(f"/api/jobs?from_job={second['id']}").json()
    assert first["song_id"] == second["song_id"] == third["song_id"] == first["id"]
    source = settings.data_dir / first["id"] / "source.wav"
    copy = settings.data_dir / second["id"] / "source.wav"
    assert copy.read_bytes() == source.read_bytes()
    # Each edit owns its folder: removing the first song's job leaves the second playable.
    client.post(f"/api/jobs/{first['id']}/cancel")
    assert client.delete(f"/api/jobs/{first['id']}").status_code == 204
    assert client.get(f"/api/jobs/{second['id']}/audio/original").status_code == 200


def test_another_edit_needs_an_existing_upload(client):
    assert client.post(f"/api/jobs?from_job={uuid4()}").status_code == 404
    row = upload(client).json()
    (settings.data_dir / row["id"] / "source.wav").unlink()
    response = client.post(f"/api/jobs?from_job={row['id']}")
    assert response.status_code == 404
    assert len(list(settings.data_dir.iterdir())) == 2  # database file and the first job
    assert client.post("/api/jobs").status_code == 422


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
        assert filelock.try_lock(lock.fileno())
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


def test_flac_upload_is_stored_and_played_back_as_flac(client):
    content = wav(format="FLAC", rate=44100)
    row = client.post("/api/jobs?filename=Music.FLAC&mode=vocals", content=content).json()
    assert row["status"] == "queued"
    assert jobs.source_path(row).name == "source.flac"
    original = client.get(f"/api/jobs/{row['id']}/audio/original")
    assert original.content == content
    assert original.headers["content-type"] == "audio/flac"
    assert "flac" in client.get("/api/config").json()["input_formats"]


def test_reject_disguised_flac_and_unknown_extensions(client):
    assert client.post("/api/jobs?filename=bad.flac", content=wav()).status_code == 422
    assert client.post("/api/jobs?filename=bad.wav", content=wav(format="FLAC")).status_code == 422
    assert client.post("/api/jobs?filename=song.ogg", content=wav()).status_code == 422


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
    "choice", ["inverse", "direct_resurrection", "direct_inst_v2", "direct_bleedless"]
)
@pytest.mark.parametrize(
    "query,status",
    [
        ("mode=instrumental", 202),
        ("mode=custom&keep=drums,bass,other", 202),
        ("mode=all", 422),
        ("mode=vocals", 422),
        ("mode=custom&keep=vocals,bass", 422),
    ],
)
def test_whole_instrumental_choices_only_for_no_vocals_outputs(client, query, status, choice):
    response = client.post(
        f"/api/jobs?filename=track.wav&{query}&instruments_from={choice}", content=wav()
    )
    assert response.status_code == status
    if status == 202:
        assert response.json()["instruments_from"] == choice
    else:
        assert client.get("/api/jobs").json() == []


def test_unknown_instrumental_choice_is_refused(client):
    response = client.post(
        "/api/jobs?filename=track.wav&mode=instrumental&instruments_from=direct_nope", content=wav()
    )
    assert response.status_code == 422


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


def test_old_job_migrates_with_null_analysis_fields(client):
    with sqlite3.connect(settings.data_dir / "jobs.sqlite3") as db:
        db.execute("""CREATE TABLE jobs (
            id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL,
            stage TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
            duration REAL NOT NULL, sample_rate INTEGER NOT NULL, channels INTEGER NOT NULL,
            error TEXT, task_id TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'all', keep TEXT,
            model TEXT NOT NULL DEFAULT 'htdemucs',
            shifts INTEGER NOT NULL DEFAULT 0,
            overlap REAL NOT NULL DEFAULT 0.25,
            vocals TEXT NOT NULL DEFAULT 'demucs',
            instruments_from TEXT NOT NULL DEFAULT 'mix',
            range_start REAL, range_end REAL, ranges TEXT)""")
        db.execute(
            "INSERT INTO jobs (id, filename, status, stage, created, updated, duration, "
            "sample_rate, channels, task_id) "
            "VALUES ('old', 'song.wav', 'completed', 'Ready', 1, 1, 3, 44100, 2, 'task')"
        )
    row = client.get("/api/jobs").json()[0]
    assert row["status"] == "completed"
    assert row["filename"] == "song.wav"
    for key in ("bpm", "camelot", "key_name", "downbeat", "analysis_warning"):
        assert row[key] is None
    again = jobs.get("old")
    assert again["bpm"] is None and again["analysis_warning"] is None


def test_create_stores_analysis_fields(client):
    omitted = upload(client).json()
    for key in ("bpm", "camelot", "key_name", "downbeat", "analysis_warning"):
        assert omitted[key] is None
    row = client.post(
        "/api/jobs",
        params={
            "filename": "track.wav",
            "bpm": 128.04,
            "camelot": "8A",
            "key_name": "A minor",
            "downbeat": 0.25,
            "analysis_warning": "The bridge drifts",
        },
        content=wav(),
    ).json()
    assert row["bpm"] == pytest.approx(128.04)
    assert (row["camelot"], row["key_name"]) == ("8A", "A minor")
    assert row["downbeat"] == pytest.approx(0.25)
    assert row["analysis_warning"] == "The bridge drifts"
    saved = client.get(f"/api/jobs/{row['id']}").json()
    assert saved["camelot"] == "8A"
    assert saved["analysis_warning"] == "The bridge drifts"
    jobs.update(row["id"], status="failed")
    client.post(f"/api/jobs/{row['id']}/retry")
    kept = jobs.get(row["id"])
    assert kept["bpm"] == pytest.approx(128.04)
    assert kept["camelot"] == "8A"
    assert kept["key_name"] == "A minor"
    assert kept["downbeat"] == pytest.approx(0.25)
    assert kept["analysis_warning"] == "The bridge drifts"
    blank = client.post(
        "/api/jobs", params={"filename": "track.wav", "analysis_warning": ""}, content=wav()
    ).json()
    assert blank["analysis_warning"] == ""
    assert client.post("/api/jobs?filename=track.wav&bpm=-1", content=wav()).status_code == 422


def test_separation_holds_the_inference_lock(client):
    row = upload(client).json()
    seen = {}

    def fake_popen(*args, **kwargs):
        path = settings.data_dir / "inference.lock"
        with path.open("a") as handle:
            seen["held"] = not filelock.try_lock(handle.fileno())
            if not seen["held"]:
                filelock.unlock(handle.fileno())

        class Finished:
            returncode = 1

            def poll(self):
                return self.returncode

            def terminate(self):
                return None

            def kill(self):
                return None

            def wait(self, timeout=None):
                return self.returncode

        return Finished()

    with patch("stemlab.worker.subprocess.Popen", side_effect=fake_popen):
        separate_job.apply(args=[row["id"]], task_id=jobs.get(row["id"])["task_id"])
    assert seen["held"] is True


def finished_job(client, **kwargs):
    row = upload(client, **kwargs).json()
    folder = settings.data_dir / row["id"] / "stems"
    folder.mkdir()
    return row, folder


@pytest.mark.parametrize(
    ("fmt", "media"), [("wav", "audio/wav"), ("flac", "audio/flac"), ("mp3", "audio/mpeg")]
)
def test_stem_downloads_convert_to_the_requested_format(client, fmt, media):
    if fmt == "mp3" and "mp3" not in exports.formats():
        pytest.skip("ffmpeg is not installed")
    row, folder = finished_job(client)
    signal = (np.sin(np.arange(44100) / 20)[:, None] * 0.5).repeat(2, axis=1).astype("float32")
    sf.write(folder / "vocals.flac", signal, 44100, format="FLAC", subtype="PCM_24")
    jobs.update(row["id"], status="completed", stage="Ready")
    response = client.get(f"/api/jobs/{row['id']}/audio/vocals?download=true&format={fmt}")
    assert response.status_code == 200
    assert response.headers["content-type"] == media
    assert f"track-vocals.{fmt}" in response.headers["content-disposition"]
    decoded, rate = sf.read(io.BytesIO(response.content), dtype="float32")
    assert rate == 44100 and decoded.shape[1] == 2
    if fmt == "mp3":
        assert len(response.content) * 8 / 1.0 / 1000 > 250  # one second at roughly 320 kbps
    else:
        np.testing.assert_allclose(decoded, signal, atol=1e-6)
    scratch = settings.data_dir / row["id"] / "exports"
    assert not scratch.exists() or not list(scratch.iterdir())


def test_old_float_wav_stem_converts_without_clipping(client):
    row, folder = finished_job(client)
    loud = np.full((4410, 2), 1.5, dtype="float32")
    sf.write(folder / "vocals.wav", loud, 44100, subtype="FLOAT")
    jobs.update(row["id"], status="completed", stage="Ready")
    response = client.get(f"/api/jobs/{row['id']}/audio/vocals?format=flac")
    decoded, _ = sf.read(io.BytesIO(response.content), dtype="float32")
    assert decoded.max() == pytest.approx(0.999, abs=1e-4) and decoded.min() > 0.9


def test_zip_download_converts_every_output(client):
    row = client.post("/api/jobs?filename=track.wav&mode=vocals", content=wav()).json()
    folder = settings.data_dir / row["id"]
    (folder / "stems").mkdir()
    sf.write(folder / "stems" / "vocals.flac", np.zeros((4410, 2), "float32"), 44100, format="FLAC")
    (folder / "stems.zip").write_bytes(b"stored-archive")
    jobs.update(row["id"], status="completed", stage="Ready")
    path = f"/api/jobs/{row['id']}/download"
    assert client.get(path + "?format=flac").content == b"stored-archive"
    archive = client.get(path + "?format=wav")
    assert zipfile.ZipFile(io.BytesIO(archive.content)).namelist() == ["vocals.wav"]
    assert not list((folder / "exports").iterdir())


def test_unavailable_or_unknown_export_formats_fail_cleanly(client, monkeypatch):
    row, folder = finished_job(client)
    sf.write(folder / "vocals.flac", np.zeros((4410, 2), "float32"), 44100, format="FLAC")
    jobs.update(row["id"], status="completed", stage="Ready")
    path = f"/api/jobs/{row['id']}/audio/vocals"
    assert client.get(path + "?format=ogg").status_code == 422
    monkeypatch.setattr("stemlab.exports.shutil.which", lambda _name: None)
    assert "mp3" not in client.get("/api/config").json()["export_formats"]
    assert client.get(path + "?format=mp3").status_code == 503
    assert not list((folder.parent / "exports").iterdir())


def song_job(client, **params):
    """A 60 second upload that already has its reading (120 BPM, first bar at 0.5 s)."""
    query = "&".join(
        f"{key}={value}" for key, value in {"bpm": 120, "downbeat": 0.5, **params}.items()
    )
    return client.post(
        f"/api/jobs?filename=song.wav&camelot=8A&key_name=A%20minor&{query}",
        content=wav(seconds=60),
    ).json()


EXTEND = '{"intro":{"bars":4},"outro":{"bars":8,"source":"last_bars"}}'


def test_an_extended_edit_belongs_to_the_song_and_keeps_its_parameters(client):
    first = song_job(client)
    second = client.post(f"/api/jobs?from_job={first['id']}&mode=extend&extend={EXTEND}")
    assert second.status_code == 202
    row = second.json()
    assert (row["mode"], row["song_id"], row["bpm"], row["downbeat"]) == (
        "extend",
        first["id"],
        120,
        0.5,
    )
    assert row["key_name"] == "A minor" and row["ranges"] is None
    assert row["extend"]["intro"]["bars"] == 4 and row["extend"]["outro"]["source"] == "last_bars"
    assert row["outputs"] == [
        {
            "id": "extended",
            "label": "Extended edit",
            "sources": ["vocals", "drums", "bass", "other"],
        }
    ]


@pytest.mark.parametrize(
    ("extend", "message"),
    [
        ('{"intro":{"bars":5}}', "bars"),
        ("{}", "intro, an outro or both"),
        ('{"intro":{"bars":4,"source":"fragment","fragment":[5,2]}}', "fragment"),
        ('{"intro":{"bars":32,"source":"first_bars"}}', None),
        ("not json", None),
    ],
)
def test_bad_extension_parameters_are_refused_with_a_reason(client, extend, message):
    song = song_job(client)
    response = client.post(f"/api/jobs?from_job={song['id']}&mode=extend&extend={extend}")
    if extend.startswith('{"intro":{"bars":32'):
        # 60 s at 120 BPM is plenty for four bars, which is all a loop needs.
        assert response.status_code == 202
        return
    assert response.status_code == 422
    if message:
        assert message in response.json()["detail"]


def test_an_extended_edit_needs_a_tempo_a_song_and_enough_bars(client):
    assert (
        client.post(
            f"/api/jobs?filename=x.wav&mode=extend&extend={EXTEND}", content=wav()
        ).status_code
        == 422
    )
    no_tempo = client.post("/api/jobs?filename=song.wav", content=wav(seconds=60)).json()
    response = client.post(f"/api/jobs?from_job={no_tempo['id']}&mode=extend&extend={EXTEND}")
    assert response.status_code == 422 and "steady tempo" in response.json()["detail"]
    short = client.post(
        "/api/jobs?filename=short.wav&bpm=120&downbeat=0", content=wav(seconds=5)
    ).json()
    response = client.post(f"/api/jobs?from_job={short['id']}&mode=extend&extend={EXTEND}")
    assert response.status_code == 422 and "too short" in response.json()["detail"]


def test_the_worker_slices_existing_full_stems_instead_of_separating(client):
    from stemlab.worker import extend_command

    song = song_job(client)
    edit = client.post(f"/api/jobs?from_job={song['id']}&mode=extend&extend={EXTEND}").json()
    row = jobs.get(edit["id"])
    assert "--parts" not in extend_command(row, "out")
    # A finished whole-song 'all' edit of the same song provides them.
    full = client.post(f"/api/jobs?from_job={song['id']}&mode=all").json()
    stems = settings.data_dir / full["id"] / "stems"
    stems.mkdir()
    for name in ("vocals", "drums", "bass", "other"):
        (stems / f"{name}.flac").write_bytes(b"x")
    jobs.update(full["id"], status="completed", stage="Ready")
    command = extend_command(row, "out")
    assert command[command.index("--parts") + 1] == str(stems)
    assert command[command.index("--bpm") + 1] == "120.0"
    # A section-only 'all' edit does not cover the song, so it is not used.
    section = client.post(f"/api/jobs?from_job={song['id']}&mode=all&start=1&end=5").json()
    assert section["id"] != full["id"]


class Done:
    def __init__(self, code=0):
        self.returncode, self.stderr = code, "boom"


def test_the_preview_returns_a_flac_and_cleans_up(client, monkeypatch):
    song = song_job(client)
    seen = {}

    def fake(command, **_kwargs):
        seen["command"] = command
        folder = Path(command[4])
        sf.write(folder / "preview.flac", np.zeros((4410, 2), "float32"), 44100, format="FLAC")
        return Done(0)

    monkeypatch.setattr("stemlab.routes.subprocess.run", fake)
    response = client.post(
        f"/api/jobs/{song['id']}/extend-preview", json={"extend": json.loads(EXTEND)}
    )
    assert response.status_code == 200 and response.headers["content-type"] == "audio/flac"
    assert (
        "--preview" in seen["command"]
        and seen["command"][seen["command"].index("--bpm") + 1] == "120.0"
    )
    scratch = settings.data_dir / song["id"] / "exports"
    assert not scratch.exists() or not list(scratch.iterdir())


@pytest.mark.parametrize(("code", "status"), [(75, 503), (1, 500)])
def test_a_busy_or_failed_preview_says_so(client, monkeypatch, code, status):
    song = song_job(client)
    monkeypatch.setattr("stemlab.routes.subprocess.run", lambda *_a, **_k: Done(code))
    response = client.post(
        f"/api/jobs/{song['id']}/extend-preview", json={"extend": json.loads(EXTEND)}
    )
    assert response.status_code == status
    bad = client.post(
        f"/api/jobs/{song['id']}/extend-preview", json={"extend": {"intro": {"bars": 3}}}
    )
    assert bad.status_code == 422


@pytest.mark.skipif("mp3" not in exports.formats(), reason="ffmpeg is not installed")
def test_the_mp3_of_an_extended_edit_carries_tempo_and_key(client):
    import subprocess

    song = song_job(client)
    edit = client.post(f"/api/jobs?from_job={song['id']}&mode=extend&extend={EXTEND}").json()
    folder = settings.data_dir / edit["id"] / "stems"
    folder.mkdir()
    sf.write(folder / "extended.flac", np.zeros((44100, 2), "float32"), 44100, format="FLAC")
    jobs.update(edit["id"], status="completed", stage="Ready")
    response = client.get(f"/api/jobs/{edit['id']}/audio/extended?format=mp3&download=true")
    assert response.status_code == 200
    target = settings.data_dir / "tagged.mp3"
    target.write_bytes(response.content)
    shown = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format_tags",
            "-of",
            "default=nw=1",
            str(target),
        ],
        capture_output=True,
        text=True,
    ).stdout
    assert "TBPM=120.00" in shown and "TKEY=Am" in shown


MANUAL = json.dumps(
    {
        "operations": [
            {
                "action": "insert",
                "at": 4,
                "bars": 4,
                "fragment": [10.5, 20.5],
                "stems": {"vocals": 0, "drums": 1, "bass": 1, "other": 1},
                "model": "htdemucs",
                "vocals": "melband",
            },
            {
                "action": "replace",
                "span": [10, 14],
                "fragment": [10.5, 20.5],
                "stems": {"vocals": 1, "drums": 1, "bass": 1, "other": 1},
            },
        ]
    }
)


def test_a_manual_edit_keeps_its_operations_and_their_choices(client):
    song = song_job(client)
    response = client.post(f"/api/jobs?from_job={song['id']}&mode=extend&extend={MANUAL}")
    assert response.status_code == 202
    first, second = response.json()["extend"]["operations"]
    assert (first["action"], first["at"], first["bars"], first["model"]) == (
        "insert",
        4,
        4,
        "htdemucs",
    )
    assert first["vocals"] == "melband" and first["shifts"] == settings.shifts
    assert second["span"] == [10, 14] and "bars" not in second
    assert second["model"] == settings.model


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"operations": []}, "at least one"),
        ({"operations": [{"action": "insert", "at": 4, "bars": 4}]}, "fragment"),
        (
            {
                "operations": [
                    {
                        "action": "insert",
                        "at": 0,
                        "bars": 4,
                        "fragment": [1, 9],
                        "stems": {"vocals": 1, "drums": 1, "bass": 1, "other": 1},
                    }
                ]
            },
            "insert between",
        ),
        (
            {
                "operations": [
                    {
                        "action": "replace",
                        "span": [3, 3],
                        "fragment": [1, 9],
                        "stems": {"vocals": 1, "drums": 1, "bass": 1, "other": 1},
                    }
                ]
            },
            "at least one bar",
        ),
        (
            {
                "operations": [
                    {
                        "action": "start",
                        "bars": 4,
                        "fragment": [1, 9],
                        "stems": {"vocals": 0, "drums": 0, "bass": 0, "other": 0},
                    }
                ]
            },
            "at least one sound",
        ),
    ],
)
def test_a_manual_edit_with_a_bad_operation_is_refused_with_the_reason(client, change, message):
    song = song_job(client)
    response = client.post(
        f"/api/jobs?from_job={song['id']}&mode=extend&extend={json.dumps(change)}"
    )
    assert response.status_code == 422 and message in response.json()["detail"]


def test_a_manual_preview_can_ask_for_one_operation(client, monkeypatch):
    song = song_job(client)
    seen = {}

    def fake(command, **_kwargs):
        seen["command"] = command
        sf.write(
            Path(command[4]) / "preview.flac", np.zeros((4410, 2), "float32"), 44100, format="FLAC"
        )
        return Done(0)

    monkeypatch.setattr("stemlab.routes.subprocess.run", fake)
    body = {"extend": json.loads(MANUAL), "only": 1}
    assert client.post(f"/api/jobs/{song['id']}/extend-preview", json=body).status_code == 200
    command = seen["command"]
    assert command[command.index("--only") + 1] == "1"
    assert (
        client.post(f"/api/jobs/{song['id']}/extend-preview", json={**body, "only": 5}).status_code
        == 422
    )


@pytest.fixture
def tagged_upload(client, tmp_path):
    """A job whose uploaded MP3 carries a real release's tags and cover, at 120 BPM in A minor."""
    import subprocess

    from test_tags import png, run

    (tmp_path / "cover.png").write_bytes(png())
    source = tmp_path / "source.mp3"
    run(
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-i", str(tmp_path / "cover.png"),
        "-map", "0:a", "-map", "1:v", "-c:a", "libmp3lame", "-c:v", "copy", "-id3v2_version", "3",
        "-metadata", "title=Gasolina", "-metadata", "artist=Daddy Yankee",
        "-metadata", "album=Barrio Fino", "-disposition:v", "attached_pic", str(source),
    )  # fmt: skip
    del subprocess
    response = client.post(
        "/api/jobs?filename=Gasolina.mp3&mode=instrumental&bpm=120&downbeat=0&key_name=A%20minor",
        content=source.read_bytes(),
    )
    assert response.status_code == 202
    return response.json()


@pytest.mark.skipif(not tags.available(), reason="ffmpeg is not installed")
def test_a_finished_job_gives_its_outputs_the_song_tags_and_a_version_name(client, tagged_upload):
    from stemlab.outputs import output_plan
    from stemlab.worker import tag_outputs

    row = jobs.get(tagged_upload["id"])
    folder = settings.data_dir / row["id"] / "stems"
    folder.mkdir()
    sf.write(folder / "instrumental.flac", np.zeros((44100, 2), "float32"), 44100, format="FLAC")
    tag_outputs(row, output_plan(row["mode"], row["keep"]), folder)
    written = tags.read(folder / "instrumental.flac")
    assert written["tags"]["title"] == "Gasolina (Instrumental)"
    assert (written["tags"]["artist"], written["tags"]["album"]) == ("Daddy Yankee", "Barrio Fino")
    assert written["cover"] is True
    assert written["tempo"] == {"bpm": "120.00", "key": "Am"}


@pytest.mark.skipif(not tags.available(), reason="ffmpeg is not installed")
@pytest.mark.parametrize("fmt", ["mp3", "wav"])
def test_converted_downloads_carry_the_song_tags(client, tagged_upload, fmt):
    folder = settings.data_dir / tagged_upload["id"] / "stems"
    folder.mkdir()
    sf.write(folder / "instrumental.flac", np.zeros((44100, 2), "float32"), 44100, format="FLAC")
    jobs.update(tagged_upload["id"], status="completed", stage="Ready")
    response = client.get(f"/api/jobs/{tagged_upload['id']}/audio/instrumental?format={fmt}")
    assert response.status_code == 200
    target = settings.data_dir / f"download.{fmt}"
    target.write_bytes(response.content)
    written = tags.read(target)
    assert written["tags"]["title"] == "Gasolina (Instrumental)"
    assert written["tags"]["artist"] == "Daddy Yankee"
    assert written["cover"] is (fmt == "mp3")


def test_a_failed_tagging_does_not_fail_the_job(client, monkeypatch, tmp_path):
    from stemlab.outputs import output_plan
    from stemlab.worker import tag_outputs

    row = jobs.get(upload(client).json()["id"])
    folder = settings.data_dir / row["id"] / "stems"
    folder.mkdir()
    sf.write(folder / "vocals.flac", np.zeros((441, 2), "float32"), 44100, format="FLAC")

    def refuse(*_args, **_kwargs):
        raise tags.TagError("no")

    monkeypatch.setattr(tags, "available", lambda: True)
    monkeypatch.setattr(tags, "copy", refuse)
    tag_outputs(row, output_plan("vocals"), folder)


def test_resurrection_can_be_the_vocal_model(client):
    response = client.post(
        "/api/jobs?filename=track.wav&mode=vocals&vocals=resurrection", content=wav()
    )
    assert response.status_code == 202 and response.json()["vocals"] == "resurrection"
