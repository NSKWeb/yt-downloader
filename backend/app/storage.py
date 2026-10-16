"""Redis-backed job state store.

Job records are small JSON documents keyed by task id. They carry a TTL so an
abandoned job does not sit in Redis forever.

Reads and writes of a single record are not atomic on their own, so
`update_job` runs inside a WATCH/MULTI transaction. A plain GET-then-SET loses
one writer's fields whenever two callers touch the same job concurrently: both
read the same snapshot, each sets its own field, and the later SET drops the
other's. A probe with two writers on disjoint fields lost an update in 58 of 60
trials.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone

from arq.connections import ArqRedis
from redis.exceptions import WatchError

from .models import JobState

logger = logging.getLogger(__name__)

JOB_KEY = "job:{task_id}"
JOB_TTL = 60 * 60 * 24  # 24h

# Each attempt re-reads and retries. Contention is a handful of callbacks on
# one job, so this converges quickly; the backoff keeps two writers from
# colliding on the same schedule, and the cap stops a pathological writer from
# spinning forever. The budget is deliberately far above what a probe with two
# writers needed (10 attempts still gave up on 1 job in 60).
_UPDATE_ATTEMPTS = 50
_UPDATE_BACKOFF_BASE = 0.002
_UPDATE_BACKOFF_MAX = 0.05


def _key(task_id: str) -> str:
    return JOB_KEY.format(task_id=task_id)


async def save_job(redis: ArqRedis, job: JobState) -> None:
    await redis.set(_key(job.task_id), job.model_dump_json(), ex=JOB_TTL)


async def load_job(redis: ArqRedis, task_id: str) -> JobState | None:
    raw = await redis.get(_key(task_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return JobState.model_validate_json(raw)


async def update_job(redis: ArqRedis, task_id: str, **fields) -> JobState | None:
    """Apply `fields` to the stored job without clobbering concurrent writers.

    WATCH marks the key; if anything else writes it before EXEC, the
    transaction aborts and we retry against the fresh value. The JSON is
    re-encoded by Pydantic, so this cannot drift from `save_job`'s format the
    way a Lua/cjson rewrite could.
    """
    key = _key(task_id)
    for attempt in range(_UPDATE_ATTEMPTS):
        async with redis.pipeline() as pipe:
            try:
                await pipe.watch(key)
                raw = await pipe.get(key)
                if raw is None:
                    await pipe.unwatch()
                    return None
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                job = JobState.model_validate_json(raw)
                for name, value in fields.items():
                    setattr(job, name, value)
                job.updated_at = datetime.now(timezone.utc)
                pipe.multi()
                pipe.set(key, job.model_dump_json(), ex=JOB_TTL)
                await pipe.execute()
                return job
            except WatchError:
                # Jittered backoff so two writers stop colliding in lockstep.
                delay = min(_UPDATE_BACKOFF_BASE * 2**attempt, _UPDATE_BACKOFF_MAX)
                await asyncio.sleep(delay * (0.5 + random.random()))
    logger.warning("gave up updating job %s after %d attempts", task_id, _UPDATE_ATTEMPTS)
    return None


async def delete_job(redis: ArqRedis, task_id: str) -> None:
    await redis.delete(_key(task_id))
