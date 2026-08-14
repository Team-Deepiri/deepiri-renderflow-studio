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


@pytest.fixture(autouse=True)
def _plan_gate_allows(monkeypatch):
    """Stub the Layer 2 callback so tests don't need a live orchestrator.

    check_plan is fail-closed by design, so without this every test would
    stop at the plan gate. Tests that exercise the gate itself override this.
    """
    monkeypatch.setattr("app.redis_worker.check_plan", lambda job_id, shot_list: [])


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


def test_missing_guardrail_verdict_refuses():
    """A payload with no guardrail_verdict must fail closed, not be treated as
    an implicit allow — the orchestrator always sets a real value now, so
    absence means something upstream is broken."""
    reporter = FakeReporter()
    run_rfir_job("job-2", {"prompt": "a test prompt", "budget": {"max_gpu_seconds": 0.001, "max_tier": "A"}}, reporter)

    assert len(reporter.statuses) == 1
    assert reporter.statuses[0].state == RfirJobState.FAILED
    assert "guardrail_verdict" in reporter.statuses[0].error


def test_guardrail_flags_do_not_block(caplog):
    """PII_REDACTED / ESCALATED are informational (§3: 'proceed with
    warnings' / 'modify then continue') — only the verdict gates GPU work.
    The worker still surfaces flags in its own logs for visibility."""
    reporter = FakeReporter()
    run_rfir_job(
        "job-flags",
        {"prompt": "a test prompt", "guardrail_verdict": "allow",
         "guardrail_flags": ["PII_REDACTED"],
         "budget": {"max_gpu_seconds": 0.001, "max_tier": "A"}},
        reporter,
    )

    assert reporter.statuses[0].state == RfirJobState.PREPARING
    assert any("PII_REDACTED" in r.message for r in caplog.records)


def test_unknown_guardrail_verdict_refuses():
    reporter = FakeReporter()
    run_rfir_job(
        "job-verdict-bogus",
        {"prompt": "a test prompt", "guardrail_verdict": "maybe"},
        reporter,
    )

    assert reporter.statuses[0].state == RfirJobState.FAILED


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


# --- Layer 2 plan guard -----------------------------------------------------


def _payload(prompt="a quiet forest path"):
    return {
        "prompt": prompt,
        "guardrail_verdict": "allow",
        "budget": {"max_gpu_seconds": 5.0, "max_tier": "A"},
    }


def test_plan_guard_block_stops_before_compile(monkeypatch):
    """A blocked plan must fail the job without compiling or executing."""
    from app.guardrails.plan_client import PlanBlocked

    def _blocked(job_id, shot_list):
        raise PlanBlocked("PLAN_UNSAFE: {'shot_index': 0}")

    monkeypatch.setattr("app.redis_worker.check_plan", _blocked)

    built = []

    def _build(*args, **kwargs):
        built.append(args)
        raise AssertionError("build() must not run on a blocked plan")

    import app.rfir.compiler.builder as builder
    monkeypatch.setattr(builder, "build", _build)

    reporter = FakeReporter()
    run_rfir_job("job-plan-block", _payload(), reporter)

    assert built == []
    terminal = reporter.statuses[-1]
    assert terminal.state == RfirJobState.FAILED
    assert "plan rejected by guardrail" in terminal.error
    assert "PLAN_UNSAFE" in terminal.error


def test_plan_guard_is_fail_closed_when_unreachable(monkeypatch):
    """A transport error must block, not wave the job through."""
    import app.guardrails.plan_client as plan_client

    def _boom(url, body, timeout):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(plan_client, "_post", _boom)
    monkeypatch.setattr("app.redis_worker.check_plan", plan_client.check_plan)

    reporter = FakeReporter()
    run_rfir_job("job-plan-unreachable", _payload(), reporter)

    terminal = reporter.statuses[-1]
    assert terminal.state == RfirJobState.FAILED
    assert "fail-closed" in terminal.error


def test_plan_guard_block_reported_before_storyboard(monkeypatch):
    """A blocked plan must not leak a shot count into the review UI."""
    from app.guardrails.plan_client import PlanBlocked

    def _blocked(job_id, shot_list):
        raise PlanBlocked("SAFETY_BLOCK")

    monkeypatch.setattr("app.redis_worker.check_plan", _blocked)

    reporter = FakeReporter()
    run_rfir_job("job-plan-order", _payload(), reporter)

    assert not any(s.stage == "storyboard" for s in reporter.statuses)


def test_apply_tier_adjustments_downgrades():
    from app.redis_worker import _apply_tier_adjustments
    from app.rfir.ir.types import CameraPath, Shot, ShotList

    shot_list = ShotList(prompt="p", shots=[
        Shot(index=0, description="one", tier=Tier.D, duration_sec=5.0, camera=CameraPath()),
        Shot(index=1, description="two", tier=Tier.A, duration_sec=5.0, camera=CameraPath()),
    ])

    _apply_tier_adjustments(shot_list, [{"tier": "C"}, {"tier": "A"}])

    assert shot_list.shots[0].tier == Tier.C
    assert shot_list.shots[1].tier == Tier.A


def test_apply_tier_adjustments_ignores_unknown_tier():
    from app.redis_worker import _apply_tier_adjustments
    from app.rfir.ir.types import CameraPath, Shot, ShotList

    shot_list = ShotList(prompt="p", shots=[
        Shot(index=0, description="one", tier=Tier.B, duration_sec=5.0, camera=CameraPath()),
    ])

    _apply_tier_adjustments(shot_list, [{"tier": "Z"}])

    assert shot_list.shots[0].tier == Tier.B


def test_apply_tier_adjustments_tolerates_short_response():
    """zip() truncation: a mismatched response must not raise."""
    from app.redis_worker import _apply_tier_adjustments
    from app.rfir.ir.types import CameraPath, Shot, ShotList

    shot_list = ShotList(prompt="p", shots=[
        Shot(index=0, description="one", tier=Tier.D, duration_sec=5.0, camera=CameraPath()),
        Shot(index=1, description="two", tier=Tier.D, duration_sec=5.0, camera=CameraPath()),
    ])

    _apply_tier_adjustments(shot_list, [])

    assert shot_list.shots[0].tier == Tier.D


def test_missing_budget_max_tier_uses_cloud_probe_default(monkeypatch):
    """When payload omits budget.max_tier, use probed cloud defaults (B offline)."""
    from app.cloud_probe import CloudDefaults, reset_cloud_defaults_cache
    import app.cloud_probe as cloud_probe

    reset_cloud_defaults_cache()
    monkeypatch.setattr(
        cloud_probe,
        "_cached",
        CloudDefaults(cloud_reachable=False, max_tier="B", cloud_allowed=False),
    )

    captured = {}

    def _plan(prompt, max_tier):
        captured["max_tier"] = max_tier
        from app.rfir.ir.types import CameraPath, Shot, ShotList

        return ShotList(prompt=prompt, shots=[
            Shot(index=0, description=prompt, tier=max_tier, duration_sec=1.0, camera=CameraPath()),
        ])

    def _build(shot_list, budget=None, routing=None, ai_enabled=True):
        captured["budget_max_tier"] = budget.max_tier
        captured["cloud_allowed"] = routing.cloud_allowed
        captured["local_only"] = routing.local_only
        raise RuntimeError("stop after compile args captured")

    monkeypatch.setattr("app.redis_worker._plan_shots", _plan)
    monkeypatch.setattr("app.rfir.compiler.builder.build", _build)

    reporter = FakeReporter()
    run_rfir_job(
        "job-default-tier",
        {"prompt": "a calm lake", "guardrail_verdict": "allow", "budget": {"max_gpu_seconds": 5.0}},
        reporter,
    )

    assert captured["max_tier"] == Tier.B
    assert captured["budget_max_tier"] == Tier.B
    assert captured["cloud_allowed"] is False
    assert captured["local_only"] is True
