"""Layer 4 — Output guard.

Runs after all generation stages complete, before JobStatus -> REVIEW.

Spec reference: guardrails-implementation.md §8
"""
from __future__ import annotations

from uuid import UUID

from app.guardrails.config import policy_for_project
from app.guardrails.provenance import build_provenance_sidecar
from app.guardrails.types import GuardrailDecision, RFReasonCode

GATE = "output"


def run_output_gate(
    job_id: str,
    project_id: UUID,
    *,
    model_ids: list[str] | None = None,
    has_likeness_match: bool = False,
    copyright_similarity_score: float = 0.0,
    user_id: str | None = None,
    user_role: str = "editor",
) -> tuple[GuardrailDecision, dict]:
    """Run Layer 4 output checks. Returns (decision, provenance_sidecar)."""
    policy = policy_for_project(project_id, user_id=user_id, user_role=user_role)

    if has_likeness_match:
        if policy.likeness_mode == "strict":
            return GuardrailDecision(
                gate=GATE, verdict="block", reason_code=RFReasonCode.LIKENESS_BLOCK,
            ), {}
        if policy.likeness_mode == "consent":
            return GuardrailDecision(
                gate=GATE, verdict="block", reason_code=RFReasonCode.CONSENT_REQUIRED,
            ), {}

    if copyright_similarity_score > 0.8 and policy.copyright_mode == "block":
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.OUTPUT_BLOCK,
            score=copyright_similarity_score,
        ), {}

    if copyright_similarity_score > 0.6 and policy.copyright_mode == "warn":
        provenance = build_provenance_sidecar(job_id, model_ids or [], policy.provenance_mode)
        return GuardrailDecision(
            gate=GATE, verdict="escalate", reason_code=RFReasonCode.COPYRIGHT_WARN,
            score=copyright_similarity_score,
        ), provenance

    provenance = build_provenance_sidecar(job_id, model_ids or [], policy.provenance_mode)
    return GuardrailDecision(gate=GATE, verdict="allow"), provenance
