"""Tests for the SQLite history store."""

import pytest

from app import history
from app.config import settings
from app.models import JobState, JobStatus


class FakeJob:
    """Minimal stand-in for JobState; record_job only reads attributes."""

    def __init__(self, task_id="abc123", **over):
        job = JobState(task_id=task_id, url="https://youtu.be/x", mode="video", quality="best")
        self.task_id = job.task_id
        self.url = job.url
        self.platform = job.platform
        self.mode = job.mode
        self.quality = job.quality
        self.audio_format = job.audio_format
        self.status = job.status
        self.title = job.title
        self.filename = job.filename
        self.filesize = job.filesize
        self.error = job.error
        self.created_at = job.created_at
        for key, value in over.items():
            setattr(self, key, value)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db = tmp_path / "history.db"
    monkeypatch.setattr(settings, "database_path", db)
    monkeypatch.setattr(settings, "history_enabled", True)
    return db


@pytest.mark.asyncio
async def test_record_then_list_roundtrip(temp_db):
    await history.init_db()
    await history.record_job(FakeJob(task_id="t1", platform="tiktok", quality="720p"))
    entries = await history.list_recent()
    assert len(entries) == 1
    assert entries[0]["task_id"] == "t1"
    assert entries[0]["platform"] == "tiktok"
    assert entries[0]["quality"] == "720p"


@pytest.mark.asyncio
async def test_record_is_an_upsert(temp_db):
    """The same task is written on queue and again on completion."""
    await history.init_db()
    await history.record_job(FakeJob(task_id="t1", status=JobStatus.QUEUED))
    await history.record_job(
        FakeJob(task_id="t1", status=JobStatus.COMPLETE, filename="v.mp4", filesize=99)
    )
    entries = await history.list_recent()
    assert len(entries) == 1, "a repeated task_id must update, not duplicate"
    assert entries[0]["status"] == "complete"
    assert entries[0]["filesize"] == 99
    assert entries[0]["filename"] == "v.mp4"


@pytest.mark.asyncio
async def test_filter_by_platform(temp_db):
    await history.init_db()
    await history.record_job(FakeJob(task_id="a", platform="youtube"))
    await history.record_job(FakeJob(task_id="b", platform="tiktok"))
    await history.record_job(FakeJob(task_id="c", platform="tiktok"))
    assert len(await history.list_recent()) == 3
    assert len(await history.list_recent(platform="tiktok")) == 2
    assert len(await history.list_recent(platform="youtube")) == 1


@pytest.mark.asyncio
async def test_newest_first(temp_db):
    await history.init_db()
    for i in range(3):
        await history.record_job(FakeJob(task_id=f"t{i}"))
    entries = await history.list_recent()
    assert [e["task_id"] for e in entries] == ["t2", "t1", "t0"]


@pytest.mark.asyncio
async def test_delete_entry(temp_db):
    await history.init_db()
    await history.record_job(FakeJob(task_id="t1"))
    await history.delete_entry("t1")
    assert await history.list_recent() == []


@pytest.mark.asyncio
async def test_disabled_history_is_a_noop(temp_db, monkeypatch):
    monkeypatch.setattr(settings, "history_enabled", False)
    await history.init_db()
    await history.record_job(FakeJob(task_id="t1"))
    assert await history.list_recent() == []


@pytest.mark.asyncio
async def test_bad_database_path_does_not_raise(tmp_path, monkeypatch):
    """History is non-critical: a broken path must never break a download."""
    monkeypatch.setattr(settings, "history_enabled", True)
    monkeypatch.setattr(settings, "database_path", tmp_path / "nope" / "deep" / "h.db")
    # Parent directories are created by init_db, so this should actually work.
    await history.init_db()
    await history.record_job(FakeJob(task_id="t1"))
    assert len(await history.list_recent()) == 1

    # A path that cannot be a database at all fails open: no exception, and
    # reads come back empty rather than crashing the endpoint.
    monkeypatch.setattr(settings, "database_path", tmp_path / "afile")
    (tmp_path / "afile").mkdir()
    await history.record_job(FakeJob(task_id="t2"))
    assert await history.list_recent() == []


def test_history_db_path_follows_download_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "download_dir", tmp_path)
    monkeypatch.setattr(settings, "database_path", None)
    assert settings.history_db_path == tmp_path / "history.db"

    explicit = tmp_path / "custom.db"
    monkeypatch.setattr(settings, "database_path", explicit)
    assert settings.history_db_path == explicit
