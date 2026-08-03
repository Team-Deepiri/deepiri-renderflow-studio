"""Layer 2 — Plan / storyboard guard.

Called after RFIR plan_shots() generates a ShotList, before GPU compile.
Uses diri-agent-guardrails ContentSafetyChecker for per-shot validation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from diri_agent_guardrails.checkers.content import ContentSafetyChecker

from app.guardrails.config import policy_for_project
from app.guardrails.types import GuardrailDecision, RFReasonCode

GATE = "plan"

_MINOR_PLUS_EXPLICIT = re.compile(
    r"(?:"
    r"\b(?:child|minor|kid|underage|preteen|teen(?:ager)?)\b"
    r".*"
    r"\b(?:nude|naked|intimate|sexual|explicit|erotic)\b"
    r"|"
    r"\b(?:nude|naked|intimate|sexual|explicit|erotic)\b"
    r".*"
    r"\b(?:child|minor|kid|underage|preteen|teen(?:ager)?)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}
_content = ContentSafetyChecker()


@dataclass
class ShotEntry:
    description: str
    duration_sec: float = 5.0
    tier: str = "B"
    metadata: dict = field(default_factory=dict)


def _shots_payload(entries: list[ShotEntry]) -> list[dict]:
    """Serialize entries so callers can read back tier downgrades, not silently dropped."""
    return [
        {"description": e.description, "duration_sec": e.duration_sec, "tier": e.tier}
        for e in entries
    ]


def run_plan_gate(
    shots: list[ShotEntry] | list[dict],
    project_id: UUID,
    user_id: str | None = None,
    user_role: str = "editor",
) -> GuardrailDecision:
    """Validate a shot list against the project's guardrail policy."""
    policy = policy_for_project(project_id, user_id=user_id, user_role=user_role)
    entries = [ShotEntry(**s) if isinstance(s, dict) else s for s in shots]

    total_sec = sum(e.duration_sec for e in entries)
    if total_sec > policy.max_duration_sec:
        return GuardrailDecision(
            gate=GATE, verdict="block", reason_code=RFReasonCode.DURATION_CAP,
            details={"total_sec": total_sec, "limit_sec": policy.max_duration_sec},
        )

    max_allowed_tier = _TIER_ORDER.get(policy.max_tier, 2)

    for i, shot in enumerate(entries):
        if _MINOR_PLUS_EXPLICIT.search(shot.description):
            return GuardrailDecision(
                gate=GATE, verdict="block", reason_code=RFReasonCode.SAFETY_BLOCK,
                score=1.0, details={"shot_index": i, "reason": "minor+explicit descriptor"},
            )

        if _TIER_ORDER.get(shot.tier, 1) > max_allowed_tier:
            shot.tier = policy.max_tier

        result = _content.check(shot.description)
        if result.blocked:
            return GuardrailDecision(
                gate=GATE, verdict="block", reason_code=RFReasonCode.PLAN_UNSAFE,
                score=result.score, details={"shot_index": i, "shot": shot.description[:120]},
            )

    return GuardrailDecision(
        gate=GATE, verdict="allow", details={"shots": _shots_payload(entries)},
    )
