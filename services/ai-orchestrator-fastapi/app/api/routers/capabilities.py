"""Orchestrator capability introspection (GPU via installed deepiri-gpu-utils)."""

from __future__ import annotations

from typing import Any

from deepiri_gpu_utils.detect import detect
from fastapi import APIRouter

router = APIRouter(tags=["system"])


def _gpu_capabilities() -> dict[str, Any]:
    r = detect()
    return {
        "backend": r.backend,
        "confidence": r.confidence,
        "details": r.details,
        "warnings": r.warnings,
    }


@router.get("/v1/capabilities")
def get_capabilities() -> dict[str, Any]:
    return {
        "gpu": _gpu_capabilities(),
        "service": "deepiri-renderflow-orchestrator",
    }
