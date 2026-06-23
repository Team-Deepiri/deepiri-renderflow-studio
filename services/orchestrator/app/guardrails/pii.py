"""PII detection — wraps diri-agent-guardrails PIIChecker.

Spec reference: guardrails-implementation.md §5.3
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from diri_agent_guardrails.checkers.pii import PIIChecker

from app.guardrails.types import GuardrailDecision, RFReasonCode

logger = logging.getLogger(__name__)

_checker = PIIChecker()


def check_pii(text: str) -> GuardrailDecision:
    """Detect PII in text. Returns REDACT verdict if found, ALLOW otherwise."""
    result = _checker.check(text)
    if not result.passed:
        return GuardrailDecision(
            gate="prompt",
            verdict="redact",
            reason_code=RFReasonCode.PII_REDACTED,
            score=result.score,
            details=result.details,
        )
    return GuardrailDecision(gate="prompt", verdict="allow")


def redact_for_audit(text: str) -> str:
    """Replace PII with [REDACTED] for audit log storage.

    If RENDERFLOW_GUARDRAIL_LOG_PROMPTS is false, returns a SHA-256 hash instead.
    """
    log_prompts = os.environ.get("RENDERFLOW_GUARDRAIL_LOG_PROMPTS", "true").lower() == "true"
    if not log_prompts:
        return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"

    redacted = text
    for pattern, label in _checker._compiled:
        redacted = pattern.sub(f"[REDACTED_{label.upper()}]", redacted)
    return redacted
