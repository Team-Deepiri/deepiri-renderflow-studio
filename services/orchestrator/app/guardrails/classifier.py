"""Safety classifier — Llama-Guard wrapper stub.

Spec reference: guardrails-implementation.md §5.2

Currently delegates to diri-agent-guardrails regex-based checkers.
When Llama-Guard-3-1B is available (Phase G1.3, requires model infra),
this module will load the model via llama-cpp or transformers and
classify prompts against S1-S13 categories.

Env: RENDERFLOW_GUARDRAIL_CLASSIFIER (default: "regex")
  - "regex"           — current implementation (InjectionChecker + ContentSafetyChecker)
  - "llama-guard-3-1b" — future: real Llama Guard model (INT4, CPU)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from diri_agent_guardrails.checkers.content import ContentSafetyChecker
from diri_agent_guardrails.checkers.injection import InjectionChecker

logger = logging.getLogger(__name__)


@dataclass
class ClassifierResult:
    safe: bool
    categories: list[str] = field(default_factory=list)
    score: float = 0.0
    details: dict = field(default_factory=dict)


class SafetyClassifier:
    """Unified safety classifier interface.

    Wraps the current regex checkers. Replace internals with Llama Guard
    when the model loading pipeline is ready.
    """

    def __init__(self) -> None:
        self._classifier_id = os.environ.get("RENDERFLOW_GUARDRAIL_CLASSIFIER", "regex")
        self._injection = InjectionChecker()
        self._content = ContentSafetyChecker()

        if self._classifier_id == "llama-guard-3-1b":
            logger.warning(
                "Llama-Guard-3-1B requested but not yet implemented; falling back to regex classifier"
            )

    @property
    def classifier_id(self) -> str:
        return self._classifier_id

    def classify(self, text: str) -> ClassifierResult:
        """Classify text against safety categories. Returns ClassifierResult."""
        inj = self._injection.check(text)
        if inj.blocked:
            return ClassifierResult(
                safe=False,
                categories=["S_INJECTION"],
                score=inj.score,
                details=inj.details,
            )

        content = self._content.check(text)
        if content.blocked:
            categories = _infer_categories(text)
            return ClassifierResult(
                safe=False,
                categories=categories,
                score=content.score,
                details=content.details,
            )

        return ClassifierResult(safe=True, score=0.0)


def _infer_categories(text: str) -> list[str]:
    """Best-effort S1-S13 category mapping from regex matches.

    Placeholder until Llama Guard provides real category classification.
    """
    import re
    lower = text.lower()
    cats: list[str] = []
    if re.search(r"\b(?:kill|murder|attack|stab|shoot)\b", lower):
        cats.append("S1")
    if re.search(r"\b(?:drug|narcotic|steal|fraud)\b", lower):
        cats.append("S2")
    if re.search(r"\b(?:child|minor|underage).*(?:sex|porn|nude)", lower):
        cats.append("S4")
    if re.search(r"\b(?:bomb|weapon|explosive|sarin|nuke)\b", lower):
        cats.append("S9")
    if re.search(r"\b(?:hate|slur|discriminat)", lower):
        cats.append("S10")
    if re.search(r"\b(?:suicide|self[- ]harm|kill\s+(?:my|your)self)\b", lower):
        cats.append("S11")
    if re.search(r"\b(?:nude|naked|porn|sexual|erotic|nsfw)\b", lower):
        cats.append("S12")
    return cats or ["S_UNKNOWN"]


_classifier: SafetyClassifier | None = None


def get_classifier() -> SafetyClassifier:
    global _classifier
    if _classifier is None:
        _classifier = SafetyClassifier()
    return _classifier
