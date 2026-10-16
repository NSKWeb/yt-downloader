"""ARQ worker: pulls download jobs off the queue and runs them.

Run with:  arq app.workers.tasks.WorkerSettings
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from arq import cron

from ..config import settings
from ..downloader import run_download
from ..history import init_db, record_job
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
    platform_key: str = "youtube",
    playlist: bool = False,
    subtitles: bool = False,
    audio_quality: str = "192",
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

    async def on_meta(data: dict) -> None:
        await update_job(
            redis,
            task_id,
            title=data.get("title"),
            filesize=data.get("filesize"),
        )

    try:
        path = await run_download(
            url=url,
            mode=mode,
            quality=quality,
            audio_format=audio_format,
            output_dir=settings.download_dir,
            on_progress=on_progress,
            on_meta=on_meta,
            platform_key=platform_key,
            playlist=playlist,
            subtitles=subtitles,
            audio_quality=audio_quality,
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
    # Mirror the terminal state into SQLite, which outlives the Redis TTL.
    await record_job(job)


async def cleanup_expired_files(ctx: dict) -> int:
    """Delete files older than FILE_TTL_SECONDS. Runs hourly."""
    directory = settings.download_dir
    if not directory.exists():
        return 0

    # The SQLite history database defaults to a path inside the download
    # directory and is idle whenever no job is running, so a naive sweep
    # deletes it after FILE_TTL_SECONDS and silently wipes the history.
    protected = {settings.history_db_path.resolve()}
    # WAL mode also keeps -wal and -shm siblings beside the database.
    protected |= {Path(f"{p}-wal") for p in protected}
    protected |= {Path(f"{p}-shm") for p in protected}

    cutoff = time.time() - settings.file_ttl_seconds
    removed = 0
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.resolve() in protected:
                continue
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

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        await init_db()
