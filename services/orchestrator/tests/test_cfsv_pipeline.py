"""Tests for the CFSV pipeline: compile_tier_a and compile_and_run_tier_a (§1.11).

The ML ops (t2i, depth) are monkeypatched with cheap fakes so no torch,
model weights, or GPU are needed — the tests exercise the real compiler,
validator, executor engine, and ffmpeg mux end to end.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.media.cfsv_pipeline import compile_and_run_tier_a, compile_tier_a

ffmpeg_required = pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="ffmpeg not found in PATH"
)


@pytest.fixture
def fake_ops(monkeypatch):
    """Replace the ML ops with deterministic fakes (no torch / weights)."""
    from app.rfir.ops import depth_estimate, t2i_keyframe

    def fake_t2i(prompt, *, width=512, height=288, steps=4, seed=None, **kw):
        return Image.new("RGB", (width, height), color=(120, 40, 200))

    def fake_depth(image, **kw):
        return np.zeros((image.height, image.width), dtype=np.float32)

    monkeypatch.setattr(t2i_keyframe, "run", fake_t2i)
    monkeypatch.setattr(depth_estimate, "run", fake_depth)


# ── compile only ──────────────────────────────────────────────────────────────


def test_compile_tier_a_writes_graph_json(tmp_path):
    result = compile_tier_a("a calm lake at sunrise", str(tmp_path))

    assert result["ok"] is True
    assert result["shot_count"] == 1
    assert result["total_duration_sec"] == 5.0

    graph = json.loads(Path(result["graph_uri"]).read_text())
    ops = [n["op"] for n in graph["nodes"]]
    assert "t2i_keyframe" in ops
    assert "ffmpeg_mux" in ops


# ── compile + run ─────────────────────────────────────────────────────────────


@ffmpeg_required
def test_compile_and_run_tier_a_returns_ok_with_artifacts(tmp_path, fake_ops):
    result = compile_and_run_tier_a(
        "a lone samurai on a misty mountain", str(tmp_path), job_id="test-job",
    )

    assert result["ok"] is True, result.get("error")
    output = Path(result["output_path"])
    assert output.name == "output.mp4"
    assert output.exists()
    assert output.stat().st_size > 1024

    assert result["keyframes"], "expected at least one keyframe PNG"
    assert all(Path(p).exists() for p in result["keyframes"])
    assert Path(result["graph_uri"]).exists()
    assert result["metrics"]["nodes"], "expected per-node metrics"


@ffmpeg_required
def test_compile_and_run_tier_a_reports_node_progress(tmp_path, fake_ops):
    seen_ops: list[str] = []

    result = compile_and_run_tier_a(
        "a red balloon over the sea", str(tmp_path),
        on_node_start=lambda node: seen_ops.append(node.op),
    )

    assert result["ok"] is True, result.get("error")
    assert seen_ops[0] == "t2i_keyframe"
    assert "depth_estimate" in seen_ops
    assert seen_ops[-1] == "ffmpeg_mux"


def test_compile_and_run_tier_a_missing_model_fails_cleanly(tmp_path, monkeypatch):
    from app.rfir.ops import t2i_keyframe

    def broken_t2i(*a, **kw):
        raise RuntimeError("model weights not found: flux-schnell-fp16")

    monkeypatch.setattr(t2i_keyframe, "run", broken_t2i)

    result = compile_and_run_tier_a("anything", str(tmp_path))

    assert result["ok"] is False
    assert "model weights not found" in result["error"]


def test_compile_and_run_tier_a_callback_exceptions_propagate(tmp_path, fake_ops):
    class Abort(BaseException):
        pass

    def cancel(node):
        raise Abort()

    with pytest.raises(Abort):
        compile_and_run_tier_a("anything", str(tmp_path), on_node_start=cancel)
