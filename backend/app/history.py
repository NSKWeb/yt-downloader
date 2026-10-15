"""Download history, persisted to SQLite.

Uses the stdlib sqlite3 driver off the event loop via asyncio.to_thread, so no
extra dependency is needed and a slow disk never blocks a request. Redis remains
the source of truth for live job state; this table is the durable record that
outlives the 24-hour Redis TTL.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    task_id     TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    platform    TEXT NOT NULL,
    mode        TEXT NOT NULL,
    quality     TEXT,
    audio_format TEXT,
    status      TEXT NOT NULL,
    title       TEXT,
    filename    TEXT,
    filesize    INTEGER,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_downloads_platform ON downloads(platform);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL keeps readers from blocking the writer while downloads are recorded.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _upsert(path: Path, record: dict) -> None:
    conn = _connect(path)
    try:
        conn.execute(
            """
            INSERT INTO downloads (
                task_id, url, platform, mode, quality, audio_format, status,
                title, filename, filesize, error, created_at, updated_at
            ) VALUES (
                :task_id, :url, :platform, :mode, :quality, :audio_format, :status,
                :title, :filename, :filesize, :error, :created_at, :updated_at
            )
            ON CONFLICT(task_id) DO UPDATE SET
                status=excluded.status,
                title=excluded.title,
                filename=excluded.filename,
                filesize=excluded.filesize,
                error=excluded.error,
                updated_at=excluded.updated_at
            """,
            record,
        )
        conn.commit()
    finally:
        conn.close()


def _list_recent(path: Path, limit: int, platform: str | None) -> list[dict]:
    conn = _connect(path)
    try:
        if platform:
            rows = conn.execute(
                "SELECT * FROM downloads WHERE platform = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (platform, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _delete(path: Path, task_id: str) -> None:
    conn = _connect(path)
    try:
        conn.execute("DELETE FROM downloads WHERE task_id = ?", (task_id,))
        conn.commit()
    finally:
        conn.close()


async def init_db() -> None:
    if not settings.history_enabled:
        return
    try:
        await asyncio.to_thread(_init_db, settings.history_db_path)
        logger.info("history database ready at %s", settings.history_db_path)
    except Exception:  # noqa: BLE001 - history is non-critical
        logger.warning("could not initialise history database", exc_info=True)


async def record_job(job) -> None:
    """Persist a JobState. Never raises: history must not break a download."""
    if not settings.history_enabled:
        return
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "task_id": job.task_id,
        "url": job.url,
        "platform": job.platform,
        "mode": job.mode,
        "quality": job.quality,
        "audio_format": job.audio_format,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "title": job.title,
        "filename": job.filename,
        "filesize": job.filesize,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else now,
        "updated_at": now,
    }
    try:
        await asyncio.to_thread(_upsert, settings.history_db_path, record)
    except Exception:  # noqa: BLE001
        logger.warning("could not record job %s in history", job.task_id, exc_info=True)


async def list_recent(limit: int = 50, platform: str | None = None) -> list[dict]:
    if not settings.history_enabled:
        return []
    try:
        return await asyncio.to_thread(_list_recent, settings.history_db_path, limit, platform)
    except Exception:  # noqa: BLE001
        logger.warning("could not read history", exc_info=True)
        return []


async def delete_entry(task_id: str) -> None:
    if not settings.history_enabled:
        return
    try:
        await asyncio.to_thread(_delete, settings.history_db_path, task_id)
    except Exception:  # noqa: BLE001
        logger.warning("could not delete history entry %s", task_id, exc_info=True)
