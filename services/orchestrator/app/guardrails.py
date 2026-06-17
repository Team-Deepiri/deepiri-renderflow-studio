"""Guardrail helpers — thin wrapper around diri-agent-guardrails for RenderFlow."""
from __future__ import annotations

from fastapi import HTTPException

from diri_agent_guardrails import SafetyGuardrails
from diri_agent_guardrails.checkers.content import ContentSafetyChecker

_guardrails = SafetyGuardrails()

# RenderFlow-specific content patterns on top of the library defaults
_rf_content = ContentSafetyChecker(patterns=[
    # Adult / explicit content
    r"\b(?:naked|nude|nudity|porn|pornographic|xxx)\b",
    r"\b(?:sexual|erotic)\s+(?:content|image|video|picture|scene)\b",
    r"\b(?:undress|strip|genitals?|breasts?)\b",
    # Self-harm / suicide — only block instructional requests, not awareness/prevention
    r"\b(?:how\s+to|ways?\s+to|steps?\s+to)\s+(?:die|kill\s+(?:my|your)?self|commit\s+suicide|self[- ]harm|end\s+(?:my|your)\s+life)\b",
    r"\bshow\s+(?:me\s+)?how\s+to\s+die\b",
    # Violence against people
    r"\b(?:how\s+to\s+)?(?:murder|stab|shoot|torture)\s+(?:a\s+)?(?:person|people|someone|human)\b",
])


def check_prompt(prompt: str) -> None:
    """Raise HTTP 400 if the prompt fails safety checks."""
    result = _guardrails.check_prompt(prompt)
    if _guardrails.should_block(result):
        raise HTTPException(status_code=400, detail=f"Prompt blocked: {result.message}")

    rf_result = _rf_content.check(prompt)
    if not rf_result.passed:
        raise HTTPException(status_code=400, detail=f"Prompt blocked: {rf_result.message}")
