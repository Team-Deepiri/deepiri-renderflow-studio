from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app import db_repos
from app.api.schemas.studio import AiJobCreate, AiJobOut
from app.job_store import JobStatus, store
from app.runtime_state import get_settings
from app.worker_loop import cancel_job, enqueue_job, worker_stats
from app.media import ffmpeg as ffmpeg_util
from app.paths import data_subdir
from app.services import studio

from pathlib import Path
import threading

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
    from app import memory_store

    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.status not in (JobStatus.REVIEW, JobStatus.COMMITTED):
        raise HTTPException(status_code=409, detail="accept only allowed from review or committed")

    # Create video asset from the job output if not already created
    if not rec.metadata.get("asset_id"):
        output_path = rec.metadata.get("output_path") or f"renderflow://jobs/{job_id}/output.mp4"
        label = rec.prompt[:60] if rec.prompt else "AI Generated"
        arow = memory_store.asset_create(
            rec.project_id, "video", str(output_path),
            sha256="pending",
            duration_ms=10_000,
            meta={
                "name": f"AI · {label}",
                "source": "ai",
                "proxy_status": "pending",
                "proxy_path": None,
                "width": 1920,
                "height": 1080,
            },
        )
        db_repos.insert_asset(arow)
        aid = str(arow["id"])
        store.merge_meta(job_id, "asset_id", aid)
        db_repos.insert_ai_job_artifact(str(job_id), aid, "ai_bundle", None)

        def _start_proxy(asset_id: str, path: str) -> None:
            pass  # placeholder for future proxy transcoding
        threading.Thread(target=_start_proxy, args=(aid, str(output_path)), daemon=True).start()

    store.update_status(job_id, JobStatus.COMMITTED, stages=rec.stages + ["committed"])
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
