import io
import zipfile
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from stemlab import generate, jobs
from stemlab.config import settings
from stemlab.main import app
from stemlab.outputs import output_plan
from stemlab.worker import ace_python, separate_job


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "ace_step_dir", tmp_path / "ace-step")
    monkeypatch.setattr(settings, "queue_mode", "local")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def installed(client):
    ace_python().parent.mkdir(parents=True)
    ace_python().touch()


def wav(seconds=1.1, rate=16000, invalid=False):
    data = np.zeros((int(rate * seconds), 2), dtype="float32")
    if invalid:
        data[100] = np.nan
    buffer = io.BytesIO()
    sf.write(buffer, data, rate, format="WAV", subtype="FLOAT")
    return buffer.getvalue()


def make(client, **params):
    return client.post("/api/generate", params={"prompt": "warm lo-fi keys", **params})


def test_output_plan_is_one_backing_track():
    assert [group["id"] for group in output_plan("generate")] == ["backing"]


def test_config_says_whether_generation_is_set_up(client, installed):
    assert client.get("/api/config").json()["generate"] == {"ready": True, "seconds": [10, 240]}


def test_config_reports_a_missing_environment(client):
    assert client.get("/api/config").json()["generate"]["ready"] is False
    assert make(client).status_code == 503


def test_text_only_track(client, installed):
    response = make(client, duration=20, seed=5)
    assert response.status_code == 202
    row = response.json()
    assert row["mode"] == "generate"
    assert row["status"] == "queued"
    assert row["generate"] == {"prompt": "warm lo-fi keys", "duration": 20, "seed": 5}
    assert [output["id"] for output in row["outputs"]] == ["backing"]
    assert row["filename"] == "warm lo-fi keys.wav"
    assert jobs.reference_path(row) is None
    assert not jobs.has_source(row)
    assert client.get(f"/api/jobs/{row['id']}/audio/original").status_code == 404


def test_each_track_gets_its_own_seed_unless_one_is_given(client, installed):
    seeds = {make(client).json()["generate"]["seed"] for _ in range(3)}
    assert len(seeds) > 1


@pytest.mark.parametrize(
    "params", [{"duration": 9}, {"duration": 241}, {"prompt": "   "}, {"prompt": ""}]
)
def test_rejects_bad_requests(client, installed, params):
    assert make(client, **params).status_code == 422
    assert client.get("/api/jobs").json() == []


def test_reference_upload_is_stored_with_the_job(client, installed):
    response = client.post(
        "/api/generate",
        params={"prompt": "in this style", "filename": "ref.wav"},
        content=wav(),
    )
    assert response.status_code == 202
    row = jobs.get(response.json()["id"])
    assert jobs.reference_path(row).name == "reference.wav"


def test_bad_reference_upload_leaves_nothing_behind(client, installed):
    response = client.post(
        "/api/generate",
        params={"prompt": "in this style", "filename": "ref.wav"},
        content=wav(invalid=True),
    )
    assert response.status_code == 422
    assert client.get("/api/jobs").json() == []
    assert not any(path.is_dir() for path in settings.data_dir.iterdir())


def test_reference_from_a_song_in_the_crate(client, installed):
    song = client.post("/api/jobs?filename=song.wav", content=wav()).json()
    response = make(client, reference_job=song["id"])
    assert response.status_code == 202
    assert jobs.reference_path(jobs.get(response.json()["id"])).name == "reference.wav"
    # A track of a song that is not finished cannot be a reference yet.
    assert make(client, reference_job=song["id"], reference_stem="vocals").status_code in {
        409,
        422,
    }


def test_reference_from_a_finished_stem(client, installed):
    song = client.post("/api/jobs?filename=song.wav", content=wav()).json()
    folder = settings.data_dir / song["id"] / "stems"
    folder.mkdir()
    sf.write(folder / "vocals.flac", np.zeros((16000, 2), dtype="float32"), 16000, format="FLAC")
    assert make(client, reference_job=song["id"], reference_stem="vocals").status_code == 409
    jobs.update(song["id"], status="completed")
    response = make(client, reference_job=song["id"], reference_stem="vocals")
    assert response.status_code == 202
    assert jobs.reference_path(jobs.get(response.json()["id"])).name == "reference.flac"
    assert make(client, reference_job=song["id"], reference_stem="drums").status_code == 404


def test_reference_errors(client, installed):
    missing = "00000000-0000-4000-8000-000000000000"
    assert make(client, reference_job=missing).status_code == 404
    both = client.post(
        "/api/generate",
        params={"prompt": "x", "filename": "ref.wav", "reference_job": missing},
        content=wav(),
    )
    assert both.status_code == 422


class Finished:
    returncode = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        return None

    def kill(self):
        return None

    def wait(self, timeout=None):
        return self.returncode


def run_worker(row):
    seen = {}

    def fake_popen(command, **kwargs):
        seen["command"] = command
        stems = settings.data_dir / row["id"] / "stems"
        stems.mkdir(parents=True, exist_ok=True)
        sf.write(
            stems / "backing.flac",
            np.zeros((4800, 2), dtype="float32"),
            48000,
            format="FLAC",
        )
        return Finished()

    with patch("stemlab.worker.subprocess.Popen", side_effect=fake_popen):
        separate_job.apply(args=[row["id"]], task_id=jobs.get(row["id"])["task_id"])
    return seen["command"]


def test_worker_runs_the_acestep_interpreter_and_zips_the_track(client, installed):
    row = client.post(
        "/api/generate",
        params={"prompt": "in this style", "duration": 15, "seed": 3, "filename": "ref.wav"},
        content=wav(),
    ).json()
    command = run_worker(row)
    assert command[:2] == [str(ace_python()), "-P"]
    assert command[2].endswith("stemlab/generate.py")
    assert command[command.index("--prompt") + 1] == "in this style"
    assert command[command.index("--duration") + 1] == "15"
    assert command[command.index("--seed") + 1] == "3"
    assert command[command.index("--reference") + 1].endswith("reference.wav")
    finished = jobs.get(row["id"])
    assert finished["status"] == "completed"
    with zipfile.ZipFile(settings.data_dir / row["id"] / "stems.zip") as archive:
        assert archive.namelist() == ["backing.flac"]
    audio = client.get(f"/api/jobs/{row['id']}/audio/backing")
    assert audio.status_code == 200
    assert client.get(f"/api/jobs/{row['id']}/download").status_code == 200


def test_text_only_worker_command_has_no_reference(client, installed):
    row = make(client).json()
    assert "--reference" not in run_worker(row)
    assert jobs.get(row["id"])["status"] == "completed"


def test_retry_keeps_the_prompt_and_reference(client, installed):
    row = make(client, seed=9).json()
    jobs.update(row["id"], status="failed")
    assert client.post(f"/api/jobs/{row['id']}/retry").status_code == 202
    assert jobs.get(row["id"])["generate"]["seed"] == 9


def test_reference_excerpt_is_the_middle_of_a_long_song(tmp_path):
    rate = 1000
    song = np.arange(100 * rate, dtype="float32")[:, None].repeat(2, axis=1) / (100 * rate)
    sf.write(tmp_path / "song.wav", song, rate, subtype="FLOAT")
    excerpt, _ = sf.read(generate.reference_excerpt(tmp_path / "song.wav", tmp_path))
    assert len(excerpt) == generate.REFERENCE_SECONDS * rate
    assert excerpt[0, 0] == pytest.approx(35 / 100, abs=1e-3)


def test_reference_excerpt_keeps_a_short_song_whole(tmp_path):
    sf.write(tmp_path / "short.wav", np.zeros((5000, 2), dtype="float32"), 1000, subtype="FLOAT")
    excerpt, _ = sf.read(generate.reference_excerpt(tmp_path / "short.wav", tmp_path))
    assert len(excerpt) == 5000


def test_the_child_resolves_its_paths_before_it_changes_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = generate.parse(
        ["data/job/stems", "--ace-dir", "data/ace-step", "--prompt", "x", "--duration", "10"]
        + ["--seed", "1", "--reference", "data/job/reference.mp3"]
    )
    assert args.output == tmp_path / "data/job/stems"
    assert args.ace_dir == tmp_path / "data/ace-step"
    assert args.reference == tmp_path / "data/job/reference.mp3"
    bare = generate.parse(
        ["out", "--ace-dir", "a", "--prompt", "x", "--duration", "10", "--seed", "1"]
    )
    assert bare.reference is None
