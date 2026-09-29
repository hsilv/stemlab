import shutil
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import numpy as np
import soundfile as sf
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from stemlab import jobs
from stemlab.config import settings
from stemlab.outputs import MODES, STEMS, output_plan
from stemlab.worker import separate_job

router = APIRouter(prefix="/api")


@router.get("/config")
def config():
    return {
        "max_upload_mb": settings.max_upload_mb,
        "max_duration_seconds": settings.max_duration_seconds,
        "stems": STEMS,
        "model": "htdemucs",
        "device": settings.device,
        "modes": MODES,
        "input_formats": ["wav", "mp3"],
    }


def require_job(job_id: UUID):
    row = jobs.get(str(job_id))
    if not row:
        raise HTTPException(404, "Job not found.")
    return row


def present(row):
    return {
        **{key: value for key, value in row.items() if key != "task_id"},
        "outputs": output_plan(row["mode"], row["keep"]),
    }


def enqueue(row):
    if settings.queue_mode == "local":
        return present(row)
    try:
        separate_job.apply_async(args=[row["id"]], task_id=row["task_id"], retry=False)
    except Exception:
        jobs.update(
            row["id"],
            expected=["queued"],
            status="failed",
            stage="Queue unavailable",
            error="Could not reach the queue. Start the services and retry.",
        )
    return present(jobs.get(row["id"]))


def validate_audio(path):
    try:
        with sf.SoundFile(path) as audio:
            allowed = {"MP3"} if path.suffix.lower() == ".mp3" else {"WAV", "WAVEX", "RF64"}
            if audio.format not in allowed:
                raise HTTPException(422, "The audio format must match its WAV or MP3 extension.")
            if audio.channels not in {1, 2}:
                raise HTTPException(422, "Use a mono or stereo WAV or MP3 file.")
            if not 8000 <= audio.samplerate <= 192000:
                raise HTTPException(422, "Supported sample rates are 8–192 kHz.")
            if not 1 <= audio.frames / audio.samplerate <= settings.max_duration_seconds:
                raise HTTPException(
                    422, f"Audio must be 1–{settings.max_duration_seconds} seconds long."
                )
            frames = 0
            for block in audio.blocks(blocksize=65536, dtype="float32"):
                frames += len(block)
                if not np.isfinite(block).all():
                    raise HTTPException(422, "The file contains invalid audio samples.")
            if frames != audio.frames:
                raise HTTPException(422, "The audio file is truncated.")
        return sf.info(path)
    except (sf.LibsndfileError, ValueError) as exc:
        raise HTTPException(422, "This is not a readable WAV or MP3 file.") from exc


@router.post("/jobs", status_code=202)
async def upload(
    request: Request,
    filename: str = Query(min_length=1, max_length=240),
    mode: Literal["all", "vocals", "instrumental", "custom"] = "all",
    keep: str | None = Query(default=None, max_length=100),
):
    """Stream a raw WAV (audio/wav) or MP3 (audio/mpeg) request body."""
    sources = keep.split(",") if keep is not None else None
    try:
        output_plan(mode, sources)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    filename = filename.replace("\\", "/").split("/")[-1]
    if not filename.lower().endswith((".wav", ".mp3")):
        raise HTTPException(422, "Choose a .wav or .mp3 file.")
    limit = settings.max_upload_mb * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
        except ValueError as exc:
            raise HTTPException(400, "Invalid content length.") from exc
        if length > limit:
            raise HTTPException(413, "The file exceeds the upload size limit.")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(settings.data_dir).free < limit + 1024**3:
        raise HTTPException(507, "Not enough free disk space. Delete old jobs first.")
    job_id = str(uuid4())
    folder = settings.data_dir / job_id
    folder.mkdir()
    source = jobs.source_path({"id": job_id, "filename": filename})
    try:
        size = 0
        with source.open("wb") as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "The file exceeds the upload size limit.")
                await run_in_threadpool(target.write, chunk)
        info = await run_in_threadpool(validate_audio, source)
        row = await run_in_threadpool(jobs.create, job_id, filename, info, mode, sources)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return await run_in_threadpool(enqueue, row)


@router.get("/jobs")
def list_jobs():
    jobs.recover_stale()
    return [present(row) for row in jobs.recent()]


@router.get("/jobs/{job_id}")
def job(job_id: UUID):
    jobs.recover_stale()
    return present(require_job(job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: UUID):
    require_job(job_id)
    key = str(job_id)
    if not jobs.update(key, expected=["queued"], status="cancelled", stage="Cancelled"):
        jobs.update(key, expected=["running"], status="cancelling", stage="Stopping worker")
    return present(jobs.get(key))


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(job_id: UUID):
    require_job(job_id)
    key = str(job_id)
    if not jobs.update(
        key,
        expected=["failed", "cancelled"],
        status="queued",
        stage="Waiting for worker",
        error=None,
        task_id=str(uuid4()),
    ):
        raise HTTPException(409, "Only failed or cancelled jobs can be retried.")
    return enqueue(jobs.get(key))


@router.delete("/jobs/{job_id}", status_code=204)
def delete(job_id: UUID):
    row = require_job(job_id)
    if row["status"] not in jobs.TERMINAL:
        raise HTTPException(409, "Cancel the job and wait for it to stop before deleting.")
    if not jobs.update(str(job_id), expected=list(jobs.TERMINAL), status="deleting"):
        raise HTTPException(409, "The job changed. Refresh and try again.")
    shutil.rmtree(settings.data_dir / str(job_id), ignore_errors=True)
    jobs.delete(str(job_id))


@router.get("/jobs/{job_id}/audio/{stem}")
def audio(job_id: UUID, stem: str, download: bool = False):
    row = require_job(job_id)
    available = {output["id"] for output in output_plan(row["mode"], row["keep"])}
    if stem != "original" and stem not in available:
        raise HTTPException(404, "Unknown stem.")
    if stem != "original" and row["status"] != "completed":
        raise HTTPException(409, "Stems are not ready.")
    folder = settings.data_dir / str(job_id)
    path = jobs.source_path(row) if stem == "original" else folder / "stems" / f"{stem}.wav"
    if not path.is_file():
        raise HTTPException(404, "Audio file not found.")
    return FileResponse(
        path,
        media_type="audio/mpeg" if path.suffix == ".mp3" else "audio/wav",
        filename=f"{Path(row['filename']).stem}-{stem}{path.suffix}",
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/jobs/{job_id}/download")
def download(job_id: UUID):
    row = require_job(job_id)
    if row["status"] != "completed":
        raise HTTPException(409, "Stems are not ready.")
    path = settings.data_dir / str(job_id) / "stems.zip"
    if not path.is_file():
        raise HTTPException(404, "Archive not found.")
    return FileResponse(
        path, media_type="application/zip", filename=f"{Path(row['filename']).stem}-stems.zip"
    )
