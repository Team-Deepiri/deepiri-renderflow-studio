"""Redis list queue for AI job IDs — shared contract for orchestrator + model workers."""

from __future__ import annotations

import json
import time
from enum import IntEnum
from typing import Any

REDIS_KEY_JOBS = "renderflow:ai_jobs"
REDIS_KEY_JOBS_HIGH = "renderflow:ai_jobs:high"
REDIS_KEY_JOBS_DLQ = "renderflow:ai_jobs:dlq"
REDIS_KEY_JOBS_RETRY = "renderflow:ai_jobs:retry"


class JobPriority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2


class JobStatus(IntEnum):
    QUEUED = 0
    PROCESSING = 1
    COMPLETED = 2
    FAILED = 3
    DEAD_LETTER = 4


class RedisJobQueue:
    def __init__(self, client: Any):
        self._r = client

    def push_job(
        self,
        job_id: str,
        payload: dict[str, Any] | None = None,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> None:
        body = json.dumps({"job_id": job_id, "payload": payload or {}, "priority": priority})
        
        if priority == JobPriority.HIGH:
            self._r.rpush(REDIS_KEY_JOBS_HIGH, body)
        else:
            self._r.rpush(REDIS_KEY_JOBS, body)

    def push_to_dlq(self, job_id: str, reason: str, payload: dict[str, Any] | None = None) -> None:
        entry = json.dumps({
            "job_id": job_id,
            "reason": reason,
            "payload": payload or {},
            "failed_at": time.time(),
        })
        self._r.rpush(REDIS_KEY_JOBS_DLQ, entry)

    def push_retry(self, job_id: str, retry_count: int, payload: dict[str, Any] | None = None) -> None:
        entry = json.dumps({
            "job_id": job_id,
            "retry_count": retry_count,
            "payload": payload or {},
            "next_retry_at": time.time() + (2 ** retry_count),
        })
        self._r.zadd(REDIS_KEY_JOBS_RETRY, {entry: time.time()})

    def get_retry_ready(self) -> list[dict[str, Any]] | None:
        now = time.time()
        ready = self._r.zrangebyscore(REDIS_KEY_JOBS_RETRY, 0, now)
        if not ready:
            return None
        
        results = []
        for entry in ready:
            self._r.zrem(REDIS_KEY_JOBS_RETRY, entry)
            data = json.loads(entry)
            data["retry_after"] = data.pop("next_retry_at", 0)
            results.append(data)
        return results

    def blocking_pop(self, timeout_sec: int = 5) -> dict[str, Any] | None:
        result = self._r.blpop([REDIS_KEY_JOBS_HIGH, REDIS_KEY_JOBS], timeout=timeout_sec)
        if not result:
            return None
        _, raw = result
        return json.loads(raw)
