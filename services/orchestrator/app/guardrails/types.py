"""RenderFlow guardrail types — wraps diri-agent-guardrails core primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RFReasonCode(str, Enum):
    AI_DISABLED = "AI_DISABLED"
    VIEWER_ROLE = "VIEWER_ROLE"
    DISALLOWED_MODE = "DISALLOWED_MODE"
    CLOUD_BLOCKED = "CLOUD_BLOCKED"
    RATE_LIMIT = "RATE_LIMIT"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    SAFETY_BLOCK = "SAFETY_BLOCK"
    INJECTION_DETECTED = "INJECTION_DETECTED"
    PROMPT_TOO_LONG = "PROMPT_TOO_LONG"
    PII_REDACTED = "PII_REDACTED"
    POLICY_BLOCK = "POLICY_BLOCK"
    PLAN_UNSAFE = "PLAN_UNSAFE"
    DURATION_CAP = "DURATION_CAP"
    OUTPUT_BLOCK = "OUTPUT_BLOCK"
    LIKENESS_BLOCK = "LIKENESS_BLOCK"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    COPYRIGHT_WARN = "COPYRIGHT_WARN"


@dataclass
class GuardrailDecision:
    gate: str
    verdict: str  # allow | block | escalate | redact
    reason_code: RFReasonCode | None = None
    score: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "verdict": self.verdict,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "score": self.score,
            "details": self.details,
        }
