"""Redis-backed job state store.

Job records are small JSON documents keyed by task id. They carry a TTL so an
abandoned job does not sit in Redis forever.
"""

from __future__ import annotations

from arq.connections import ArqRedis

from .models import JobState

JOB_KEY = "job:{task_id}"
JOB_TTL = 60 * 60 * 24  # 24h


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
    job = await load_job(redis, task_id)
    if job is None:
        return None
    for key, value in fields.items():
        setattr(job, key, value)
    from datetime import datetime, timezone

    job.updated_at = datetime.now(timezone.utc)
    await save_job(redis, job)
    return job


async def delete_job(redis: ArqRedis, task_id: str) -> None:
    await redis.delete(_key(task_id))
