"""Tests for the CFSV pipeline: compile_tier_a and compile_and_run_tier_a (§1.11).

The ML ops (t2i, depth) are replaced by the shared fake_ml_ops fixture
(conftest.py) so no torch, model weights, or GPU are needed — the tests
exercise the real compiler, validator, executor engine, and ffmpeg mux
end to end.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.media.cfsv_pipeline import compile_and_run_tier_a, compile_tier_a

ffmpeg_required = pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="ffmpeg not found in PATH"
)


@pytest.fixture(autouse=True)
def _safe_keyframes(monkeypatch):
    """Score every generated frame as clean by default.

    This path now runs the Layer 3 guard, and without a stub the classifier
    weights would load on every test here. Tests that care about the guard
    override _nsfw_score themselves.
    """
    from app.guardrails import runtime_guard

    monkeypatch.setattr(runtime_guard, "_nsfw_score", lambda _b: 0.01)


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
def test_compile_and_run_tier_a_returns_ok_with_artifacts(tmp_path, fake_ml_ops):
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
def test_compile_and_run_tier_a_reports_node_progress(tmp_path, fake_ml_ops):
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


def test_compile_and_run_tier_a_callback_exceptions_propagate(tmp_path, fake_ml_ops):
    class Abort(BaseException):
        pass

    def cancel(node):
        raise Abort()

    with pytest.raises(Abort):
        compile_and_run_tier_a("anything", str(tmp_path), on_node_start=cancel)


def test_blocked_keyframe_fails_the_run_and_persists_nothing(tmp_path, monkeypatch, fake_ml_ops):
    from app.guardrails import runtime_guard

    monkeypatch.setattr(runtime_guard, "_nsfw_score", lambda _b: 0.95)

    result = compile_and_run_tier_a("anything", str(tmp_path), nsfw_mode="block")

    assert result["ok"] is False
    assert "generation blocked" in result["error"]
    assert not list(Path(tmp_path).glob("*.png")), "a blocked frame was written to disk"
    assert not (Path(tmp_path) / "output.mp4").exists()


def test_nsfw_mode_reaches_the_guard(tmp_path, monkeypatch, fake_ml_ops):
    """restricted's 0.9 threshold has to survive the trip into the executor —
    a score that blocks under `block` must pass under `restricted`."""
    from app.guardrails import runtime_guard

    monkeypatch.setattr(runtime_guard, "_nsfw_score", lambda _b: 0.8)

    blocked = compile_and_run_tier_a("anything", str(tmp_path / "b"), nsfw_mode="block")
    allowed = compile_and_run_tier_a("anything", str(tmp_path / "r"), nsfw_mode="restricted")

    assert blocked["ok"] is False and "generation blocked" in blocked["error"]
    assert "generation blocked" not in (allowed.get("error") or "")


def test_nsfw_mode_off_never_scores_a_frame(tmp_path, monkeypatch, fake_ml_ops):
    from app.guardrails import runtime_guard

    def _should_not_run(_b):
        raise AssertionError("classifier ran with nsfw_mode=off")

    monkeypatch.setattr(runtime_guard, "_nsfw_score", _should_not_run)

    result = compile_and_run_tier_a("anything", str(tmp_path), nsfw_mode="off")

    assert "generation blocked" not in (result.get("error") or "")


def test_graph_json_records_the_policy_the_run_used(tmp_path, fake_ml_ops):
    compile_and_run_tier_a("anything", str(tmp_path), nsfw_mode="restricted")

    graph = json.loads((Path(tmp_path) / "graph.json").read_text())
    assert graph["metadata"]["nsfw_mode"] == "restricted"
