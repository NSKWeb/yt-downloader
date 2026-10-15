"""Tests for the sliding-window rate limiter."""

import pytest
from fastapi import HTTPException

from app import rate_limit
from app.config import settings


class FakePipeline:
    """Executes the four commands _hit issues, against a plain dict store."""

    def __init__(self, store):
        self.store = store
        self.ops = []

    def zremrangebyscore(self, key, _min, max_score):
        self.ops.append(("trim", key, max_score))
        return self

    def zadd(self, key, mapping):
        self.ops.append(("add", key, mapping))
        return self

    def zcard(self, key):
        self.ops.append(("card", key))
        return self

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))
        return self

    async def execute(self):
        results = []
        for op in self.ops:
            if op[0] == "trim":
                _, key, cutoff = op
                entries = self.store.setdefault(key, {})
                for member in [m for m, s in entries.items() if s <= cutoff]:
                    del entries[member]
                results.append(None)
            elif op[0] == "add":
                _, key, mapping = op
                self.store.setdefault(key, {}).update(mapping)
                results.append(1)
            elif op[0] == "card":
                _, key = op
                results.append(len(self.store.get(key, {})))
            else:
                results.append(True)
        return results


class FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return FakePipeline(self.store)


class FakeClient:
    host = "1.2.3.4"


class FakeRequest:
    def __init__(self, headers=None, app=None):
        self.headers = headers or {}
        self.client = FakeClient()
        self.app = app


class FakeApp:
    def __init__(self, redis):
        self.state = type("S", (), {"redis": redis})()


@pytest.fixture
def limited(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "rate_limit_per_hour", 100)
    return FakeRequest(app=FakeApp(FakeRedis()))


class TestClientKey:
    def test_prefers_x_forwarded_for(self):
        req = FakeRequest(headers={"x-forwarded-for": "9.9.9.9, 10.0.0.1"})
        assert rate_limit.client_key(req) == "9.9.9.9"

    def test_falls_back_to_socket_address(self):
        assert rate_limit.client_key(FakeRequest()) == "1.2.3.4"

    def test_unknown_when_no_client(self):
        req = FakeRequest()
        req.client = None
        assert rate_limit.client_key(req) == "unknown"


@pytest.mark.asyncio
async def test_allows_up_to_the_limit(limited):
    for _ in range(3):
        await rate_limit.check_rate_limit(limited)  # must not raise


@pytest.mark.asyncio
async def test_blocks_past_the_limit(limited):
    for _ in range(3):
        await rate_limit.check_rate_limit(limited)
    with pytest.raises(HTTPException) as exc:
        await rate_limit.check_rate_limit(limited)
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_hourly_cap_blocks_independently(limited, monkeypatch):
    """A caller under the per-minute limit can still trip the hourly cap."""
    monkeypatch.setattr(settings, "rate_limit_per_hour", 2)
    for _ in range(2):
        await rate_limit.check_rate_limit(limited)
    with pytest.raises(HTTPException) as exc:
        await rate_limit.check_rate_limit(limited)
    assert exc.value.headers["Retry-After"] == "3600"


@pytest.mark.asyncio
async def test_disabled_limiter_never_raises(limited, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    for _ in range(50):
        await rate_limit.check_rate_limit(limited)


@pytest.mark.asyncio
async def test_fails_open_when_redis_is_down(monkeypatch):
    """A Redis outage must not lock every user out of the service."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)

    class Broken:
        def pipeline(self):
            raise ConnectionError("redis is down")

    req = FakeRequest(app=FakeApp(Broken()))
    await rate_limit.check_rate_limit(req)  # must not raise


@pytest.mark.asyncio
async def test_separate_clients_have_separate_budgets(limited, monkeypatch):
    for _ in range(3):
        await rate_limit.check_rate_limit(limited)

    other = FakeRequest(
        headers={"x-forwarded-for": "8.8.8.8"}, app=limited.app
    )
    await rate_limit.check_rate_limit(other)  # its own budget, must not raise
