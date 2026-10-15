"""FastAPI application: HTTP surface for the downloader."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from arq import create_pool
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import settings
from .downloader import probe_info
from .models import (
    DownloadRequest,
    DownloadResponse,
    InfoResponse,
    JobState,
    JobStatus,
    StatusResponse,
)
from .storage import load_job, save_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    app.state.redis = await create_pool(settings.redis_settings)
    logger.info("connected to redis at %s:%s", settings.redis_host, settings.redis_port)
    yield
    await app.state.redis.close()


app = FastAPI(
    title="yt-downloader",
    version="1.0.0",
    description="Fast YouTube video and audio downloader.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _redis(request: Request):
    return request.app.state.redis


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.post("/api/download", response_model=DownloadResponse)
async def create_download(payload: DownloadRequest, request: Request) -> DownloadResponse:
    """Validate the request, persist a job record, and enqueue the work."""
    redis = _redis(request)
    task_id = uuid.uuid4().hex
    job = JobState(
        task_id=task_id,
        url=payload.url,
        mode=payload.mode,
        quality=payload.quality,
        audio_format=payload.audio_format if payload.mode == "audio" else None,
        status=JobStatus.QUEUED,
    )
    await save_job(redis, job)
    await redis.enqueue_job(
        "download_task",
        task_id,
        payload.url,
        payload.mode,
        payload.quality,
        payload.audio_format,
    )
    logger.info("queued job %s (%s %s)", task_id, payload.mode, payload.quality)
    return DownloadResponse(task_id=task_id, status=JobStatus.QUEUED)


@app.get("/api/status/{task_id}", response_model=StatusResponse)
async def get_status(task_id: str, request: Request) -> StatusResponse:
    job = await load_job(_redis(request), task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown task id")
    return StatusResponse(
        task_id=job.task_id,
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


@app.get("/api/info", response_model=InfoResponse)
async def get_info(url: str) -> InfoResponse:
    """Metadata preview. Never raises for a bad URL; returns an empty payload."""
    data = await probe_info(url)
    if not data:
        raise HTTPException(status_code=422, detail="Could not read metadata for that URL")
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
