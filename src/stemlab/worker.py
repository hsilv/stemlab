import json
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from celery import Celery

from stemlab import filelock, jobs, tags
from stemlab.config import settings
from stemlab.environment import venv_python
from stemlab.outputs import output_plan, stem_file

app = Celery("stemlab", broker=settings.broker_url, backend=settings.result_backend)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    broker_transport_options={"visibility_timeout": settings.job_timeout_seconds + 600},
    broker_connection_timeout=3,
    task_publish_retry=False,
)


@app.task(name="stemlab.ping")
def ping() -> dict[str, str]:
    """Exercise queue delivery and result retrieval without downloading a model."""
    return {"status": "ok", "worker": "stemlab"}


@app.task(bind=True, name="stemlab.separate")
def separate_job(self, job_id):
    folder = settings.data_dir / job_id
    if not folder.exists():
        return
    with (folder / ".lock").open("a") as lock:
        if not filelock.try_lock(lock.fileno()):
            return
        run_job(job_id, self.request.id, lock.fileno())


def tag_outputs(row, plan, output):
    """Give each output the song's artist, album, cover and the rest, and its own version name.

    A failure only costs the tags: the audio is already written.
    """
    if not tags.available() or not jobs.has_source(row):
        return
    for group in plan:
        path = stem_file(output, group["id"])
        try:
            tags.copy(jobs.source_path(row), path, **tags.output_arguments(row, group["id"]))
        except (tags.TagError, OSError):
            logging.exception("Could not tag %s for %s", group["id"], row["id"])


def extend_command(row, output):
    """The child that writes an extended edit; loops come from existing stems when there are."""
    command = [
        sys.executable,
        "-m",
        "stemlab.extend",
        str(jobs.source_path(row)),
        str(output),
        "--params",
        json.dumps(row["extend"]),
        "--bpm",
        str(row["bpm"]),
        "--downbeat",
        str(row["downbeat"]),
        "--model",
        row["model"],
        "--shifts",
        str(row["shifts"]),
        "--overlap",
        str(row["overlap"]),
    ]
    parts = jobs.full_stems_folder(row["song_id"] or row["id"])
    return command + (["--parts", str(parts)] if parts else [])


def ace_python():
    """The interpreter of the ACE-Step environment; it may not be installed."""
    return venv_python(settings.ace_step_dir / "ace" / ".venv")


def generate_command(row, output):
    """The child that writes a backing track, run by ACE-Step's own interpreter."""
    request = row["generate"]
    command = [
        str(ace_python()),
        "-P",
        str(Path(__file__).with_name("generate.py")),
        str(output),
        "--ace-dir",
        str(settings.ace_step_dir),
        "--prompt",
        request["prompt"],
        "--duration",
        str(request["duration"]),
        "--seed",
        str(request["seed"]),
    ]
    reference = jobs.reference_path(row)
    return command + (["--reference", str(reference)] if reference else [])


def child_command(row, output, options):
    """The process that writes this job's outputs."""
    if row["mode"] == "extend":
        return extend_command(row, output)
    if row["mode"] == "generate":
        return generate_command(row, output)
    return [
        sys.executable,
        "-m",
        "stemlab.inference",
        str(jobs.source_path(row)),
        str(output),
        *options,
    ]


def range_options(row):
    """CLI arguments for one section, several ranges, or the whole track."""
    if row.get("ranges"):
        encoded = ",".join(f"{start}-{end}" for start, end in row["ranges"])
        return ["--ranges", encoded]
    if row["range_start"] is not None:
        return ["--start", str(row["range_start"]), "--end", str(row["range_end"])]
    return []


def run_job(job_id, task_id, lock_fd):
    if not jobs.claim(job_id, task_id):
        return
    # Local import: analysis.py pulls in the inference stack, which the API process must not load.
    from stemlab.analysis import inference_lock

    with inference_lock():
        separate(job_id, task_id, lock_fd)


def separate(job_id, task_id, lock_fd):
    folder = settings.data_dir / job_id
    output = folder / "stems"
    process = None
    started = time.monotonic()
    outcome, error = "failed", None
    try:
        row = jobs.get(job_id)
        plan = output_plan(row["mode"], row["keep"])
        options = [
            "--mode",
            row["mode"],
            "--model",
            row["model"],
            "--vocals",
            row["vocals"],
            "--instruments-from",
            row["instruments_from"],
            "--shifts",
            str(row["shifts"]),
            "--overlap",
            str(row["overlap"]),
        ]
        options.extend(range_options(row))
        if row["keep"] is not None:
            options.extend(["--keep", ",".join(row["keep"])])
        shutil.rmtree(output, ignore_errors=True)
        (folder / "stems.zip").unlink(missing_ok=True)
        with (folder / "worker.log").open("w") as log:
            process = subprocess.Popen(
                child_command(row, output, options),
                stdout=log,
                stderr=log,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                **filelock.inherit(lock_fd),
            )
            while process.poll() is None:
                row = jobs.get(job_id)
                if not row or row["status"] != "running" or row["task_id"] != task_id:
                    outcome = "cancelled"
                    break
                if time.monotonic() - started > settings.job_timeout_seconds:
                    raise TimeoutError("Processing exceeded the configured time limit.")
                with (folder / "worker.log").open("rb") as progress:
                    progress.seek(max(0, (folder / "worker.log").stat().st_size - 4096))
                    tail = progress.read().decode(errors="replace")
                stage = "Loading model (first run may download weights)"
                for line in tail.splitlines():
                    if line.startswith("STAGE:"):
                        stage = line.removeprefix("STAGE:")
                jobs.update(job_id, expected=["running"], stage=stage)
                time.sleep(1)
        if outcome == "cancelled":
            return
        if process.returncode:
            raise RuntimeError(
                "Processing failed. Check worker logs, model download access and available "
                "GPU/system memory, then retry."
            )
        jobs.update(job_id, expected=["running"], stage="Preparing downloads")
        tag_outputs(row, plan, output)
        with zipfile.ZipFile(folder / "stems.zip", "w", compression=zipfile.ZIP_STORED) as archive:
            for group in plan:
                path = stem_file(output, group["id"])
                if path is None:
                    raise RuntimeError("The model did not produce the requested outputs.")
                archive.write(path, path.name)
        outcome = "completed"
    except Exception as exc:
        logging.exception("Separation failed for %s", job_id)
        if (folder / "worker.log").exists():
            logging.error("Inference output: %s", (folder / "worker.log").read_text()[-8000:])
        error = str(exc)
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        row = jobs.get(job_id)
        if row and row["status"] == "cancelling":
            outcome = "cancelled"
        if outcome != "completed":
            shutil.rmtree(output, ignore_errors=True)
            (folder / "stems.zip").unlink(missing_ok=True)
        jobs.update(
            job_id,
            expected=["running", "cancelling"],
            status=outcome,
            stage={"completed": "Ready", "failed": "Failed", "cancelled": "Cancelled"}[outcome],
            error=error,
        )
