"""Tests for the Redis-backed job store.

These use an in-process fake rather than a real Redis, matching the rest of the
suite. The fake is deliberately pessimistic: it tracks a version per key and
raises WatchError when a watched key changed before EXEC, so the retry loop in
`update_job` is exercised for real instead of being stubbed out.
"""

import asyncio

import pytest
from redis.exceptions import WatchError

from app import storage
from app.models import JobState, JobStatus


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self._watched: str | None = None
        self._watched_version: int | None = None
        self._queued: list[tuple] = []
        self._in_multi = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def watch(self, key):
        self._watched = key
        self._watched_version = self.redis.versions.get(key, 0)

    async def unwatch(self):
        self._watched = None
        self._watched_version = None

    async def get(self, key):
        # Yield so a concurrent writer can interleave between our read and our
        # write; without this the race would never be observed.
        await asyncio.sleep(0)
        return self.redis.store.get(key)

    def multi(self):
        self._in_multi = True

    def set(self, key, value, ex=None):
        self._queued.append(("set", key, value, ex))
        return self

    async def execute(self):
        if self._watched is not None:
            if self.redis.versions.get(self._watched, 0) != self._watched_version:
                raise WatchError("watched key changed")
        results = []
        for op, key, value, ex in self._queued:
            assert op == "set"
            self.redis.store[key] = value
            self.redis.versions[key] = self.redis.versions.get(key, 0) + 1
            results.append(True)
        self._queued.clear()
        self._watched = None
        self._in_multi = False
        return results


class FakeRedis:
    """Stands in for the ARQ redis pool; only the job-store calls are used."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.versions: dict[str, int] = {}
        self.conflicts = 0

    def pipeline(self):
        return _FakePipeline(self)

    async def set(self, key, value, ex=None):
        # Yield here too: a writer that reads, yields, and then writes is the
        # shape that loses data, so the fake must give the other writer a turn
        # between the read and the write.
        await asyncio.sleep(0)
        self.store[key] = value
        self.versions[key] = self.versions.get(key, 0) + 1

    async def get(self, key):
        # Yield so a concurrent writer can interleave between read and write.
        # Without this the pre-fix GET-then-SET never loses a field in-process,
        # and the regression test would pass against the buggy code.
        await asyncio.sleep(0)
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def redis():
    return FakeRedis()


def _job(task_id="t1", **over):
    job = JobState(task_id=task_id, url="https://youtu.be/x", mode="video", quality="best")
    for key, value in over.items():
        setattr(job, key, value)
    return job


class TestSaveAndLoad:
    @pytest.mark.asyncio
    async def test_roundtrip(self, redis):
        await storage.save_job(redis, _job())
        loaded = await storage.load_job(redis, "t1")
        assert loaded.task_id == "t1"
        assert loaded.status == JobStatus.QUEUED

    @pytest.mark.asyncio
    async def test_missing_key_is_none(self, redis):
        assert await storage.load_job(redis, "nope") is None


class TestUpdateJob:
    @pytest.mark.asyncio
    async def test_sets_fields_and_bumps_updated_at(self, redis):
        job = _job()
        await storage.save_job(redis, job)
        before = job.updated_at

        updated = await storage.update_job(redis, "t1", progress=42.0, title="hi")

        assert updated.progress == 42.0
        assert updated.title == "hi"
        assert updated.updated_at >= before

    @pytest.mark.asyncio
    async def test_missing_job_is_none(self, redis):
        assert await storage.update_job(redis, "nope", progress=1.0) is None

    @pytest.mark.asyncio
    async def test_concurrent_writers_do_not_lose_fields(self, redis):
        """The regression: a plain GET-then-SET dropped one writer's fields.

        Two writers touch disjoint fields, as the progress and metadata
        callbacks do. Both must survive.
        """
        await storage.save_job(redis, _job())

        async def writer_progress():
            for i in range(1, 21):
                await storage.update_job(redis, "t1", progress=float(i))

        async def writer_title():
            for i in range(1, 21):
                await storage.update_job(redis, "t1", title=f"title-{i}")

        await asyncio.gather(writer_progress(), writer_title())

        final = await storage.load_job(redis, "t1")
        assert final.progress == 20.0, "progress was clobbered by the other writer"
        assert final.title == "title-20", "title was clobbered by the other writer"

    @pytest.mark.asyncio
    async def test_retries_after_a_conflict(self, redis, monkeypatch):
        """A single lost race must be retried, not dropped."""
        await storage.save_job(redis, _job())
        real_execute = _FakePipeline.execute
        calls = {"n": 0}

        async def flaky_execute(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise WatchError("forced")
            return await real_execute(self)

        monkeypatch.setattr(_FakePipeline, "execute", flaky_execute)

        updated = await storage.update_job(redis, "t1", progress=7.0)

        assert updated.progress == 7.0
        assert calls["n"] == 2, "the conflict should have caused exactly one retry"
        assert (await storage.load_job(redis, "t1")).progress == 7.0

    @pytest.mark.asyncio
    async def test_gives_up_without_raising(self, redis, monkeypatch):
        """Exhausting the retry budget returns None rather than throwing."""

        async def always_conflict(self):
            raise WatchError("always")

        monkeypatch.setattr(_FakePipeline, "execute", always_conflict)
        await storage.save_job(redis, _job())

        assert await storage.update_job(redis, "t1", progress=1.0) is None
