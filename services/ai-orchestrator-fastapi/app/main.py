from datetime import datetime, UTC
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    REVIEW = "review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMMITTED = "committed"


class AiJobCreate(BaseModel):
    project_id: UUID
    mode: str = Field(description="scene|audio|vfx|assist")
    prompt: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AiJob(BaseModel):
    id: UUID
    project_id: UUID
    mode: str
    prompt: str
    status: JobStatus
    stages: list[str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


app = FastAPI(title="Deepiri Renderflow AI Orchestrator", version="0.1.0")
_jobs: dict[UUID, AiJob] = {}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/jobs", response_model=AiJob)
def create_job(payload: AiJobCreate) -> AiJob:
    now = datetime.now(UTC)
    job = AiJob(
        id=uuid4(),
        project_id=payload.project_id,
        mode=payload.mode,
        prompt=payload.prompt,
        status=JobStatus.QUEUED,
        stages=["queued"],
        metadata=payload.metadata,
        created_at=now,
        updated_at=now,
    )
    _jobs[job.id] = job
    return job


@app.get("/v1/jobs/{job_id}", response_model=AiJob)
def get_job(job_id: UUID) -> AiJob:
    return _jobs[job_id]
