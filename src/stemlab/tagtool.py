"""Copy the tags and cover of one song onto another file, from the Tags booth.

A file is named by a reference: "job:<id>:<stem>" for the original or an output of a job in the
crate, or "file:<id>" for one uploaded here. The target is never changed: the result is a copy.
"""

import logging
import shutil
import time
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from stemlab import exports, jobs, tags
from stemlab.config import settings
from stemlab.outputs import output_plan, stem_file
from stemlab.routes import require_job, upload_limit, write_upload

router = APIRouter(prefix="/api/tags")
# Uploaded files wait here only long enough to be used.
KEEP_SECONDS = 3600


def workspace():
    return settings.data_dir / "tagtool"


def sweep():
    """Remove uploads and results nobody came back for."""
    folder = workspace()
    if not folder.is_dir():
        return
    for path in folder.iterdir():
        if path.is_dir() and time.time() - path.stat().st_mtime > KEEP_SECONDS:
            shutil.rmtree(path, ignore_errors=True)


class Reference:
    """A file a reference names: its path, a name to show, and the version it is, if any."""

    def __init__(self, path, name, version=None, row=None):
        self.path, self.name, self.version, self.row = path, name, version, row


def resolve(ref):
    kind, _, rest = ref.partition(":")
    try:
        if kind == "file":
            folder = workspace() / str(UUID(rest))
            path = next(folder.glob("file.*"), None)
            if path is None:
                raise HTTPException(404, "That file is gone. Choose it again.")
            return Reference(path, (folder / "name.txt").read_text(), None)
        if kind == "job":
            job_id, _, stem = rest.partition(":")
            row = require_job(UUID(job_id))
    except ValueError as exc:
        raise HTTPException(422, "Unknown file.") from exc
    if kind != "job":
        raise HTTPException(422, "Unknown file.")
    if stem == "original":
        if not jobs.has_source(row):
            raise HTTPException(404, "This track has no original upload.")
        return Reference(jobs.source_path(row), row["filename"], None, row)
    if stem not in {output["id"] for output in output_plan(row["mode"], row["keep"])}:
        raise HTTPException(404, "Unknown output.")
    path = stem_file(settings.data_dir / row["id"] / "stems", stem)
    if row["status"] != "completed" or path is None:
        raise HTTPException(409, "That output is not ready.")
    name = f"{Path(row['filename']).stem}-{stem}{path.suffix}"
    return Reference(path, name, tags.VERSION_NAMES.get(stem), row)


def require_ffmpeg():
    if not tags.available():
        raise HTTPException(503, "Copying tags needs ffmpeg and ffprobe installed on the server.")


@router.post("/files", status_code=201)
async def stage(request: Request, filename: str = Query(min_length=1, max_length=240)):
    """Receive one MP3, FLAC or WAV, recognized by its content and not by its name."""
    require_ffmpeg()
    limit = upload_limit(request)
    await run_in_threadpool(sweep)
    ident = uuid4()
    folder = workspace() / str(ident)
    folder.mkdir(parents=True)
    raw = folder / "file.upload"
    try:
        await write_upload(request, raw, limit)
        found = await run_in_threadpool(tags.read, raw)
        if found["container"] is None:
            raise HTTPException(422, "Choose an MP3, FLAC or WAV file.")
        raw.rename(folder / f"file{found['container']}")
        (folder / "name.txt").write_text(filename.replace("\\", "/").split("/")[-1])
    except tags.TagError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, str(exc)) from exc
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {"ref": f"file:{ident}", "name": (folder / "name.txt").read_text()}


@router.get("")
def show(ref: str = Query(max_length=120)):
    """What the file carries: its tags and cover, and the version name it would get."""
    require_ffmpeg()
    found = resolve(ref)
    try:
        info = tags.read(found.path)
    except tags.TagError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"name": found.name, "version": found.version, **info}


@router.get("/cover")
def cover(ref: str = Query(max_length=120)):
    require_ffmpeg()
    found = resolve(ref)
    scratch = workspace() / "scratch" / uuid4().hex
    scratch.mkdir(parents=True)
    image = scratch / "cover.png"
    if not tags.extract_cover(found.path, image):
        shutil.rmtree(scratch, ignore_errors=True)
        raise HTTPException(404, "This file has no cover.")
    return FileResponse(
        image, media_type="image/png", background=BackgroundTask(shutil.rmtree, scratch, True)
    )


class CopyRequest(BaseModel):
    source: str
    target: str
    # What this version is, added to the title: None takes the target's own (an output's name),
    # an empty string adds nothing.
    version: str | None = None
    cover: bool = True


@router.post("/copy")
def copy(body: CopyRequest):
    """A copy of the target with the source's tags and cover. Neither original is touched."""
    require_ffmpeg()
    source, target = resolve(body.source), resolve(body.target)
    version = target.version if body.version is None else (body.version.strip() or None)
    tempo = None
    if target.row is not None:
        tempo = {"bpm": target.row.get("bpm"), "key": tags.key_tag(target.row.get("key_name"))}
    scratch = workspace() / "scratch" / uuid4().hex
    scratch.mkdir(parents=True)
    name = f"{Path(target.name).stem}{target.path.suffix}"
    result = scratch / name
    try:
        shutil.copyfile(target.path, result)
        tags.copy(
            source.path,
            result,
            version=version,
            tempo=tempo,
            cover=body.cover,
            fallback_title=Path(source.name).stem,
        )
    except tags.TagError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        logging.exception("Copying tags failed")
        raise
    return FileResponse(
        result,
        media_type=exports.MEDIA_TYPES[result.suffix.lower()],
        filename=name,
        background=BackgroundTask(shutil.rmtree, scratch, True),
    )
