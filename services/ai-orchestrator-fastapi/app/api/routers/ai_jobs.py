from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.schemas.studio import AiJobCreate, AiJobOut
from app.job_store import store
from app.runtime_state import get_settings
from app.worker_loop import enqueue_job

router = APIRouter()


@router.post("/v1/jobs", response_model=AiJobOut, tags=["ai"])
def create_ai_job(payload: AiJobCreate) -> AiJobOut:
    job = store.create(
        payload.project_id,
        payload.mode,
        payload.prompt,
        metadata=payload.metadata,
    )
    enqueue_job(str(job.id), get_settings())
    return AiJobOut.from_record(job)


@router.get("/v1/jobs/{job_id}", response_model=AiJobOut, tags=["ai"])
def get_ai_job(job_id: UUID) -> AiJobOut:
    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    return AiJobOut.from_record(rec)
