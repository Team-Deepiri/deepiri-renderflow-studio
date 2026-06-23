"""Org-maintained keyword blocklist.

Spec reference: guardrails-implementation.md §5.5
"""
from __future__ import annotations

from app.guardrails.types import GuardrailDecision, RFReasonCode

# RenderFlow-specific blocked terms (slurs, explicit, trademarks)
DEFAULT_BLOCKLIST: list[str] = [
    "naked",
    "nude",
    "nudity",
    "porn",
    "pornographic",
    "xxx",
    "undress",
    "genitals",
]


def check_blocklist(
    text: str,
    extra_terms: list[str] | None = None,
) -> GuardrailDecision:
    """Check text against the default + org-specific blocklist."""
    terms = DEFAULT_BLOCKLIST + (extra_terms or [])
    lower = text.lower()
    for term in terms:
        if term.lower() in lower:
            return GuardrailDecision(
                gate="prompt",
                verdict="block",
                reason_code=RFReasonCode.POLICY_BLOCK,
                details={"blocklist_match": term},
            )
    return GuardrailDecision(gate="prompt", verdict="allow")
