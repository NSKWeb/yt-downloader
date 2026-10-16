"""Sliding-window rate limiting backed by Redis.

Two windows are enforced: a per-minute burst limit and an hourly cap. Both use
a sorted set of request timestamps per client key, which gives an accurate
sliding window without the boundary spikes a fixed-window counter allows.

Keys expire on their own, so there is no cleanup job to run.
"""

from __future__ import annotations

import ipaddress
import logging
import time

from fastapi import HTTPException, Request, status

from .config import settings

logger = logging.getLogger(__name__)

# The default and most-specific private ranges a reverse proxy runs in.
_ALWAYS_TRUSTED = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


def _trusted_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets = list(_ALWAYS_TRUSTED)
    for entry in settings.trusted_proxy_list:
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("ignoring unparseable TRUSTED_PROXIES entry: %s", entry)
    return nets


def _is_trusted(host: str | None) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _trusted_networks())


def _forwarded_client(forwarded: str) -> str | None:
    """Return the rightmost address in X-Forwarded-For that we did not add.

    Each proxy appends the peer it saw, so the rightmost entry is the one our
    own trusted proxy wrote; entries to its left were supplied by the client and
    are trivially spoofable. Walking from the right past our trusted proxies
    gives the first address we can actually vouch for.
    """
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop):
            return hop
    return None


def client_key(request: Request) -> str:
    """Identify the caller.

    X-Forwarded-For is honoured only when the immediate peer is a trusted
    proxy. Without that check any caller could send a fresh `X-Forwarded-For`
    per request and get an unlimited number of rate-limit budgets, which makes
    the limiter decorative.
    """
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted(peer):
        client = _forwarded_client(forwarded)
        if client:
            return client
    return peer or "unknown"


async def _hit(redis, key: str, window_seconds: int, limit: int, now: float) -> int:
    """Record a hit and return the current count within the window."""
    member = f"{now:.6f}"
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window_seconds)
    pipe.zadd(key, {member: now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    results = await pipe.execute()
    return int(results[2])


async def check_rate_limit(request: Request) -> None:
    """Raise 429 if the caller has exceeded either window.

    Fails open if Redis is unreachable: a queue outage should not take the whole
    service down, and the download worker is the real bottleneck anyway.
    """
    if not settings.rate_limit_enabled:
        return

    redis = request.app.state.redis
    key_root = f"ratelimit:{client_key(request)}"
    now = time.time()

    try:
        burst = await _hit(
            redis,
            f"{key_root}:minute",
            window_seconds=60,
            limit=settings.rate_limit_per_minute,
            now=now,
        )
        hourly = await _hit(
            redis,
            f"{key_root}:hour",
            window_seconds=3600,
            limit=settings.rate_limit_per_hour,
            now=now,
        )
    except Exception:  # noqa: BLE001 - deliberately fail open
        logger.warning("rate limit check skipped: redis unavailable", exc_info=True)
        return

    if burst > settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests in the last minute. Please slow down.",
            headers={"Retry-After": "60"},
        )
    if hourly > settings.rate_limit_per_hour:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Hourly request limit reached. Try again later.",
            headers={"Retry-After": "3600"},
        )
