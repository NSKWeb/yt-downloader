"""Tests for the SQLite history store."""

from datetime import datetime, timedelta, timezone

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


class TestPruneHistory:
    """The table had no retention: every finished job appended a row forever."""

    async def _seed(self, count, *, age_days=0.0, prefix="t"):
        """Insert `count` rows, optionally backdated by `age_days`."""
        import sqlite3

        await history.init_db()
        base = datetime.now(timezone.utc) - timedelta(days=age_days)
        conn = sqlite3.connect(settings.history_db_path)
        try:
            for i in range(count):
                ts = (base + timedelta(seconds=i)).isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO downloads (task_id, url, platform, mode,"
                    " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (f"{prefix}{i}", "https://youtu.be/x", "youtube", "video", "complete", ts, ts),
                )
            conn.commit()
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_removes_rows_past_the_age_cap(self, temp_db, monkeypatch):
        monkeypatch.setattr(settings, "history_retention_days", 7)
        monkeypatch.setattr(settings, "history_max_rows", 0)
        await self._seed(3, age_days=30, prefix="old")
        await self._seed(2, age_days=0, prefix="new")

        removed = await history.prune_history()

        assert removed == 3
        entries = await history.list_recent()
        assert {e["task_id"] for e in entries} == {"new0", "new1"}

    @pytest.mark.asyncio
    async def test_row_cap_keeps_the_newest(self, temp_db, monkeypatch):
        monkeypatch.setattr(settings, "history_retention_days", 0)
        monkeypatch.setattr(settings, "history_max_rows", 5)
        await self._seed(12)

        removed = await history.prune_history()

        assert removed == 7
        entries = await history.list_recent(limit=100)
        assert len(entries) == 5
        # Newest-first ordering means t11..t7 survive.
        assert {e["task_id"] for e in entries} == {f"t{i}" for i in range(7, 12)}

    @pytest.mark.asyncio
    async def test_vacuum_reclaims_file_space(self, temp_db, monkeypatch):
        """DELETE alone leaves the pages in the file, so the size must drop."""
        monkeypatch.setattr(settings, "history_retention_days", 7)
        monkeypatch.setattr(settings, "history_max_rows", 0)
        await self._seed(400, age_days=30)
        size_before = settings.history_db_path.stat().st_size

        await history.prune_history()

        assert settings.history_db_path.stat().st_size < size_before

    @pytest.mark.asyncio
    async def test_noop_when_nothing_to_remove(self, temp_db, monkeypatch):
        monkeypatch.setattr(settings, "history_retention_days", 30)
        monkeypatch.setattr(settings, "history_max_rows", 100)
        await self._seed(3)

        assert await history.prune_history() == 0
        assert len(await history.list_recent()) == 3

    @pytest.mark.asyncio
    async def test_disabled_history_is_a_noop(self, temp_db, monkeypatch):
        monkeypatch.setattr(settings, "history_enabled", False)
        assert await history.prune_history() == 0
