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
    def __init__(self, host="1.2.3.4"):
        self.host = host


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
    def test_trusts_x_forwarded_for_from_a_proxy(self):
        # 203.0.113.7 is the real client; the private hop is our own nginx.
        req = FakeRequest(headers={"x-forwarded-for": "203.0.113.7, 172.18.0.5"})
        req.client = FakeClient(host="172.18.0.5")
        assert rate_limit.client_key(req) == "203.0.113.7"

    def test_falls_back_to_socket_address(self):
        assert rate_limit.client_key(FakeRequest()) == "1.2.3.4"

    def test_unknown_when_no_client(self):
        req = FakeRequest()
        req.client = None
        assert rate_limit.client_key(req) == "unknown"

    def test_ignores_spoofed_x_forwarded_for_from_untrusted_peer(self):
        """A direct caller must not be able to pick its own rate-limit bucket."""
        req = FakeRequest(headers={"x-forwarded-for": "9.9.9.9"})
        req.client = FakeClient(host="203.0.113.9")
        assert rate_limit.client_key(req) == "203.0.113.9"

    def test_spoofed_prefix_is_discarded_behind_a_proxy(self):
        """Only the hop our trusted proxy wrote counts, not the client's prefix."""
        req = FakeRequest(
            headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7, 10.0.0.9"}
        )
        req.client = FakeClient(host="10.0.0.9")
        assert rate_limit.client_key(req) == "203.0.113.7"

    def test_all_trusted_hops_fall_back_to_peer(self):
        req = FakeRequest(headers={"x-forwarded-for": "10.0.0.1, 10.0.0.2"})
        req.client = FakeClient(host="10.0.0.2")
        assert rate_limit.client_key(req) == "10.0.0.2"

    def test_configured_trusted_proxy_is_honoured(self, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxies", "198.51.100.0/24")
        req = FakeRequest(headers={"x-forwarded-for": "203.0.113.7"})
        req.client = FakeClient(host="198.51.100.4")
        assert rate_limit.client_key(req) == "203.0.113.7"


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

    # Reached through the same trusted proxy, but a different real client.
    other = FakeRequest(headers={"x-forwarded-for": "8.8.8.8"}, app=limited.app)
    other.client = FakeClient(host="10.0.0.1")
    await rate_limit.check_rate_limit(other)  # its own budget, must not raise
