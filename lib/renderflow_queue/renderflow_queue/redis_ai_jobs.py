"""Redis list queue for AI job IDs — shared contract for orchestrator + model workers."""

from __future__ import annotations

import json
from typing import Any

REDIS_KEY_JOBS = "renderflow:ai_jobs"


class RedisJobQueue:
    def __init__(self, client: Any):
        self._r = client

    def push_job(self, job_id: str, payload: dict[str, Any] | None = None) -> None:
        body = json.dumps({"job_id": job_id, "payload": payload or {}})
        self._r.rpush(REDIS_KEY_JOBS, body)

    def blocking_pop(self, timeout_sec: int = 5) -> dict[str, Any] | None:
        item = self._r.blpop(REDIS_KEY_JOBS, timeout=timeout_sec)
        if not item:
            return None
        _, raw = item
        return json.loads(raw)
