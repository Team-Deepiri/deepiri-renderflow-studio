"""Layer 1 — Input / prompt guard.

Composes classifier, PII, and blocklist modules with
RenderFlow-specific zero-tolerance patterns.

Spec reference: guardrails-implementation.md §5
"""
from __future__ import annotations

import os
import re
from uuid import UUID

from fastapi import HTTPException

from app.guardrails.blocklist import check_blocklist
from app.guardrails.classifier import get_classifier
from app.guardrails.config import policy_for_project
from app.guardrails.pii import check_pii
from app.guardrails.presets import RenderFlowPolicy, build_policy
from app.guardrails.types import GuardrailDecision, RFReasonCode

GATE = "prompt"

# Zero-tolerance patterns (S4 CSAM / S9 weapons) — always block, no admin override
_ZERO_TOLERANCE = re.compile(
    r"child\s*porn|csam|\bloli(?!pop)\b|\bshota\b|ncii"
    r"|synthesize\s+(?:sarin|vx gas|novichok|mustard\s+gas|nerve\s+agent)"
    r"|(?:how\s+to\s+)?(?:make|build|create)\s+(?:a\s+)?(?:dirty\s+bomb|bioweapon|biological\s+weapon)",
    re.IGNORECASE,
)

_REASON_MESSAGES: dict[str, str] = {
    "SAFETY_BLOCK": "This prompt was flagged for safety reasons.",
    "INJECTION_DETECTED": "This prompt contains disallowed instructions.",
    "PROMPT_TOO_LONG": "Prompt exceeds the maximum allowed length.",
    "PII_REDACTED": "Personal information was detected and will be redacted.",
    "POLICY_BLOCK": "This prompt isn't allowed under your organization's rules.",
}


def run_prompt_gate(
    prompt: str,
    project_id: UUID,
    user_id: str | None = None,
    user_role: str = "editor",
) -> GuardrailDecision:
    """Run Layer 1 prompt checks."""
    policy = policy_for_project(project_id, user_id=user_id, user_role=user_role)
    return _check(prompt, policy)


def check_prompt(prompt: str) -> None:
    """Convenience guard that raises HTTPException on block.

    Used by media_generation routes without project context.
    """
    readiness = os.environ.get("READINESS_MODE", "dev")
    preset = "dev" if readiness == "dev" else "us_default"
    policy = build_policy(preset)

    decision = _check(prompt, policy)
    if decision.blocked:
        reason = decision.reason_code.value if decision.reason_code else "POLICY_BLOCK"
        msg = _REASON_MESSAGES.get(reason, "Prompt blocked by safety policy.")
        raise HTTPException(status_code=403, detail=msg)


def _check(prompt: str, policy: RenderFlowPolicy) -> GuardrailDecision:
    """Core check logic shared by both entry points."""
    # 1. Zero-tolerance — always block (S4/S9), no admin override
    if _ZERO_TOLERANCE.search(prompt):
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.SAFETY_BLOCK,
            score=1.0, details={"zero_tolerance": True},
        )

    # 2. Length
    if len(prompt) > policy.max_prompt_length:
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.PROMPT_TOO_LONG,
            details={"length": len(prompt), "limit": policy.max_prompt_length},
        )

    # 3. Blocklist (org keywords + RenderFlow defaults)
    bl_decision = check_blocklist(prompt)
    if bl_decision.blocked:
        return bl_decision

    # 4. Safety classifier (injection + content)
    classifier = get_classifier()
    result = classifier.classify(prompt)
    if not result.safe:
        is_injection = "S_INJECTION" in result.categories
        return GuardrailDecision(
            gate=GATE, verdict="block",
            reason_code=RFReasonCode.INJECTION_DETECTED if is_injection else RFReasonCode.SAFETY_BLOCK,
            score=result.score,
            details={**result.details, "categories": result.categories},
        )

    # 5. PII detection → REDACT (not block)
    pii_decision = check_pii(prompt)
    if pii_decision.verdict == "redact":
        return pii_decision

    return GuardrailDecision(gate=GATE, verdict="allow")
