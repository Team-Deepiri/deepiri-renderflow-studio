"""Tier-A end-to-end proof — runs the full inference pipeline locally.

Compiles a single Tier-A shot and calls run_graph() to produce a real MP4.
Requires model weights downloaded by scripts/download_rfir_models.py.

Run:
    RENDERFLOW_MODELS_DIR=$HOME/renderflow-models poetry run pytest tests/test_tier_a_e2e.py -v -s
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

import pytest

MODELS_DIR = os.environ.get("RENDERFLOW_MODELS_DIR")

pytestmark = pytest.mark.skipif(
    not MODELS_DIR,
    reason="RENDERFLOW_MODELS_DIR not set — run: export RENDERFLOW_MODELS_DIR=$HOME/renderflow-models",
)


def _build_tier_a_graph():
    from app.rfir.ir.types import (
        CameraMotion,
        CameraPath,
        InferenceBudget,
        Shot,
        ShotList,
        Tier,
    )
    from app.rfir.compiler.builder import build

    shot_list = ShotList(
        prompt="a lone samurai stands on a misty mountain at dawn",
        shots=[
            Shot(
                index=0,
                description="wide shot of a samurai silhouetted against a misty mountain at dawn",
                tier=Tier.A,
                duration_sec=5.0,
                camera=CameraPath(motion=CameraMotion.STATIC),
            )
        ],
    )

    return build(shot_list, budget=InferenceBudget(max_tier=Tier.A))


def test_tier_a_graph_compiles():
    """The compiler produces a valid Tier-A graph with the expected ops."""
    graph = _build_tier_a_graph()

    ops = [n.op for n in graph.nodes]
    assert "t2i_keyframe" in ops, "missing t2i_keyframe node"
    assert "depth_estimate" in ops, "missing depth_estimate node"
    assert "ffmpeg_mux" in ops, "missing ffmpeg_mux node"
    assert graph.metadata["tier_distribution"].get("A", 0) == 1

    print(f"\n  Nodes: {ops}")
    print(f"  Tier distribution: {graph.metadata['tier_distribution']}")


def test_tier_a_run_graph_produces_mp4():
    """run_graph() executes the Tier-A pipeline and writes output.mp4 to disk."""
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not found in PATH — install it to produce MP4 output")

    graph = _build_tier_a_graph()

    keep_dir = os.environ.get("RFIR_OUTPUT_DIR")
    tmp_obj = None
    if keep_dir:
        tmp = keep_dir
        Path(tmp).mkdir(parents=True, exist_ok=True)
    else:
        tmp_obj = tempfile.TemporaryDirectory(prefix="rfir_tier_a_")
        tmp = tmp_obj.name

    with (tmp_obj or contextlib.nullcontext()):
        from app.rfir.executor.engine import run_graph

        ctx = run_graph(graph, job_id="test-tier-a-001", output_dir=tmp)

        output_mp4 = Path(tmp) / "output.mp4"

        print(f"\n  Output dir: {tmp}")
        print(f"  Artifacts: {list(ctx.artifacts.keys())}")
        print(f"  Node timings:")
        for m in ctx.node_metrics:
            print(f"    {m.node_id} ({m.op}): {m.wall_ms:.0f} ms")

        assert output_mp4.exists(), f"output.mp4 not found in {tmp}"
        size_kb = output_mp4.stat().st_size / 1024
        assert size_kb > 1, f"output.mp4 is suspiciously small: {size_kb:.1f} KB"
        assert "output_mp4" in ctx.artifacts

        print(f"\n  output.mp4 size: {size_kb:.1f} KB")
        print(f"  Path: {ctx.artifacts['output_mp4']}")
