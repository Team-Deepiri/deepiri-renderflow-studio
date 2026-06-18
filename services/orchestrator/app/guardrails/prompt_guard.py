"""Layer 1 — Input / prompt guard.

Composes diri-agent-guardrails checkers (injection, content, PII) with
RenderFlow-specific zero-tolerance patterns and org blocklist.
"""
from __future__ import annotations

import os
import re
from uuid import UUID

from fastapi import HTTPException

from diri_agent_guardrails.checkers.content import ContentSafetyChecker
from diri_agent_guardrails.checkers.injection import InjectionChecker
from diri_agent_guardrails.checkers.pii import PIIChecker

from app.guardrails.config import policy_for_project
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

# RenderFlow-specific content patterns on top of library defaults
_rf_content = ContentSafetyChecker(patterns=[
    r"\b(?:naked|nude|nudity|porn|pornographic|xxx)\b",
    r"\b(?:sexual|erotic)\s+(?:content|image|video|picture|scene)\b",
    r"\b(?:undress|strip|genitals?|breasts?)\b",
    r"\b(?:how\s+to|ways?\s+to|steps?\s+to)\s+(?:die|kill\s+(?:my|your)?self|commit\s+suicide|self[- ]harm|end\s+(?:my|your)\s+life)\b",
    r"\b(?:how\s+to\s+)?(?:murder|stab|shoot|torture)\s+(?:a\s+)?(?:person|people|someone|human)\b",
])

_injection = InjectionChecker()
_content = ContentSafetyChecker()
_pii = PIIChecker()

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
    """Run Layer 1 prompt checks using diri-agent-guardrails checkers."""
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
    # 1. Zero-tolerance — always block (S4/S9)
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

    # 3. Injection check (from package)
    inj_result = _injection.check(prompt)
    if inj_result.blocked:
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.INJECTION_DETECTED,
            score=inj_result.score, details=inj_result.details,
        )

    # 4. Content safety — library defaults + RenderFlow-specific patterns
    for checker in (_content, _rf_content):
        content_result = checker.check(prompt)
        if content_result.blocked:
            return GuardrailDecision(
                gate=GATE, verdict="block", reason_code=RFReasonCode.SAFETY_BLOCK,
                score=content_result.score, details=content_result.details,
            )

    # 5. PII detection → REDACT (not block)
    pii_result = _pii.check(prompt)
    if not pii_result.passed:
        return GuardrailDecision(
            gate=GATE, verdict="redact", reason_code=RFReasonCode.PII_REDACTED,
            score=pii_result.score, details=pii_result.details,
        )

    return GuardrailDecision(gate=GATE, verdict="allow")
