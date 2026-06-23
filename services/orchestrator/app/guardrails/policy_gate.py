"""Layer 0 — Policy envelope gate.

Checks before any job is enqueued: AI enabled, user role, mode, rate limit, cloud.
Uses diri-agent-guardrails RateLimitChecker for rate limiting.
"""
from __future__ import annotations

import logging
import os
from uuid import UUID

from diri_agent_guardrails.checkers.rate_limit import InMemoryRateLimitBackend, RateLimitChecker

from app.guardrails.config import policy_for_project
from app.guardrails.types import GuardrailDecision, RFReasonCode

logger = logging.getLogger(__name__)

GATE = "policy"

_rate_checker: RateLimitChecker | None = None


def _get_rate_checker() -> RateLimitChecker:
    global _rate_checker
    if _rate_checker is not None:
        return _rate_checker
    _rate_checker = RateLimitChecker(backend=InMemoryRateLimitBackend())
    return _rate_checker


def run_policy_gate(
    project_id: UUID,
    mode: str,
    user_id: str | None = None,
    user_role: str = "editor",
) -> GuardrailDecision:
    """Run Layer 0 policy checks."""
    policy = policy_for_project(project_id, user_id=user_id, user_role=user_role)

    if not policy.enabled or not policy.ai_enabled:
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.AI_DISABLED,
        )

    if policy.user_role == "viewer":
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.VIEWER_ROLE,
        )

    if mode not in policy.allowed_modes:
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.DISALLOWED_MODE,
            details={"mode": mode, "allowed": policy.allowed_modes},
        )

    if not policy.cloud_allowed and not policy.local_only:
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.CLOUD_BLOCKED,
        )

    if policy.user_id:
        checker = _get_rate_checker()
        result = checker.check(
            "",
            key=f"guardrail:rate:{policy.user_id}",
            limit=policy.rate_limit_per_hour,
            window_seconds=3600,
        )
        if result.blocked:
            return GuardrailDecision(
                gate=GATE, verdict="block", reason_code=RFReasonCode.RATE_LIMIT,
                details=result.details,
            )

    return GuardrailDecision(gate=GATE, verdict="allow")
