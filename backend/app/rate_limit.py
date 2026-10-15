"""Sliding-window rate limiting backed by Redis.

Two windows are enforced: a per-minute burst limit and an hourly cap. Both use
a sorted set of request timestamps per client key, which gives an accurate
sliding window without the boundary spikes a fixed-window counter allows.

Keys expire on their own, so there is no cleanup job to run.
"""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException, Request, status

from .config import settings

logger = logging.getLogger(__name__)


def client_key(request: Request) -> str:
    """Identify the caller.

    Prefers X-Forwarded-For because the service sits behind nginx, and every
    request would otherwise appear to come from the proxy's own address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
