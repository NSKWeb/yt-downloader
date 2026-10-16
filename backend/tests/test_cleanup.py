"""Tests for the worker's expired-file cleanup."""

import os
import time

import pytest

from app.config import settings
from app.workers.tasks import cleanup_expired_files


@pytest.fixture
def download_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "download_dir", tmp_path)
    return tmp_path


def _make(path, age_seconds):
    path.write_bytes(b"x")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


async def test_removes_only_expired_files(download_dir, monkeypatch):
    monkeypatch.setattr(settings, "file_ttl_seconds", 3600)

    old = _make(download_dir / "old.mp4", age_seconds=7200)
    fresh = _make(download_dir / "fresh.mp4", age_seconds=60)

    removed = await cleanup_expired_files({})

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


async def test_returns_zero_on_empty_dir(download_dir):
    assert await cleanup_expired_files({}) == 0


async def test_missing_dir_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "download_dir", tmp_path / "does-not-exist")
    assert await cleanup_expired_files({}) == 0


async def test_leaves_directories_alone(download_dir, monkeypatch):
    monkeypatch.setattr(settings, "file_ttl_seconds", 0)
    nested = download_dir / "subdir"
    nested.mkdir()

    await cleanup_expired_files({})

    assert nested.exists()


async def test_preserves_the_history_database(download_dir, monkeypatch):
    """history_db_path defaults to download_dir/history.db and is idle between
    jobs, so an unguarded sweep deletes the whole history after one TTL."""
    monkeypatch.setattr(settings, "file_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "database_path", None)

    db = _make(download_dir / "history.db", age_seconds=7200)
    media = _make(download_dir / "old.mp4", age_seconds=7200)

    removed = await cleanup_expired_files({})

    assert db.exists(), "cleanup must never delete the history database"
    assert not media.exists()
    assert removed == 1


async def test_preserves_history_wal_sidecars(download_dir, monkeypatch):
    monkeypatch.setattr(settings, "file_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "database_path", None)

    wal = _make(download_dir / "history.db-wal", age_seconds=7200)
    shm = _make(download_dir / "history.db-shm", age_seconds=7200)

    await cleanup_expired_files({})

    assert wal.exists()
    assert shm.exists()


async def test_honours_a_custom_database_path(download_dir, monkeypatch):
    """A database outside the download directory is untouched either way."""
    monkeypatch.setattr(settings, "file_ttl_seconds", 3600)
    custom = download_dir / "state" / "history.db"
    custom.parent.mkdir()
    custom.write_bytes(b"db")
    monkeypatch.setattr(settings, "database_path", custom)

    # A same-named file in download_dir is not the configured database.
    decoy = _make(download_dir / "history.db", age_seconds=7200)

    await cleanup_expired_files({})

    assert custom.exists()
    assert not decoy.exists()
