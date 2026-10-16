"""FastAPI application: HTTP surface for the downloader."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from arq import create_pool
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import settings
from .downloader import probe_info
from .history import delete_entry, init_db, list_recent, record_job
from .models import (
    DownloadRequest,
    DownloadResponse,
    InfoResponse,
    JobState,
    JobStatus,
    StatusResponse,
    ThemeInfo,
)
from .platforms import detect_platform, platform_catalog, platform_for_subdomain
from .rate_limit import check_rate_limit
from .storage import load_job, save_job
from .themes import theme_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    app.state.redis = await create_pool(settings.redis_settings)
    await init_db()
    logger.info("connected to redis at %s:%s", settings.redis_host, settings.redis_port)
    yield
    await app.state.redis.close()


app = FastAPI(
    title="yt-downloader",
    version="2.0.0",
    description="Multi-platform video and audio downloader.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def platform_subdomain_middleware(request: Request, call_next):
    """Record which platform subdomain served the request.

    Purely informational: it sets `request.state.subdomain_platform` so handlers
    can default to the subdomain's platform, and logs the mapping. It never
    grants access; the URL allowlist in DownloadRequest is the authority.
    """
    platform = platform_for_subdomain(request.headers.get("host", ""))
    request.state.subdomain_platform = platform
    if platform is not None and request.url.path.startswith("/api/"):
        logger.debug("subdomain=%s path=%s", platform.key, request.url.path)
    return await call_next(request)


def _redis(request: Request):
    return request.app.state.redis


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/api/platforms")
async def list_platforms() -> dict:
    """Describe the supported platforms and their options."""
    return {"platforms": platform_catalog()}


@app.get("/api/themes", response_model=ThemeInfo)
async def list_themes() -> ThemeInfo:
    """Describe the selectable accent palettes.

    Selection itself is per-browser: the frontend stores the chosen key in
    localStorage and applies it via the [data-theme] attribute, because there
    are no user accounts to hang a server-side preference on.
    """
    return theme_catalog()


@app.post(
    "/api/download",
    response_model=DownloadResponse,
    dependencies=[Depends(check_rate_limit)],
)
async def create_download(payload: DownloadRequest, request: Request) -> DownloadResponse:
    """Validate the request, persist a job record, and enqueue the work."""
    redis = _redis(request)
    platform = detect_platform(payload.url)
    platform_key = platform.key if platform else "youtube"
    task_id = uuid.uuid4().hex
    job = JobState(
        task_id=task_id,
        url=payload.url,
        platform=platform_key,
        mode=payload.mode,
        quality=payload.quality,
        audio_format=payload.audio_format if payload.mode == "audio" else None,
        status=JobStatus.QUEUED,
    )
    await save_job(redis, job)
    await record_job(job)
    await redis.enqueue_job(
        "download_task",
        task_id,
        payload.url,
        payload.mode,
        payload.quality,
        payload.audio_format,
        platform_key,
        payload.playlist,
        payload.subtitles,
        payload.audio_quality,
    )
    logger.info(
        "queued job %s (%s %s %s)", task_id, platform_key, payload.mode, payload.quality
    )
    return DownloadResponse(task_id=task_id, status=JobStatus.QUEUED)


@app.get("/api/history")
async def get_history(limit: int = 50, platform: str | None = None) -> dict:
    """Recent downloads, newest first. Survives the Redis TTL."""
    limit = max(1, min(limit, 200))
    return {"entries": await list_recent(limit=limit, platform=platform)}


@app.delete("/api/history/{task_id}")
async def delete_history(task_id: str) -> dict:
    await delete_entry(task_id)
    return {"deleted": task_id}


@app.get("/api/status/{task_id}", response_model=StatusResponse)
async def get_status(task_id: str, request: Request) -> StatusResponse:
    job = await load_job(_redis(request), task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown task id")
    return StatusResponse(
        task_id=job.task_id,
        platform=job.platform,
        status=job.status,
        progress=job.progress,
        speed=job.speed,
        eta=job.eta,
        title=job.title,
        filesize=job.filesize,
        error=job.error,
    )


@app.get("/api/file/{task_id}")
async def get_file(task_id: str, request: Request):
    job = await load_job(_redis(request), task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown task id")
    if job.status != JobStatus.COMPLETE or not job.filename:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not complete")

    path = settings.download_dir / job.filename
    # Guard against a crafted filename escaping the download directory.
    if not path.resolve().is_relative_to(settings.download_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not path.exists():
        raise HTTPException(status_code=410, detail="File has expired and been cleaned up")

    return FileResponse(
        path,
        filename=job.filename,
        media_type="application/octet-stream",
    )


@app.websocket("/ws/progress/{task_id}")
async def ws_progress(websocket: WebSocket, task_id: str):
    """Stream job progress over a WebSocket.

    The client polls Redis on the server side instead of the browser polling
    HTTP, which removes the request overhead of a status loop. The connection
    closes once the job reaches a terminal state.
    """
    await websocket.accept()
    redis = websocket.app.state.redis

    terminal = {JobStatus.COMPLETE, JobStatus.FAILED}
    try:
        for _ in range(settings.ws_max_updates):
            job = await load_job(redis, task_id)
            if job is None:
                await websocket.send_json({"error": "unknown task id"})
                break

            await websocket.send_json(
                {
                    "task_id": job.task_id,
                    "platform": job.platform,
                    "status": job.status.value,
                    "progress": job.progress,
                    "speed": job.speed,
                    "eta": job.eta,
                    "title": job.title,
                    "filesize": job.filesize,
                    "error": job.error,
                }
            )
            if job.status in terminal:
                break
            await asyncio.sleep(settings.ws_poll_interval)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001 - never leak a traceback to the client
        logger.warning("websocket closed unexpectedly for %s", task_id, exc_info=True)
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass


@app.get(
    "/api/info",
    response_model=InfoResponse,
    dependencies=[Depends(check_rate_limit)],
)
async def get_info(url: str) -> InfoResponse:
    """Metadata preview. Never raises for a bad URL; returns an empty payload.

    The URL is put through the same platform allowlist as /api/download before
    it reaches yt-dlp. Without that check a caller could hand yt-dlp any host —
    including loopback and link-local addresses — and read the response back
    through `webpage_url`, turning this into an SSRF probe.
    """
    if detect_platform(url) is None:
        raise HTTPException(status_code=422, detail="Could not read metadata for that URL")
    data = await probe_info(url)
    if not data:
        raise HTTPException(status_code=422, detail="Could not read metadata for that URL")
    duration = data.get("duration")
    # Reject here so the UI can explain the limit up front instead of queueing a
    # job that the worker will discard. A missing duration passes, matching the
    # optional-match filter the download itself uses.
    if isinstance(duration, (int, float)) and duration > settings.max_duration_seconds:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Video is {int(duration)}s long; the limit is "
                f"{settings.max_duration_seconds}s"
            ),
        )
    heights = sorted(
        {
            f["height"]
            for f in data.get("formats", [])
            if f.get("height") and f.get("vcodec") not in (None, "none")
        }
    )
    return InfoResponse(
        title=data.get("title"),
        uploader=data.get("uploader"),
        duration=data.get("duration"),
        thumbnail=data.get("thumbnail"),
        webpage_url=data.get("webpage_url"),
        formats_available=[f"{h}p" for h in heights],
    )
