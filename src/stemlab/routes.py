import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import numpy as np
import soundfile as sf
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from stemlab import jobs, mixxx
from stemlab.config import (
    INSTRUMENT_SOURCES,
    MAX_SHIFTS,
    MODELS,
    OVERLAP_RANGE,
    VOCAL_MODELS,
    InstrumentsFrom,
    Model,
    Vocals,
    settings,
)
from stemlab.inference import parse_ranges
from stemlab.outputs import MODES, STEMS, is_instrumental, output_plan
from stemlab.worker import separate_job

router = APIRouter(prefix="/api")
MIN_SECTION_SECONDS = 1


@router.get("/config")
def config():
    return {
        "max_upload_mb": settings.max_upload_mb,
        "max_duration_seconds": settings.max_duration_seconds,
        "stems": STEMS,
        "models": MODELS,
        "vocal_models": VOCAL_MODELS,
        "instrument_sources": INSTRUMENT_SOURCES,
        "defaults": {
            "model": settings.model,
            "vocals": settings.vocals,
            "instruments_from": settings.instruments_from,
            "shifts": settings.shifts,
            "overlap": settings.overlap,
        },
        "max_shifts": MAX_SHIFTS,
        "device": settings.device,
        "modes": MODES,
        "input_formats": ["wav", "mp3"],
    }


@router.get("/mixxx/cues")
def mixxx_cues(filename: str = Query(min_length=1, max_length=240)):
    return mixxx.hot_cues(filename)


def require_job(job_id: UUID):
    row = jobs.get(str(job_id))
    if not row:
        raise HTTPException(404, "Job not found.")
    return row


def present(row):
    spans = row["ranges"]
    if not spans and row["range_start"] is not None:
        spans = [[row["range_start"], row["range_end"]]]
    return {
        **{key: value for key, value in row.items() if key != "task_id"},
        "ranges": spans,
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


def resolve_section(start, end, duration):
    """Return (start, end) seconds to separate, or None for the whole track."""
    if start is None and end is None:
        return None
    start, end = start or 0.0, end or duration
    if end > duration:
        raise HTTPException(422, "The section ends after the end of the track.")
    if end - start < MIN_SECTION_SECONDS:
        raise HTTPException(422, f"The section must be at least {MIN_SECTION_SECONDS} second long.")
    return start, end


MAX_RANGES = 12


def resolve_ranges(spans, duration):
    """Return sorted (start, end) pairs, or None when the effect covers the whole track."""
    if not spans:
        return None
    if len(spans) > MAX_RANGES:
        raise HTTPException(422, f"Choose at most {MAX_RANGES} ranges.")
    resolved = []
    for start, end in spans:
        start = 0.0 if start is None else start
        end = duration if end is None else end
        if end > duration:
            raise HTTPException(422, "A range ends after the end of the track.")
        if end - start < MIN_SECTION_SECONDS:
            raise HTTPException(
                422, f"Each range must be at least {MIN_SECTION_SECONDS} second long."
            )
        resolved.append((start, end))
    resolved.sort()
    for previous, following in zip(resolved, resolved[1:]):
        if following[0] < previous[1]:
            raise HTTPException(
                422, "Ranges overlap. Leave a gap between them, or make them one range."
            )
    return resolved


def uploaded_name(filename):
    filename = filename.replace("\\", "/").split("/")[-1]
    if not filename.lower().endswith((".wav", ".mp3")):
        raise HTTPException(422, "Choose a .wav or .mp3 file.")
    return filename


def upload_limit(request):
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
    return limit


async def write_upload(request, source, limit):
    size = 0
    with source.open("wb") as target:
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, "The file exceeds the upload size limit.")
            await run_in_threadpool(target.write, chunk)


@router.post("/jobs", status_code=202)
async def upload(
    request: Request,
    filename: str = Query(min_length=1, max_length=240),
    mode: Literal["all", "vocals", "instrumental", "custom"] = "all",
    keep: str | None = Query(default=None, max_length=100),
    model: Model = settings.model,
    vocals: Vocals = settings.vocals,
    instruments_from: InstrumentsFrom = settings.instruments_from,
    shifts: int = Query(default=settings.shifts, ge=0, le=MAX_SHIFTS),
    overlap: float = Query(default=settings.overlap, ge=OVERLAP_RANGE[0], le=OVERLAP_RANGE[1]),
    start: float | None = Query(default=None, ge=0),
    end: float | None = Query(default=None, gt=0),
    ranges: str | None = Query(default=None, max_length=500),
    bpm: float | None = Query(default=None, ge=0),
    camelot: str | None = Query(default=None, max_length=16),
    key_name: str | None = Query(default=None, max_length=80),
    downbeat: float | None = Query(default=None, ge=0),
    analysis_warning: str | None = Query(default=None, max_length=500),
):
    """Stream a raw WAV (audio/wav) or MP3 (audio/mpeg) request body."""
    sources = keep.split(",") if keep is not None else None
    try:
        plan = output_plan(mode, sources)
        if instruments_from == "inverse" and not is_instrumental(plan):
            raise ValueError("Mix minus vocals only works for No vocals.")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    filename = uploaded_name(filename)
    limit = upload_limit(request)
    job_id = str(uuid4())
    folder = settings.data_dir / job_id
    folder.mkdir()
    source = jobs.source_path({"id": job_id, "filename": filename})
    try:
        await write_upload(request, source, limit)
        info = await run_in_threadpool(validate_audio, source)
        if ranges and (start is not None or end is not None):
            raise HTTPException(422, "Send either start and end, or ranges.")
        section, stored_ranges = None, None
        if ranges:
            try:
                parsed = parse_ranges(ranges)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            resolved = resolve_ranges(parsed, info.duration)
            if resolved and len(resolved) == 1:
                section = resolved[0]
            else:
                stored_ranges = resolved
        else:
            section = resolve_section(start, end, info.duration)
        row = await run_in_threadpool(
            jobs.create,
            job_id,
            filename,
            info,
            {
                "model": model,
                "vocals": vocals,
                "instruments_from": instruments_from,
                "shifts": shifts,
                "overlap": overlap,
            },
            mode,
            sources,
            section,
            stored_ranges,
            {
                "bpm": bpm,
                "camelot": camelot,
                "key_name": key_name,
                "downbeat": downbeat,
                "analysis_warning": analysis_warning,
            },
        )
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


ANALYSIS_STAGES = frozenset(
    {
        "Checking the file",
        "Reading tempo and key",
        "Waiting for the separator",
        "Isolating drums and bass",
        "Isolating the instrumental",
    }
)
READING_FIELDS = ("bpm", "camelot", "key_name", "downbeat", "warning")


def analysis_interpreter():
    return Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"


def analysis_dir(analysis_id):
    return settings.data_dir / "analyses" / analysis_id


def analysis_source(analysis_id, filename):
    suffix = ".mp3" if filename.lower().endswith(".mp3") else ".wav"
    return analysis_dir(analysis_id) / f"source{suffix}"


def stage_of(line):
    text = line.strip()
    if text.startswith("STAGE:"):
        text = text.removeprefix("STAGE:").strip()
    if text in ANALYSIS_STAGES:
        return text
    return None


def latest_stage(path):
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 4096))
        text = handle.read().decode(errors="replace")
    stage = None
    for line in text.splitlines():
        found = stage_of(line)
        if found:
            stage = found
    return stage


def analysis_error(path):
    message = "Analysis failed."
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            if line.strip() and stage_of(line) is None:
                message = line.strip()
    return message[:500]


def reading_fields(payload):
    warning = payload.get("warning")
    bpm = payload.get("bpm")
    return {
        "bpm": None if bpm is None else round(float(bpm), 2),
        "camelot": payload.get("camelot"),
        "key_name": payload.get("key_name"),
        "downbeat": payload.get("downbeat"),
        "warning": "" if warning is None else warning,
    }


def present_analysis(row):
    payload = {
        "id": row["id"],
        "status": row["status"],
        "stage": row["stage"],
        "error": row["error"],
    }
    if row["status"] == "running":
        stage = latest_stage(analysis_dir(row["id"]) / "stages.log")
        if stage:
            payload["stage"] = stage
    if row["status"] == "completed":
        for key in READING_FIELDS:
            payload[key] = row[key]
        if payload["bpm"] is not None:
            payload["bpm"] = round(float(payload["bpm"]), 2)
        if payload["warning"] is None:
            payload["warning"] = ""
    return payload


def follow_analysis(analysis_id, source):
    """Run the analysis child. Its stdout and stderr land under the data directory."""
    folder = source.parent
    stdout_path = folder / "reading.json"
    stderr_path = folder / "stages.log"
    process = None
    try:
        with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
            process = subprocess.Popen(
                [str(analysis_interpreter()), "-m", "stemlab.analysis", str(source)],
                stdout=stdout,
                stderr=stderr,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            started = time.monotonic()
            seen = None
            while process.poll() is None:
                stage = latest_stage(stderr_path)
                if stage and stage != seen:
                    jobs.update_analysis(analysis_id, stage=stage)
                    seen = stage
                if time.monotonic() - started > settings.job_timeout_seconds:
                    raise TimeoutError("Analysis exceeded the configured time limit.")
                time.sleep(0.2)
        if process.returncode:
            raise RuntimeError(analysis_error(stderr_path))
        try:
            fields = reading_fields(json.loads(stdout_path.read_text()))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Analysis returned an unreadable result.") from exc
        recorded = {"status": "completed", "error": None, **fields}
        stage = latest_stage(stderr_path)
        if stage:
            recorded["stage"] = stage
        source.unlink(missing_ok=True)
        jobs.update_analysis(analysis_id, **recorded)
    except Exception as exc:
        logging.exception("Analysis failed for %s", analysis_id)
        recorded = {"status": "failed", "error": str(exc)}
        stage = latest_stage(stderr_path)
        if stage:
            recorded["stage"] = stage
        source.unlink(missing_ok=True)
        jobs.update_analysis(analysis_id, **recorded)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        source.unlink(missing_ok=True)


@router.post("/analyses", status_code=202)
async def start_analysis(request: Request, filename: str = Query(min_length=1, max_length=240)):
    """Stream a raw WAV or MP3 and measure tempo and key in a child process."""
    filename = uploaded_name(filename)
    limit = upload_limit(request)
    analysis_id = str(uuid4())
    folder = analysis_dir(analysis_id)
    folder.mkdir(parents=True)
    source = analysis_source(analysis_id, filename)
    try:
        await write_upload(request, source, limit)
        await run_in_threadpool(validate_audio, source)
        row = await run_in_threadpool(jobs.create_analysis, analysis_id)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    payload = present_analysis(row)
    threading.Thread(
        target=follow_analysis,
        args=(analysis_id, source),
        name=f"analysis-{analysis_id}",
        daemon=True,
    ).start()
    return payload


@router.get("/analyses/{analysis_id}")
def analysis(analysis_id: UUID):
    row = jobs.get_analysis(str(analysis_id))
    if not row:
        raise HTTPException(404, "Analysis not found.")
    return present_analysis(row)
