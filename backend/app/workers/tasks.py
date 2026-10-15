"""ARQ worker: pulls download jobs off the queue and runs them.

Run with:  arq app.workers.tasks.WorkerSettings
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from arq import cron

from ..config import settings
from ..downloader import run_download
from ..models import JobStatus
from ..storage import load_job, save_job, update_job

logger = logging.getLogger(__name__)


async def download_task(
    ctx: dict,
    task_id: str,
    url: str,
    mode: str,
    quality: str,
    audio_format: str,
) -> None:
    """Download one URL and keep the job record updated throughout."""
    redis = ctx["redis"]
    job = await load_job(redis, task_id)
    if job is None:
        logger.warning("job %s vanished before it started", task_id)
        return

    job.status = JobStatus.DOWNLOADING
    job.updated_at = datetime.now(timezone.utc)
    await save_job(redis, job)

    async def on_progress(data: dict) -> None:
        await update_job(
            redis,
            task_id,
            progress=data.get("percent", 0.0),
            speed=data.get("speed"),
            eta=data.get("eta"),
        )

    try:
        path = await run_download(
            url=url,
            mode=mode,
            quality=quality,
            audio_format=audio_format,
            output_dir=settings.download_dir,
            on_progress=on_progress,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as-is
        logger.exception("download failed for %s", task_id)
        await _finish(redis, task_id, status=JobStatus.FAILED, error=str(exc)[:500])
        return

    size = path.stat().st_size if path.exists() else None
    await _finish(
        redis,
        task_id,
        status=JobStatus.COMPLETE,
        progress=100.0,
        filename=path.name,
        filesize=size,
    )
    logger.info("job %s complete: %s (%s bytes)", task_id, path.name, size)


async def _finish(redis, task_id: str, status: JobStatus, **fields) -> None:
    job = await load_job(redis, task_id)
    if job is None:
        return
    job.status = status
    for key, value in fields.items():
        setattr(job, key, value)
    job.updated_at = datetime.now(timezone.utc)
    await save_job(redis, job)


async def cleanup_expired_files(ctx: dict) -> int:
    """Delete files older than FILE_TTL_SECONDS. Runs hourly."""
    directory = settings.download_dir
    if not directory.exists():
        return 0

    cutoff = time.time() - settings.file_ttl_seconds
    removed = 0
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            logger.warning("could not remove %s", entry, exc_info=True)

    if removed:
        logger.info("cleanup removed %d expired file(s)", removed)
    return removed


class WorkerSettings:
    functions = [download_task]
    cron_jobs = [cron(cleanup_expired_files, minute=0)]
    redis_settings = settings.redis_settings
    max_jobs = settings.max_concurrent_jobs
    job_timeout = 60 * 60 * 2
    keep_result = 60 * 60 * 24
