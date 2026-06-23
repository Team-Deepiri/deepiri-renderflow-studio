"""CFSV Pipeline — Compositor-First Sparse Video.

Compiles a prompt into an RFIR graph and delegates execution to the model worker.
When RENDERFLOW_RFIR_ENABLED=true, text_video_pipeline delegates here.

Spec reference: rfir-inference-engine-implementation.md §1.11
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.rfir.ir.types import (
    CameraMotion,
    CameraPath,
    InferenceBudget,
    Shot,
    ShotList,
    Tier,
)
from app.rfir.compiler.builder import build
from app.rfir.ir.validate import validate

logger = logging.getLogger(__name__)


def compile_tier_a(
    prompt: str,
    output_dir: str,
    *,
    duration_sec: float = 5.0,
    max_gpu_sec: int = 120,
    max_tier: str = "C",
) -> dict[str, Any]:
    """Compile a single Tier-A shot from a prompt. Returns graph JSON path + metadata."""
    shot_list = ShotList(
        prompt=prompt,
        shots=[
            Shot(
                index=0,
                description=prompt,
                tier=Tier.A,
                duration_sec=duration_sec,
                camera=CameraPath(motion=CameraMotion.ZOOM, speed=1.0),
            ),
        ],
    )

    budget = InferenceBudget(
        max_gpu_seconds=float(max_gpu_sec),
        max_tier=Tier[max_tier],
    )

    graph = build(shot_list, budget=budget)

    errors = validate(graph)
    if errors:
        return {"ok": False, "error": f"Graph validation failed: {errors[0].message}"}

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    graph_data = {
        "nodes": [
            {"id": n.id, "op": n.op, "inputs": n.inputs, "outputs": n.outputs, "attrs": n.attrs}
            for n in graph.nodes
        ],
        "tensors": {k: {"dtype": v.dtype.value, "shape": v.shape} for k, v in graph.tensors.items()},
        "metadata": graph.metadata,
    }

    graph_path = out_path / "graph.json"
    graph_path.write_text(json.dumps(graph_data, indent=2))

    return {
        "ok": True,
        "graph_uri": str(graph_path),
        "shot_count": len(shot_list.shots),
        "total_duration_sec": shot_list.total_duration_sec(),
    }
