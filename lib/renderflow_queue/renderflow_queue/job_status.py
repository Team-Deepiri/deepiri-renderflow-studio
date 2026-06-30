"""Job status write-back contract — shared by orchestrator + model workers.

The orchestrator enqueues a job onto `REDIS_KEY_JOBS` and owns the
authoritative job record (`job_store.py`), but heavy GPU work happens in a
separate model-workers process. This module gives that worker a way to
report progress/results back without either side importing the other's
Python package (they cannot — see the `app` package name collision noted
in services/orchestrator/app/api/routers/rfir_preview.py).

Contract:
  - Worker writes status via `JobStatusReporter.set_status(job_id, ...)`
    to a Redis string key with a TTL (status is transient, not the system
    of record — the orchestrator's job_store / Postgres is).
  - Orchestrator polls via `JobStatusReporter.get_status(job_id)` and
    mirrors it into job_store until a terminal status is reached.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

REDIS_KEY_JOB_STATUS_PREFIX = "renderflow:ai_jobs:status:"
DEFAULT_STATUS_TTL_SEC = 3600


class RfirJobState(str, Enum):
    PREPARING = "preparing"
    RUNNING = "running"
    REVIEW = "review"
    FAILED = "failed"


@dataclass
class RfirJobStatus:
    job_id: str
    state: RfirJobState
    stage: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RfirJobStatus":
        return cls(
            job_id=data["job_id"],
            state=RfirJobState(data["state"]),
            stage=data.get("stage", ""),
            metadata=data.get("metadata", {}),
            artifacts=data.get("artifacts", {}),
            metrics=data.get("metrics", {}),
            error=data.get("error"),
            updated_at=data.get("updated_at", time.time()),
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in (RfirJobState.REVIEW, RfirJobState.FAILED)


def _key(job_id: str) -> str:
    return f"{REDIS_KEY_JOB_STATUS_PREFIX}{job_id}"


class JobStatusReporter:
    """Read/write RFIR job status against a shared Redis client."""

    def __init__(self, client: Any, ttl_sec: int = DEFAULT_STATUS_TTL_SEC) -> None:
        self._r = client
        self._ttl_sec = ttl_sec

    def set_status(self, status: RfirJobStatus) -> None:
        status.updated_at = time.time()
        self._r.set(_key(status.job_id), json.dumps(status.to_dict()), ex=self._ttl_sec)

    def get_status(self, job_id: str) -> RfirJobStatus | None:
        raw = self._r.get(_key(job_id))
        if not raw:
            return None
        data = json.loads(raw)
        return RfirJobStatus.from_dict(data)

    def clear_status(self, job_id: str) -> None:
        self._r.delete(_key(job_id))
