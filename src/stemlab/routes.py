import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4

import numpy as np
import soundfile as sf
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from stemlab import exports, extend, jobs, mixxx, tags
from stemlab.config import (
    GENERATE_SECONDS,
    INSTRUMENT_SOURCES,
    MAX_SHIFTS,
    MODELS,
    OVERLAP_RANGE,
    VOCAL_MODELS,
    InstrumentsFrom,
    Model,
    Vocals,
    instrumental_only,
    settings,
)
from stemlab.environment import venv_python
from stemlab.inference import parse_ranges
from stemlab.outputs import MODES, STEMS, is_instrumental, output_plan, stem_file
from stemlab.worker import ace_python, separate_job

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
        "input_formats": [suffix.lstrip(".") for suffix in jobs.INPUT_SUFFIXES],
        "export_formats": exports.formats(),
        "generate": {"ready": ace_python().is_file(), "seconds": GENERATE_SECONDS},
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


# What libsndfile calls each container an upload's extension may hold.
CONTAINER_FORMATS = {".wav": {"WAV", "WAVEX", "RF64"}, ".mp3": {"MP3"}, ".flac": {"FLAC"}}


def validate_audio(path):
    try:
        with sf.SoundFile(path) as audio:
            allowed = CONTAINER_FORMATS.get(path.suffix.lower(), set())
            if audio.format not in allowed:
                raise HTTPException(
                    422, "The audio format must match its WAV, MP3 or FLAC extension."
                )
            if audio.channels not in {1, 2}:
                raise HTTPException(422, "Use a mono or stereo WAV, MP3 or FLAC file.")
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
        raise HTTPException(422, "This is not a readable WAV, MP3 or FLAC file.") from exc


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
    if not filename.lower().endswith(jobs.INPUT_SUFFIXES):
        raise HTTPException(422, "Choose a .wav, .mp3 or .flac file.")
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


def extension_params(raw, bpm, downbeat, duration):
    """The validated intro and outro of an extended edit, or a 422 telling the listener why not."""
    if not bpm or downbeat is None:
        raise HTTPException(422, "A steady tempo was not found, so there is no grid to extend on.")
    try:
        params = extend.validate(json.loads(raw or "null"), duration)
        extend.check_length(params, bpm, downbeat, duration)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return params


def reuse_source(original, source):
    """Give a new job its own name for an already uploaded song: a hard link costs no space."""
    if not original.is_file():
        raise HTTPException(404, "The original upload is no longer available.")
    try:
        os.link(original, source)
    except OSError:
        shutil.copyfile(original, source)


@router.post("/jobs", status_code=202)
async def upload(
    request: Request,
    filename: str | None = Query(default=None, min_length=1, max_length=240),
    from_job: UUID | None = None,
    mode: Literal["all", "vocals", "instrumental", "custom", "extend"] = "all",
    keep: str | None = Query(default=None, max_length=100),
    model: Model = settings.model,
    vocals: Vocals = settings.vocals,
    instruments_from: InstrumentsFrom = settings.instruments_from,
    shifts: int = Query(default=settings.shifts, ge=0, le=MAX_SHIFTS),
    overlap: float = Query(default=settings.overlap, ge=OVERLAP_RANGE[0], le=OVERLAP_RANGE[1]),
    start: float | None = Query(default=None, ge=0),
    end: float | None = Query(default=None, gt=0),
    ranges: str | None = Query(default=None, max_length=500),
    extend: str | None = Query(default=None, max_length=2000),
    bpm: float | None = Query(default=None, ge=0),
    camelot: str | None = Query(default=None, max_length=16),
    key_name: str | None = Query(default=None, max_length=80),
    downbeat: float | None = Query(default=None, ge=0),
    analysis_warning: str | None = Query(default=None, max_length=500),
):
    """Stream a raw WAV (audio/wav), MP3 (audio/mpeg) or FLAC (audio/flac) request body.

    With from_job there is no body: the new job is another edit of that job's uploaded song.
    mode=extend (only with from_job) adds an intro and outro, described by the JSON in extend.
    """
    sources = keep.split(",") if keep is not None else None
    try:
        plan = output_plan(mode, sources)
        if instrumental_only(instruments_from) and not is_instrumental(plan):
            raise ValueError("That choice only works for No vocals.")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if from_job is not None:
        original = require_job(from_job)
        filename = original["filename"]
    elif mode == "extend":
        raise HTTPException(422, "An extended edit starts from a song that is already uploaded.")
    elif filename is None:
        raise HTTPException(422, "Send a filename, or from_job to edit an uploaded song again.")
    else:
        filename = uploaded_name(filename)
        limit = upload_limit(request)
    job_id = str(uuid4())
    folder = settings.data_dir / job_id
    folder.mkdir()
    source = jobs.source_path({"id": job_id, "filename": filename})
    try:
        if from_job is not None:
            await run_in_threadpool(reuse_source, jobs.source_path(original), source)
        else:
            await write_upload(request, source, limit)
        info = await run_in_threadpool(validate_audio, source)
        if ranges and (start is not None or end is not None):
            raise HTTPException(422, "Send either start and end, or ranges.")
        section, stored_ranges, extension = None, None, None
        if mode == "extend":
            bpm = bpm or original["bpm"]
            downbeat = downbeat if downbeat is not None else original["downbeat"]
            key_name = key_name or original["key_name"]
            camelot = camelot or original["camelot"]
            extension = extension_params(extend, bpm, downbeat, info.duration)
        elif ranges:
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
            song_id=(original["song_id"] or original["id"]) if from_job is not None else None,
            extend=extension,
        )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return await run_in_threadpool(enqueue, row)


def reference_source(row, stem):
    """The stored audio of a crate song that a generated track should sound like."""
    if stem == "original":
        return jobs.source_path(row)
    if stem not in {output["id"] for output in output_plan(row["mode"], row["keep"])}:
        raise HTTPException(422, "That song has no such track.")
    if row["status"] != "completed":
        raise HTTPException(409, "That song is not ready yet.")
    return stem_file(settings.data_dir / row["id"] / "stems", stem)


@router.post("/generate", status_code=202)
async def generate(
    request: Request,
    prompt: str = Query(min_length=1, max_length=500),
    duration: int = Query(default=30, ge=GENERATE_SECONDS[0], le=GENERATE_SECONDS[1]),
    seed: int | None = Query(default=None, ge=0, lt=2**31),
    filename: str | None = Query(default=None, min_length=1, max_length=240),
    reference_job: UUID | None = None,
    reference_stem: str = Query(default="original", max_length=40),
):
    """Write a backing track from a text prompt, optionally in the style of a reference song.

    The reference is a raw WAV, MP3 or FLAC request body (named by filename), or a song already
    in the crate (reference_job, and its original or one of its tracks as reference_stem).
    """
    if not ace_python().is_file():
        raise HTTPException(503, "Generation is not set up. See the README for ACE-Step.")
    if filename is not None and reference_job is not None:
        raise HTTPException(422, "Send a reference file or a song from the crate, not both.")
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(422, "Describe the music you want.")
    if filename is not None:
        suffix = Path(uploaded_name(filename)).suffix.lower()
        limit = upload_limit(request)
    elif reference_job is not None:
        original = require_job(reference_job)
        crate_file = reference_source(original, reference_stem)
        if crate_file is None or not crate_file.is_file():
            raise HTTPException(404, "That audio is no longer available.")
        suffix = crate_file.suffix
    job_id = str(uuid4())
    folder = settings.data_dir / job_id
    folder.mkdir(parents=True)
    try:
        if filename is not None:
            reference = folder / f"reference{suffix}"
            await write_upload(request, reference, limit)
            await run_in_threadpool(validate_audio, reference)
        elif reference_job is not None:
            await run_in_threadpool(reuse_source, crate_file, folder / f"reference{suffix}")
        title = re.sub(r'[\\/:*?"<>|]+', " ", prompt)[:60].strip() or "Backing track"
        row = await run_in_threadpool(
            jobs.create,
            job_id,
            f"{title}.wav",
            SimpleNamespace(duration=duration, samplerate=48000, channels=2),
            {
                "model": settings.model,
                "vocals": settings.vocals,
                "instruments_from": settings.instruments_from,
                "shifts": settings.shifts,
                "overlap": settings.overlap,
            },
            "generate",
            generate={
                "prompt": prompt,
                "duration": duration,
                "seed": random.randrange(2**31) if seed is None else seed,
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


ExportFormat = Literal["flac", "wav", "mp3"]


def export_scratch(folder):
    """A private directory for one conversion; the response removes it after sending."""
    scratch = folder / "exports" / uuid4().hex
    scratch.mkdir(parents=True)
    return scratch


def convert_or_fail(source, fmt, target, row=None, stem=None):
    """Convert one stem for download and give the result the song's tags (when ffmpeg exists)."""
    try:
        exports.convert(source, fmt, target)
        if row is not None and tags.available():
            try:
                if jobs.has_source(row):
                    tags.copy(jobs.source_path(row), target, **tags.output_arguments(row, stem))
            except tags.TagError:
                logging.exception("Could not tag %s", target.name)
    except exports.ExportUnavailable as exc:
        shutil.rmtree(target.parent, ignore_errors=True)
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(target.parent, ignore_errors=True)
        logging.exception("Export to %s failed for %s", fmt, source)
        raise HTTPException(500, "Could not convert this track. Try FLAC or WAV.") from exc


@router.get("/jobs/{job_id}/audio/{stem}")
def audio(
    job_id: UUID,
    stem: str,
    download: bool = False,
    format: ExportFormat | None = None,
):
    row = require_job(job_id)
    available = {output["id"] for output in output_plan(row["mode"], row["keep"])}
    if stem != "original" and stem not in available:
        raise HTTPException(404, "Unknown stem.")
    if stem != "original" and row["status"] != "completed":
        raise HTTPException(409, "Stems are not ready.")
    folder = settings.data_dir / str(job_id)
    path = jobs.source_path(row) if stem == "original" else stem_file(folder / "stems", stem)
    if path is None or not path.is_file():
        raise HTTPException(404, "Audio file not found.")
    name = f"{Path(row['filename']).stem}-{stem}"
    if format and stem != "original" and path.suffix != exports.SUFFIX[format]:
        scratch = export_scratch(folder)
        target = scratch / f"{name}{exports.SUFFIX[format]}"
        convert_or_fail(path, format, target, row, stem)
        return FileResponse(
            target,
            media_type=exports.MEDIA_TYPES[target.suffix],
            filename=target.name,
            content_disposition_type="attachment" if download else "inline",
            background=BackgroundTask(shutil.rmtree, scratch, ignore_errors=True),
        )
    return FileResponse(
        path,
        media_type=exports.MEDIA_TYPES[path.suffix],
        filename=f"{name}{path.suffix}",
        content_disposition_type="attachment" if download else "inline",
    )


class ExtendPreviewRequest(BaseModel):
    extend: dict
    bpm: float | None = None
    downbeat: float | None = None
    # A manual edit's operation to hear, by its place in the list.
    only: int | None = None


@router.post("/jobs/{job_id}/extend-preview")
def extend_preview(job_id: UUID, body: ExtendPreviewRequest):
    """A short FLAC of the intro, the start of the song, the end of the song and the outro."""
    row = require_job(job_id)
    bpm = body.bpm or row["bpm"]
    downbeat = body.downbeat if body.downbeat is not None else row["downbeat"]
    params = extension_params(json.dumps(body.extend), bpm, downbeat, row["duration"])
    folder = settings.data_dir / str(job_id)
    scratch = export_scratch(folder)
    command = [
        str(analysis_interpreter()),
        "-m",
        "stemlab.extend",
        str(jobs.source_path(row)),
        str(scratch),
        "--name",
        "preview",
        "--preview",
        "--params",
        json.dumps(params),
        "--bpm",
        str(bpm),
        "--downbeat",
        str(downbeat),
        "--model",
        row["model"],
    ]
    parts = jobs.full_stems_folder(row["song_id"] or row["id"])
    if parts:
        command += ["--parts", str(parts)]
    if body.only is not None:
        operations = params.get("operations") or []
        if not 0 <= body.only < len(operations):
            raise HTTPException(422, "There is no such operation.")
        command += ["--only", str(body.only)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        raise HTTPException(504, "The preview took too long. Try again.") from exc
    path = scratch / "preview.flac"
    if result.returncode or not path.is_file():
        shutil.rmtree(scratch, ignore_errors=True)
        if result.returncode == extend.BUSY:
            raise HTTPException(503, "The separator is busy. Try again in a moment.")
        logging.error("Extend preview failed: %s", result.stderr[-2000:])
        raise HTTPException(500, "Could not build the preview.")
    return FileResponse(
        path,
        media_type="audio/flac",
        filename="preview.flac",
        background=BackgroundTask(shutil.rmtree, scratch, ignore_errors=True),
    )


@router.get("/jobs/{job_id}/download")
def download(job_id: UUID, format: ExportFormat | None = None):
    row = require_job(job_id)
    if row["status"] != "completed":
        raise HTTPException(409, "Stems are not ready.")
    folder = settings.data_dir / str(job_id)
    path = folder / "stems.zip"
    if not path.is_file():
        raise HTTPException(404, "Archive not found.")
    name = f"{Path(row['filename']).stem}-stems.zip"
    if format is None:
        return FileResponse(path, media_type="application/zip", filename=name)
    plan = output_plan(row["mode"], row["keep"])
    sources = [stem_file(folder / "stems", output["id"]) for output in plan]
    if None in sources:
        raise HTTPException(404, "Audio file not found.")
    if {source.suffix for source in sources} == {exports.SUFFIX[format]}:
        return FileResponse(path, media_type="application/zip", filename=name)
    scratch = export_scratch(folder)
    try:
        archive = scratch / name
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            for output, source in zip(plan, sources, strict=True):
                target = scratch / f"{output['id']}{exports.SUFFIX[format]}"
                convert_or_fail(source, format, target, row, output["id"])
                bundle.write(target, target.name)
                target.unlink()
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=name,
        background=BackgroundTask(shutil.rmtree, scratch, ignore_errors=True),
    )


ANALYSIS_STAGES = frozenset(
    {
        "Checking the file",
        "Reading tempo and key",
        "Waiting for the separator",
        "Isolating drums and bass",
        "Tracking the beat",
        "Isolating the harmony",
    }
)
READING_FIELDS = ("bpm", "camelot", "key_name", "downbeat", "warning")


def analysis_interpreter():
    """The Python the analysis and extend children run in: the checkout's own environment when it
    has one, otherwise the one running this server (an installed app has no `.venv` beside it)."""
    checkout = venv_python(Path(__file__).resolve().parents[2] / ".venv")
    return checkout if checkout.is_file() else Path(sys.executable)


def analysis_dir(analysis_id):
    return settings.data_dir / "analyses" / analysis_id


def analysis_source(analysis_id, filename):
    return analysis_dir(analysis_id) / f"source{jobs.input_suffix(filename)}"


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


def playlist_fields(payload):
    """A reading plus its mood, for the playlist; the Load step stores only the reading."""
    return {
        **reading_fields(payload),
        **{
            name: None if payload.get(name) is None else round(float(payload[name]), 3)
            for name in ("valence", "energy")
        },
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
    """Stream a raw WAV, MP3 or FLAC and measure tempo and key in a child process."""
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


# The Playlist booth reads WAV and MP3 folders; FLAC is accepted as an upload only.
_AUDIO_SUFFIXES = {".wav", ".mp3"}
# The separator lock is exclusive, so only one analysis child may run.
_playlist_child = threading.Lock()
_playlist_scans = {}
_playlist_scans_lock = threading.Lock()


class _PlaylistScanCancelled(Exception):
    pass


class PlaylistScanRequest(BaseModel):
    path: str


class PlaylistOrderTrack(BaseModel):
    path: str
    filename: str
    bpm: float | None = None
    camelot: str | None = None
    key_name: str | None = None
    warning: str | None = None
    valence: float | None = None
    energy: float | None = None


class PlaylistOrderRequest(BaseModel):
    tracks: list[PlaylistOrderTrack]
    pinned: str | None = None
    held: list[str] = []


def _resolved_directory(raw):
    requested = Path(raw)
    if not requested.is_absolute():
        raise HTTPException(404, "Folder not found.")
    try:
        folder = requested.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(404, "Folder not found.") from exc
    if not folder.is_dir():
        raise HTTPException(422, "Choose a folder.")
    return folder


def _child_directories(folder):
    names = []
    try:
        entries = list(folder.iterdir())
    except OSError as exc:
        raise HTTPException(403, "Cannot read this folder.") from exc
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                names.append(entry.name)
        except OSError:
            continue
    names.sort(key=str.lower)
    return [{"name": name} for name in names]


def _playlist_audio(folder):
    """Top-level wav and mp3 files. A symlink counts only when it stays in this folder."""
    chosen = []
    seen = set()
    try:
        entries = list(folder.iterdir())
    except OSError as exc:
        raise HTTPException(403, "Cannot read this folder.") from exc
    for entry in entries:
        if entry.name.startswith(".") or entry.suffix.lower() not in _AUDIO_SUFFIXES:
            continue
        try:
            if entry.is_dir():
                continue
            resolved = entry.resolve(strict=True)
        except OSError:
            continue
        if resolved.suffix.lower() not in _AUDIO_SUFFIXES or not resolved.is_file():
            continue
        if resolved.parent != folder:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(resolved)
    chosen.sort(key=lambda path: path.name.lower())
    return chosen


def _playback_file(raw):
    """A resolved wav or mp3 that is still a direct child of its parent directory."""
    requested = Path(raw)
    if not requested.is_absolute():
        raise HTTPException(404, "Audio file not found.")
    try:
        parent = requested.parent.resolve(strict=True)
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(404, "Audio file not found.") from exc
    if resolved.suffix.lower() not in _AUDIO_SUFFIXES or not resolved.is_file():
        raise HTTPException(404, "Audio file not found.")
    if resolved.parent != parent:
        raise HTTPException(404, "Audio file not found.")
    direct = parent / resolved.name
    try:
        if not direct.is_file() or direct.resolve() != resolved:
            raise HTTPException(404, "Audio file not found.")
    except OSError as exc:
        raise HTTPException(404, "Audio file not found.") from exc
    return resolved


def _remember_scan(scan):
    with _playlist_scans_lock:
        _playlist_scans[scan["id"]] = scan


def _require_scan(scan_id):
    with _playlist_scans_lock:
        scan = _playlist_scans.get(scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found.")
    return scan


def _present_scan(scan, *, started=False):
    with scan["lock"]:
        body = {
            "id": scan["id"],
            "status": scan["status"],
            "done": scan["done"],
            "total": scan["total"],
        }
        if started:
            return body
        body["current"] = scan["current"]
        if scan["status"] == "completed":
            body["tracks"] = list(scan["tracks"])
            body["unread"] = list(scan["unread"])
        else:
            body["tracks"] = []
            body["unread"] = []
        return body


def _stop_child(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_analysis_child(source, scan):
    """One python -m stemlab.analysis on the file in place. The caller holds the child lock."""
    folder = settings.data_dir / "playlist" / scan["id"]
    folder.mkdir(parents=True, exist_ok=True)
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
            with scan["lock"]:
                scan["process"] = process
            started = time.monotonic()
            while process.poll() is None:
                if scan["cancel"].is_set():
                    _stop_child(process)
                    raise _PlaylistScanCancelled()
                if time.monotonic() - started > settings.job_timeout_seconds:
                    _stop_child(process)
                    raise TimeoutError("Analysis exceeded the configured time limit.")
                time.sleep(0.2)
        if scan["cancel"].is_set():
            raise _PlaylistScanCancelled()
        if process.returncode:
            raise RuntimeError(analysis_error(stderr_path))
        try:
            return playlist_fields(json.loads(stdout_path.read_text()))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Analysis returned an unreadable result.") from exc
    finally:
        with scan["lock"]:
            scan["process"] = None
        if process is not None and process.poll() is None:
            _stop_child(process)


def _measure_file(source, scan):
    stat = source.stat()
    cached = jobs.get_reading(str(source), stat.st_size, stat.st_mtime_ns)
    if cached is not None:
        return playlist_fields(cached)
    with _playlist_child:
        if scan["cancel"].is_set():
            raise _PlaylistScanCancelled()
        fields = _run_analysis_child(source, scan)
    jobs.save_reading(str(source), stat.st_size, stat.st_mtime_ns, fields)
    return fields


def _playlist_row(path, fields):
    record = {"path": str(path), "filename": path.name}
    if fields["bpm"] is None or not fields["camelot"]:
        return None, {**record, "reason": fields["warning"] or "No BPM or Camelot."}
    return {
        **record,
        "bpm": fields["bpm"],
        "camelot": fields["camelot"],
        "key_name": fields["key_name"],
        "warning": fields["warning"] or "",
        "valence": fields["valence"],
        "energy": fields["energy"],
    }, None


def _follow_scan(scan, files):
    tracks = []
    unread = []
    try:
        for path in files:
            if scan["cancel"].is_set():
                raise _PlaylistScanCancelled()
            with scan["lock"]:
                scan["current"] = path.name
            track, missing = _playlist_row(path, _measure_file(path, scan))
            if track is not None:
                tracks.append(track)
            else:
                unread.append(missing)
            with scan["lock"]:
                scan["done"] += 1
        if scan["cancel"].is_set():
            raise _PlaylistScanCancelled()
        with scan["lock"]:
            scan["tracks"] = tracks
            scan["unread"] = unread
            scan["current"] = None
            scan["status"] = "completed"
    except _PlaylistScanCancelled:
        with scan["lock"]:
            scan["status"] = "cancelled"
            scan["current"] = None
    except Exception:
        logging.exception("Playlist scan failed for %s", scan["id"])
        with scan["lock"]:
            if scan["cancel"].is_set():
                scan["status"] = "cancelled"
            else:
                scan["status"] = "failed"
            scan["current"] = None
    finally:
        shutil.rmtree(settings.data_dir / "playlist" / scan["id"], ignore_errors=True)


def _readable_tracks(body):
    held = set(body.held)
    readable = []
    for track in body.tracks:
        if track.path in held or track.bpm is None or not track.camelot:
            continue
        readable.append(
            {
                "path": track.path,
                "filename": track.filename,
                "bpm": track.bpm,
                "camelot": track.camelot,
                "key_name": track.key_name,
                "valence": track.valence,
                "energy": track.energy,
            }
        )
    return readable


def _display_failed(stderr):
    text = (stderr or "").lower()
    return (
        "cannot open display" in text
        or "could not connect" in text
        or "unable to init server" in text
    )


def _graphical_directory(argv):
    """A chosen path, '' when the dialog is cancelled, or None when it cannot open."""
    try:
        completed = subprocess.run(argv, capture_output=True, text=True)
    except OSError:
        return None
    if completed.returncode == 0:
        return completed.stdout.strip()
    if completed.returncode == 1 and not _display_failed(completed.stderr):
        return ""
    return None


def _tk_directory():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        return filedialog.askdirectory(title="Choose a folder") or ""
    finally:
        root.destroy()


def pick_directory():
    """First dialog that can open. '' means the person cancelled."""
    zenity = shutil.which("zenity")
    if zenity:
        chosen = _graphical_directory(
            [zenity, "--file-selection", "--directory", "--title=Choose a folder"]
        )
        if chosen is not None:
            return chosen
    kdialog = shutil.which("kdialog")
    if kdialog:
        start = str(Path.home()) if Path.home().is_dir() else "/"
        chosen = _graphical_directory(
            [kdialog, "--getexistingdirectory", start, "--title", "Choose a folder"]
        )
        if chosen is not None:
            return chosen
    try:
        return _tk_directory()
    except Exception as exc:
        raise HTTPException(503, "No folder dialog is available.") from exc


@router.post("/playlist/pick")
def playlist_pick():
    chosen = pick_directory()
    if not chosen:
        return {"cancelled": True}
    folder = _resolved_directory(chosen)
    return {
        "cancelled": False,
        "path": str(folder),
        "name": folder.name or str(folder),
    }


@router.get("/playlist/browse")
def playlist_browse(path: str = Query(min_length=1)):
    folder = _resolved_directory(path)
    parent = None if folder.parent == folder else str(folder.parent)
    return {"path": str(folder), "parent": parent, "directories": _child_directories(folder)}


@router.post("/playlist/scans", status_code=202)
def start_playlist_scan(body: PlaylistScanRequest):
    folder = _resolved_directory(body.path)
    files = _playlist_audio(folder)
    scan = {
        "id": str(uuid4()),
        "status": "running",
        "done": 0,
        "total": len(files),
        "current": None,
        "tracks": [],
        "unread": [],
        "cancel": threading.Event(),
        "process": None,
        "lock": threading.Lock(),
    }
    _remember_scan(scan)
    payload = _present_scan(scan, started=True)
    threading.Thread(
        target=_follow_scan,
        args=(scan, files),
        name=f"playlist-{scan['id']}",
        daemon=True,
    ).start()
    return payload


@router.get("/playlist/scans/{scan_id}")
def playlist_scan(scan_id: UUID):
    return _present_scan(_require_scan(str(scan_id)))


@router.delete("/playlist/scans/{scan_id}")
def cancel_playlist_scan(scan_id: UUID):
    scan = _require_scan(str(scan_id))
    with scan["lock"]:
        process = scan["process"] if scan["status"] == "running" else None
        if scan["status"] == "running":
            scan["cancel"].set()
    _stop_child(process)
    return _present_scan(scan)


@router.post("/playlist/order")
def playlist_order(body: PlaylistOrderRequest):
    # Local import: ordering lives in playlist.py and is not required to boot the API.
    from stemlab.playlist import order_tracks

    return {"order": order_tracks(_readable_tracks(body), pinned=body.pinned)}


@router.get("/playlist/audio")
def playlist_audio(path: str = Query(min_length=1)):
    resolved = _playback_file(path)
    return FileResponse(
        resolved,
        media_type=exports.MEDIA_TYPES[resolved.suffix.lower()],
        filename=resolved.name,
    )
