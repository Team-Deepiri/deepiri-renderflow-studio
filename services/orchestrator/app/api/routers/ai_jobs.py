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
    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.status != JobStatus.REVIEW:
        raise HTTPException(status_code=409, detail=f"accept only allowed from {JobStatus.REVIEW.value}")

    output_path = rec.metadata.get("output_path")
    if not output_path or not Path(output_path).exists():
        detail = rec.metadata.get("artifact_error") or "AI artifact missing on disk"
        raise HTTPException(status_code=422, detail=detail)

    fmt = ffmpeg_util.detect_format(output_path)
    duration_ms: int | None = 5000
    if fmt.get("ok") and fmt.get("duration_seconds"):
        duration_ms = int(float(fmt["duration_seconds"]) * 1000)

    meta: dict[str, object] = {
        "name": f"AI — {rec.prompt[:40]}",
        "proxy_status": "pending" if fmt.get("ok") else "unavailable",
        "proxy_path": None,
        "source": "ai",
        "job_id": str(job_id),
    }
    if fmt.get("ok"):
        meta["size_bytes"] = fmt.get("size_bytes", 0)
        if fmt.get("video"):
            meta["width"] = fmt["video"].get("width")
            meta["height"] = fmt["video"].get("height")
            meta["fps"] = fmt["video"].get("fps")
            meta["codec"] = fmt["video"].get("codec")

    asset = studio.create_asset(rec.project_id, "video", output_path, "pending", duration_ms, meta)
    asset_uuid = asset["id"]
    store.merge_meta(job_id, "asset_id", str(asset_uuid))

    if meta["proxy_status"] == "pending":
        def _make_proxy(aid: UUID, input_path: str) -> None:
            proxy_dir = data_subdir("proxies", get_settings())
            proxy_dir.mkdir(parents=True, exist_ok=True)
            out_path = str(proxy_dir / f"{aid}_proxy.mp4")
            result = ffmpeg_util.transcode_proxy(input_path, out_path)
            if result.get("ok"):
                studio.update_asset_meta(aid, {"proxy_status": "ready", "proxy_path": out_path})
            else:
                studio.update_asset_meta(aid, {"proxy_status": "failed"})

        threading.Thread(target=_make_proxy, args=(asset_uuid, output_path), daemon=True).start()

    db_repos.insert_ai_job_artifact(str(job_id), str(asset_uuid), "video", None)

    accepted_stages = rec.stages + ["accepted"]
    store.update_status(job_id, JobStatus.ACCEPTED, stages=accepted_stages)
    store.update_status(job_id, JobStatus.COMMITTED, stages=accepted_stages + ["committed"])
    current = store.get(job_id)
    return AiJobOut.from_record(current or rec)


@router.post("/v1/jobs/{job_id}/reject", response_model=AiJobOut, tags=["ai"])
def reject_ai_job(job_id: UUID) -> AiJobOut:
    rec = store.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.status not in (JobStatus.REVIEW, JobStatus.ACCEPTED):
        raise HTTPException(status_code=409, detail="reject only allowed from review or accepted")
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
