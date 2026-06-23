"""RenderFlow guardrail integration — 6-layer gate system.

Composes diri-agent-guardrails primitives (InjectionChecker, ContentSafetyChecker,
PIIChecker, RateLimitChecker) into RenderFlow-specific guardrail gates.
"""
from __future__ import annotations

from app.guardrails.policy_gate import run_policy_gate
from app.guardrails.prompt_guard import check_prompt, run_prompt_gate

__all__ = [
    "check_prompt",
    "run_policy_gate",
    "run_prompt_gate",
]
