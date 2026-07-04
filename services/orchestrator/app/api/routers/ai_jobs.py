from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app import db_repos
from app.api.schemas.studio import AiJobCreate, AiJobOut
from app.guardrails import run_policy_gate, run_prompt_gate
from app.job_store import JobStatus, store
from app.runtime_state import get_settings
from app.worker_loop import cancel_job, enqueue_job, worker_stats
from app.media import ffmpeg as ffmpeg_util
from app.paths import data_subdir, is_persisted_output
from app.services import studio

from pathlib import Path
import hashlib

router = APIRouter()


_REASON_MESSAGES: dict[str, str] = {
    "AI_DISABLED": "AI is turned off for this project.",
    "RATE_LIMIT": "Too many AI requests; try again later.",
    "POLICY_BLOCK": "This request isn't allowed under your organization's rules.",
    "SAFETY_BLOCK": "This prompt was flagged for safety reasons.",
    "INJECTION_DETECTED": "This prompt contains disallowed instructions.",
    "PROMPT_TOO_LONG": "Prompt exceeds the maximum allowed length.",
    "LIKENESS_BLOCK": "Real-person likeness restrictions apply.",
    "CONSENT_REQUIRED": "Link a consent record for this subject.",
    "OUTPUT_BLOCK": "Generated output didn't pass safety checks.",
    "QUOTA_EXCEEDED": "GPU time quota used for this period.",
    "VIEWER_ROLE": "Viewers cannot submit AI generation jobs.",
    "DISALLOWED_MODE": "This AI mode is not enabled for your project.",
    "CLOUD_BLOCKED": "Cloud inference is not allowed for this project.",
}


def _log_decision(job_id: str | None, decision) -> None:
    """Persist a GuardrailDecision to the database + audit trail."""
    db_repos.insert_guardrail_decision(
        job_id=job_id,
        gate=decision.gate,
        verdict=decision.verdict,
        reason_code=decision.reason_code.value if decision.reason_code else None,
        score=decision.score,
        details=decision.details,
    )
    if decision.blocked:
        db_repos.audit_log(
            project_id=None,
            actor_id=None,
            event_type=f"ai.guardrail.{decision.gate}.blocked",
            payload=decision.to_dict(),
        )


@router.post("/v1/jobs", response_model=AiJobOut, tags=["ai"])
def create_ai_job(payload: AiJobCreate) -> AiJobOut:
    user_id = payload.metadata.get("user_id")
    user_role = payload.metadata.get("user_role", "editor")

    # Layer 0 — policy gate
    policy_decision = run_policy_gate(
        payload.project_id, payload.mode,
        user_id=user_id, user_role=user_role,
    )
    if policy_decision.blocked:
        _log_decision(None, policy_decision)
        reason = policy_decision.reason_code.value if policy_decision.reason_code else "POLICY_BLOCK"
        raise HTTPException(403, detail=_REASON_MESSAGES.get(reason, reason))

    # Layer 1 — prompt guard
    prompt_decision = run_prompt_gate(
        payload.prompt, payload.project_id,
        user_id=user_id, user_role=user_role,
    )
    if prompt_decision.blocked:
        _log_decision(None, prompt_decision)
        reason = prompt_decision.reason_code.value if prompt_decision.reason_code else "SAFETY_BLOCK"
        raise HTTPException(403, detail=_REASON_MESSAGES.get(reason, reason))

    # Passed gates — create and enqueue
    guardrail_flags = []
    if prompt_decision.verdict == "redact":
        guardrail_flags.append("PII_REDACTED")
    if prompt_decision.verdict == "escalate":
        guardrail_flags.append("ESCALATED")

    job = store.create(
        payload.project_id,
        payload.mode,
        payload.prompt,
        metadata={
            **payload.metadata,
            "guardrail_verdict": "allow",
            "guardrail_flags": guardrail_flags,
        },
    )

    _log_decision(str(job.id), policy_decision)
    _log_decision(str(job.id), prompt_decision)

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


def _sha256_file(path: Path) -> str:
    """Content hash of a job artifact, streamed so large MP4s don't load into RAM."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
        output_path = rec.metadata.get("output_path")
        if not is_persisted_output(output_path):
            raise HTTPException(status_code=409, detail=f"job output file is missing or unset: {output_path!r}")
        out_file = Path(output_path)
        output_path = str(out_file.resolve())

        label = rec.prompt[:60] if rec.prompt else "AI Generated"
        arow = memory_store.asset_create(
            rec.project_id, "video", output_path,
            sha256=_sha256_file(out_file),
            duration_ms=10_000,
            meta={
                "name": f"AI · {label}",
                "source": "ai",
                "proxy_status": "ready",
                "proxy_path": output_path,
                "width": 1920,
                "height": 1080,
            },
        )
        db_repos.insert_asset(arow)
        aid = str(arow["id"])
        store.merge_meta(job_id, "asset_id", aid)
        db_repos.insert_ai_job_artifact(str(job_id), aid, "ai_bundle", None)

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
