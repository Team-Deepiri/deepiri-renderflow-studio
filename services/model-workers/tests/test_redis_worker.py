"""Tests for redis_worker.run_rfir_job — the real RFIR dispatch entrypoint.

Verifies guardrail refusal, status reporting sequence, and the planner
fallback path. `load_model` is mocked to raise immediately for every model
ID — these are unit tests and must never touch the network or attempt to
download multi-GB weights (FLUX, Qwen GGUF, etc.). The resulting fallback
behavior (single Tier-A shot, then a clean FAILED status once t2i_keyframe
also can't load) is itself what's under test: the pipeline must fail fast
and deterministically when models aren't available, not hang.
"""
from __future__ import annotations

import pytest

from app.redis_worker import _plan_shots, run_rfir_job
from app.rfir.ir.types import Tier
from renderflow_queue import RfirJobState


@pytest.fixture(autouse=True)
def _no_real_model_downloads(monkeypatch):
    """Block every load_model() call so tests never hit the network.

    Each op module did `from app.rfir.models.loader import load_model`, which
    binds its own local name — patching the loader module alone wouldn't
    reach those call sites, so every consumer is patched explicitly.
    """
    def _raise(model_id, device=None):
        raise RuntimeError(f"no model downloads in tests (requested {model_id!r})")

    for mod_path in (
        "app.rfir.models.loader",
        "app.rfir.ops.t2i_keyframe",
        "app.rfir.ops.depth_estimate",
        "app.rfir.ops.segment_subject",
        "app.rfir.ops.vae",
        "app.rfir.ops.rife_interpolate",
        "app.rfir.ops.sparse_t2v_window",
        "app.rfir.planner",
    ):
        import importlib
        mod = importlib.import_module(mod_path)
        if hasattr(mod, "load_model"):
            monkeypatch.setattr(mod, "load_model", _raise)


class FakeReporter:
    def __init__(self) -> None:
        self.statuses = []

    def set_status(self, status) -> None:
        self.statuses.append(status)


def test_guardrail_refusal_blocks_before_any_gpu_work():
    reporter = FakeReporter()
    run_rfir_job("job-1", {"prompt": "a sunrise", "guardrail_verdict": "block"}, reporter)

    assert len(reporter.statuses) == 1
    assert reporter.statuses[0].state == RfirJobState.FAILED
    assert "guardrail_verdict" in reporter.statuses[0].error


def test_default_guardrail_verdict_is_allow():
    """Missing guardrail_verdict should be treated as a bug, not silently allowed —
    but since the orchestrator always sets it, absence currently defaults to
    'allow' for backward compatibility with simpler test payloads."""
    reporter = FakeReporter()
    # Use an empty prompt so planning + compiling are fast/deterministic and we
    # only care about observing that it does NOT short-circuit as blocked.
    run_rfir_job("job-2", {"prompt": "a test prompt", "budget": {"max_gpu_seconds": 0.001, "max_tier": "A"}}, reporter)

    # Should proceed past the guardrail check (first status is PREPARING, not FAILED-for-guardrail).
    assert reporter.statuses[0].state == RfirJobState.PREPARING


def test_plan_shots_falls_back_when_planner_unavailable():
    shot_list = _plan_shots("a calm lake at dawn", Tier.A)
    assert len(shot_list.shots) >= 1
    assert shot_list.prompt == "a calm lake at dawn"


def test_run_rfir_job_reaches_terminal_state():
    """End-to-end through plan->build->fuse->memory_plan->execute, using
    whatever fallbacks are available (no GPU weights needed) — must reach
    a terminal status (review or failed), never hang or silently drop.
    """
    reporter = FakeReporter()
    run_rfir_job(
        "job-3",
        {
            "prompt": "a quiet forest path",
            "guardrail_verdict": "allow",
            "budget": {"max_gpu_seconds": 5.0, "max_tier": "A"},
        },
        reporter,
    )

    assert len(reporter.statuses) >= 2
    terminal = reporter.statuses[-1]
    assert terminal.state in (RfirJobState.REVIEW, RfirJobState.FAILED)


def test_run_rfir_job_reports_tier_distribution_in_metadata():
    reporter = FakeReporter()
    run_rfir_job(
        "job-4",
        {
            "prompt": "a static shot of mountains",
            "guardrail_verdict": "allow",
            "budget": {"max_gpu_seconds": 5.0, "max_tier": "A"},
        },
        reporter,
    )

    layout_statuses = [
        s for s in reporter.statuses
        if s.stage == "asset_generation" and "stage_layout" in s.metadata
    ]
    assert len(layout_statuses) == 1
    assert "tier_distribution" in layout_statuses[0].metadata["stage_layout"]
