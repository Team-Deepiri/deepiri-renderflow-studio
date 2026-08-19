"""RenderFlow guardrail integration — 6-layer gate system.

Composes diri-agent-guardrails primitives (InjectionChecker, ContentSafetyChecker,
PIIChecker, RateLimitChecker) into RenderFlow-specific guardrail gates.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from app.guardrails.plan_guard import run_plan_gate
from app.guardrails.policy_gate import run_policy_gate
from app.guardrails.prompt_guard import check_prompt, run_prompt_gate


__all__ = [
    "check_prompt",
    "run_plan_gate",
    "run_policy_gate",
    "run_prompt_gate",
]

_logger = logging.getLogger(__name__)

_rfir_env = os.environ.get("RENDERFLOW_RFIR_PACKAGE_DIR")
_worker_guardrails = (
    Path(_rfir_env).parent / "guardrails" if _rfir_env
    else Path(__file__).resolve().parents[3] / "model-workers" / "app" / "guardrails"
)

if _worker_guardrails.is_dir():
    __path__.append(str(_worker_guardrails))
else:
    _logger.warning(
        "app.guardrails bridge: worker-side guardrails not found at %s — Layer 3 "
        "will be unavailable in-process (set RENDERFLOW_RFIR_PACKAGE_DIR to override)",
        _worker_guardrails,
    )

