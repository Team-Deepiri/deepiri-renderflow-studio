"""RFIR Client — serialize compiled graph into Redis job payload.

Extends the standard Redis payload with compiled_graph_uri and budget.

Spec reference: rfir-inference-engine-implementation.md §1.12
"""
from __future__ import annotations

from typing import Any

from app.config import Settings


def build_rfir_payload(
    prompt: str,
    graph_uri: str,
    settings: Settings,
    *,
    guardrail_verdict: str = "allow",
    guardrail_flags: list[str] | None = None,
    project_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Redis job payload with RFIR graph reference."""
    return {
        "prompt": prompt,
        "compiled_graph_uri": graph_uri,
        "budget": {
            "max_gpu_seconds": settings.rfir_max_gpu_sec,
            "max_tier": settings.rfir_max_tier,
        },
        "guardrail_verdict": guardrail_verdict,
        "guardrail_flags": guardrail_flags or [],
        "project": project_meta or {
            "fps_num": 24,
            "fps_den": 1,
            "resolution_w": 1920,
            "resolution_h": 1080,
        },
    }
