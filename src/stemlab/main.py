from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from redis import Redis
from redis.exceptions import RedisError

from stemlab.config import settings
from stemlab.routes import router

app = FastAPI(title="StemLab", version="1.0.0", description="Local WAV/MP3 separation and mixing")
app.include_router(router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web"), name="static")


@app.middleware("http")
async def local_write_protection(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host')}"
        if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403)
    return await call_next(request)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(Path(__file__).parent / "web" / "index.html")


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    """Check the broker; worker health is monitored separately by Compose."""
    if settings.queue_mode == "local":
        from stemlab import jobs

        with jobs.database() as db:
            db.execute("SELECT 1")
        return {"status": "ok", "queue": "local"}
    try:
        with Redis.from_url(
            settings.broker_url, socket_connect_timeout=2, socket_timeout=2
        ) as client:
            client.ping()
    except RedisError:
        return JSONResponse(status_code=503, content={"status": "unavailable", "queue": "down"})
    return {"status": "ok", "queue": "up"}
