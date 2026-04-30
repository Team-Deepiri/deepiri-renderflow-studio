from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from app import db

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    REVIEW = "review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMMITTED = "committed"


@dataclass
class AiJobRecord:
    id: UUID
    project_id: UUID
    mode: str
    prompt: str
    status: JobStatus
    stages: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[UUID, AiJobRecord] = {}

    def create(
        self,
        project_id: UUID,
        mode: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> AiJobRecord:
        now = datetime.now(UTC)
        job = AiJobRecord(
            id=uuid4(),
            project_id=project_id,
            mode=mode,
            prompt=prompt,
            status=JobStatus.QUEUED,
            stages=["queued"],
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job.id] = job
        db.insert_ai_job(
            str(job.id),
            str(project_id),
            mode,
            prompt,
            job.status.value,
        )
        return job

    def get(self, job_id: UUID) -> AiJobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update_status(self, job_id: UUID, status: JobStatus, stages: list[str] | None = None) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j.status = status
            j.updated_at = datetime.now(UTC)
            if stages is not None:
                j.stages = list(stages)
        db.update_ai_job_status(str(job_id), status.value)

    def merge_meta(self, job_id: UUID, key: str, value: Any) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j.metadata[key] = value
            j.updated_at = datetime.now(UTC)

    def set_stages(self, job_id: UUID, stages: list[str], completed_through: int) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j.stages = list(stages)
            j.updated_at = datetime.now(UTC)
        db.sync_job_stages(str(job_id), stages, completed_through=completed_through)

    def mark_artifact_committed(self, job_id: UUID, artifact_id: UUID) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j.metadata["committed_artifact"] = str(artifact_id)
            j.updated_at = datetime.now(UTC)

    def list_by_project(self, project_id: UUID) -> list[AiJobRecord]:
        with self._lock:
            return [j for j in self._jobs.values() if j.project_id == project_id]


store = JobStore()
