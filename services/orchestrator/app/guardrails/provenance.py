"""Provenance metadata — C2PA sidecar or JSON sidecar.

Spec reference: guardrails-implementation.md §8.5

Currently builds a JSON sidecar. When c2pa-python is added as a dependency,
this module will embed a real C2PA manifest into the output MP4.
"""
from __future__ import annotations

from datetime import datetime, timezone


def build_provenance_sidecar(
    job_id: str,
    model_ids: list[str],
    provenance_mode: str = "json",
) -> dict:
    """Build provenance metadata for an AI-generated output.

    Returns empty dict when provenance_mode is "off".
    """
    if provenance_mode == "off":
        return {}
    return {
        "schema": "c2pa-lite-v1" if provenance_mode == "c2pa" else "renderflow-sidecar-v1",
        "generator": "Deepiri RenderFlow RFIR",
        "job_id": job_id,
        "model_ids": model_ids,
        "ai_generated": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
