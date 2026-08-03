"""Tests that _run_t2i_keyframe enforces the injected Layer 3 keyframe guard.
"""
from __future__ import annotations

import pytest
from diri_agent_guardrails.core.result import CheckResult
from diri_agent_guardrails.core.verdict import Verdict
from PIL import Image

from app.rfir.arena import TensorArena
from app.rfir.executor import engine
from app.rfir.executor.context import ExecutionContext
from app.rfir.ir.types import RfirNode


def _fake_image() -> Image.Image:
    return Image.new("RGB", (4, 4), color=(10, 20, 30))


def _allow(*args, **kwargs) -> CheckResult:
    return CheckResult(passed=True, verdict=Verdict.ALLOW)


def _block(*args, **kwargs) -> CheckResult:
    return CheckResult(passed=False, verdict=Verdict.BLOCK, message="unsafe content")


@pytest.fixture(autouse=True)
def _stub_t2i(monkeypatch):
    """Return a real PIL image without loading any model weights."""
    monkeypatch.setattr(engine.t2i_keyframe, "run", lambda *a, **k: _fake_image())


def _node() -> RfirNode:
    return RfirNode(id="s0_t2i", op="t2i_keyframe", outputs={"image": "s0_t2i:image"})


def test_blocked_frame_never_persisted(tmp_path):
    node = _node()
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1", nsfw_mode="block", keyframe_check=_block)

    with pytest.raises(RuntimeError, match="generation blocked"):
        engine._run_t2i_keyframe(node, arena, ctx, tmp_path)

    assert not arena.has("s0_t2i:image")
    assert node.id not in ctx.artifacts
    assert not (tmp_path / "s0_t2i.png").exists()


def test_allowed_frame_persisted_normally(tmp_path):
    node = _node()
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1", nsfw_mode="block", keyframe_check=_allow)

    engine._run_t2i_keyframe(node, arena, ctx, tmp_path)

    assert arena.has("s0_t2i:image")
    assert ctx.artifacts["s0_t2i"] == str(tmp_path / "s0_t2i.png")
    assert (tmp_path / "s0_t2i.png").exists()


def test_no_checker_injected_runs_unguarded(tmp_path):
    """cfsv_pipeline (the orchestrator's in-process path) passes no checker,
    so frames there are generated without a Layer 3 scan. Pinned so the
    unguarded path stays a deliberate, visible choice."""
    node = _node()
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1")

    assert ctx.keyframe_check is None
    engine._run_t2i_keyframe(node, arena, ctx, tmp_path)

    assert arena.has("s0_t2i:image")
    assert (tmp_path / "s0_t2i.png").exists()


def test_batch_blocks_on_first_unsafe_frame_but_leaves_earlier_frames_persisted(tmp_path):
    """Batch checking isn't atomic: frames before the blocked one were already
    checked+persisted individually. The job still fails as a whole (the
    exception propagates and run_rfir_job never reaches REVIEW), so the
    dangling frame is never surfaced — same as any other mid-node failure."""
    calls = {"n": 0}

    def _first_allow_second_block(*args, **kwargs):
        calls["n"] += 1
        return _allow() if calls["n"] == 1 else _block()

    node = RfirNode(
        id="s0_t2i", op="t2i_keyframe",
        outputs={"image_0": "s0_t2i:image_0", "image_1": "s0_t2i:image_1"},
        attrs={"batch": True, "prompts": ["a calm lake", "a busy street"]},
    )
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1", nsfw_mode="block",
                           keyframe_check=_first_allow_second_block)

    with pytest.raises(RuntimeError, match="generation blocked"):
        engine._run_t2i_keyframe(node, arena, ctx, tmp_path)

    assert arena.has("s0_t2i:image_0")
    assert "s0_t2i_0" in ctx.artifacts
    assert not arena.has("s0_t2i:image_1")
    assert "s0_t2i_1" not in ctx.artifacts


def test_ctx_defaults():
    ctx = ExecutionContext(job_id="job-1")
    assert ctx.nsfw_mode == "block"
    assert ctx.keyframe_check is None
