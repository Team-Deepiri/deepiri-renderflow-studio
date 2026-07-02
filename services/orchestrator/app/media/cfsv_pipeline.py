"""CFSV Pipeline — Compositor-First Sparse Video.

Compiles a prompt into an RFIR graph and executes it. `app.rfir` resolves
through the bridge package (app/rfir/__init__.py), which grafts the
canonical RFIR sources from services/model-workers into this process.
When RENDERFLOW_RFIR_ENABLED=true, worker_loop delegates here for the
in-process path; production GPU work goes to model-workers over Redis.

Spec reference: rfir-inference-engine-implementation.md §1.11
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from app.rfir.ir.types import (
    CameraMotion,
    CameraPath,
    InferenceBudget,
    RfirGraph,
    RfirNode,
    Shot,
    ShotList,
    Tier,
)
from app.rfir.compiler.builder import CompileError, build
from app.rfir.ir.validate import validate

logger = logging.getLogger(__name__)


def _build_tier_a(
    prompt: str,
    *,
    duration_sec: float,
    max_gpu_sec: int,
    max_tier: str,
) -> tuple[RfirGraph, ShotList, InferenceBudget]:
    """Build a single Tier-A shot graph. Raises CompileError on bad input."""
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
    return graph, shot_list, budget


def _write_graph_json(graph: RfirGraph, output_dir: str) -> Path:
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
    return graph_path


def compile_tier_a(
    prompt: str,
    output_dir: str,
    *,
    duration_sec: float = 5.0,
    max_gpu_sec: int = 120,
    max_tier: str = "C",
) -> dict[str, Any]:
    """Compile a single Tier-A shot from a prompt. Returns graph JSON path + metadata."""
    try:
        graph, shot_list, _budget = _build_tier_a(
            prompt, duration_sec=duration_sec, max_gpu_sec=max_gpu_sec, max_tier=max_tier,
        )
    except CompileError as e:
        return {"ok": False, "error": str(e)}

    errors = validate(graph)
    if errors:
        return {"ok": False, "error": f"Graph validation failed: {errors[0].message}"}

    graph_path = _write_graph_json(graph, output_dir)

    return {
        "ok": True,
        "graph_uri": str(graph_path),
        "shot_count": len(shot_list.shots),
        "total_duration_sec": shot_list.total_duration_sec(),
    }


def compile_and_run_tier_a(
    prompt: str,
    output_dir: str,
    *,
    job_id: str = "adhoc",
    duration_sec: float = 5.0,
    max_gpu_sec: int = 120,
    max_tier: str = "C",
    on_node_start: Callable[[RfirNode], None] | None = None,
) -> dict[str, Any]:
    """Compile a Tier-A shot and execute the graph in-process.

    Returns artifact paths on success: the muxed output.mp4, the keyframe
    PNGs, the serialized graph, and executor metrics. Failures (bad prompt,
    missing ML runtime or model weights, no ffmpeg) come back as
    {"ok": False, "error": ...} rather than raising.

    on_node_start is forwarded to the executor for per-stage progress;
    exceptions it raises (e.g. a cancellation signal) propagate to the
    caller.
    """
    try:
        graph, _shot_list, budget = _build_tier_a(
            prompt, duration_sec=duration_sec, max_gpu_sec=max_gpu_sec, max_tier=max_tier,
        )
    except CompileError as e:
        return {"ok": False, "error": str(e)}

    errors = validate(graph)
    if errors:
        return {"ok": False, "error": f"Graph validation failed: {errors[0].message}"}

    graph_path = _write_graph_json(graph, output_dir)

    from app.rfir.executor.engine import run_graph

    try:
        ctx = run_graph(
            graph, job_id=job_id, output_dir=output_dir,
            budget=budget, on_node_start=on_node_start,
        )
    except Exception as e:
        logger.warning("RFIR execution failed for job %s: %s", job_id, e)
        return {"ok": False, "error": f"RFIR execution failed: {e}", "graph_uri": str(graph_path)}

    output_mp4 = ctx.artifacts.get("output_mp4")
    if not output_mp4 or not Path(output_mp4).exists():
        return {
            "ok": False,
            "error": "executor produced no output.mp4 (is ffmpeg installed and on PATH?)",
            "graph_uri": str(graph_path),
            "artifacts": dict(ctx.artifacts),
        }

    keyframes = sorted(
        path for key, path in ctx.artifacts.items()
        if path.endswith(".png") and "depth" not in key
    )

    return {
        "ok": True,
        "output_path": output_mp4,
        "keyframes": keyframes,
        "graph_uri": str(graph_path),
        "metrics": ctx.to_metrics_dict(),
    }
