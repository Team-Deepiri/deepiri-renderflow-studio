from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.schemas.studio import AiJobCreate, AiJobOut
from app.job_store import JobStatus, store
from app.runtime_state import get_settings
from app.worker_loop import cancel_job, enqueue_job, worker_stats

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


@router.get("/v1/jobs", response_model=list[AiJobOut], tags=["ai"])
def list_ai_jobs(project_id: UUID | None = None, limit: int = 100) -> list[AiJobOut]:
    rows = store.list_by_project(project_id) if project_id else store.list_recent(limit=limit)
    return [AiJobOut.from_record(r) for r in rows]


@router.post("/v1/jobs/{job_id}/cancel", response_model=AiJobOut, tags=["ai"])
def cancel_ai_job(job_id: UUID) -> AiJobOut:
    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.status in (JobStatus.COMMITTED, JobStatus.ACCEPTED, JobStatus.REJECTED):
        raise HTTPException(status_code=409, detail=f"cannot cancel {rec.status.value} job")
    cancel_job(str(job_id))
    store.update_status(job_id, JobStatus.CANCELLED, stages=rec.stages + ["cancelled"])
    return AiJobOut.from_record(store.get(job_id) or rec)


@router.post("/v1/jobs/{job_id}/retry", response_model=AiJobOut, tags=["ai"])
def retry_ai_job(job_id: UUID) -> AiJobOut:
    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.status not in (JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.REJECTED):
        raise HTTPException(status_code=409, detail=f"retry not allowed from {rec.status.value}")
    store.update_status(job_id, JobStatus.QUEUED, stages=["queued"])
    enqueue_job(str(job_id), get_settings())
    current = store.get(job_id)
    return AiJobOut.from_record(current or rec)


@router.post("/v1/jobs/{job_id}/accept", response_model=AiJobOut, tags=["ai"])
def accept_ai_job(job_id: UUID) -> AiJobOut:
    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.status not in (JobStatus.REVIEW, JobStatus.COMMITTED):
        raise HTTPException(status_code=409, detail="accept only allowed from review or committed")
    store.update_status(job_id, JobStatus.ACCEPTED, stages=rec.stages + ["accepted"])
    current = store.get(job_id)
    return AiJobOut.from_record(current or rec)


@router.post("/v1/jobs/{job_id}/reject", response_model=AiJobOut, tags=["ai"])
def reject_ai_job(job_id: UUID) -> AiJobOut:
    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.status not in (JobStatus.REVIEW, JobStatus.COMMITTED, JobStatus.ACCEPTED):
        raise HTTPException(status_code=409, detail="reject only allowed from review, committed, or accepted")
    store.update_status(job_id, JobStatus.REJECTED, stages=rec.stages + ["rejected"])
    current = store.get(job_id)
    return AiJobOut.from_record(current or rec)


@router.get("/v1/jobs/worker/stats", tags=["ai"])
def get_worker_stats() -> dict[str, object]:
    return worker_stats()


@router.get("/v1/jobs/{job_id}", response_model=AiJobOut, tags=["ai"])
def get_ai_job(job_id: UUID) -> AiJobOut:
    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    return AiJobOut.from_record(rec)
