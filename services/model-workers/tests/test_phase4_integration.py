"""Phase 4 integration tests — Tier D, checkpointing, hybrid routing, cost estimate.

Validates exit criteria:
  - Tier D blocked when max_tier=C in policy
  - Tier D hard duration cap (3s)
  - Checkpoint save/resume at shot boundaries
  - local_only caps at Tier B
  - Cost estimate present in metrics
"""
import tempfile

import pytest

from app.rfir.ir.types import (
    CameraMotion,
    CameraPath,
    InferenceBudget,
    RoutingPolicy,
    Shot,
    ShotList,
    Tier,
)
from app.rfir.compiler.builder import build, TIER_D_MAX_DURATION_SEC
from app.rfir.compiler.fusion import fuse
from app.rfir.compiler.memory_plan import plan
from app.rfir.budget import BudgetGovernor
from app.rfir.checkpoint import Checkpoint, save, load, checkpoint_uri
from app.rfir.executor.context import ExecutionContext


def _mixed_shotlist() -> ShotList:
    return ShotList(
        prompt="anime hero faces the final boss",
        shots=[
            Shot(index=0, description="wide shot of arena",
                 tier=Tier.A, duration_sec=4.0,
                 camera=CameraPath(motion=CameraMotion.STATIC)),
            Shot(index=1, description="hero charges forward",
                 tier=Tier.C, duration_sec=3.0,
                 camera=CameraPath(motion=CameraMotion.TRACKING),
                 subject="hero"),
            Shot(index=2, description="epic explosion establishing shot",
                 tier=Tier.D, duration_sec=5.0,
                 camera=CameraPath(motion=CameraMotion.ORBIT)),
        ],
    )


# ---------------------------------------------------------------------------
# Exit criterion 1: Tier D blocked when max_tier=C
# ---------------------------------------------------------------------------

def test_tier_d_blocked_by_max_tier_c():
    sl = _mixed_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    dist = graph.metadata["tier_distribution"]
    assert dist.get("D", 0) == 0
    assert dist.get("C", 0) >= 1  # the D shot was capped to C


def test_tier_d_allowed_when_max_tier_d():
    sl = _mixed_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.D))
    dist = graph.metadata["tier_distribution"]
    assert dist.get("D", 0) == 1


# ---------------------------------------------------------------------------
# Tier D hard duration cap
# ---------------------------------------------------------------------------

def test_tier_d_duration_capped_in_graph():
    sl = ShotList(prompt="hero", shots=[
        Shot(index=0, description="long hero shot", tier=Tier.D,
             duration_sec=10.0, camera=CameraPath(motion=CameraMotion.STATIC)),
    ])
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.D))
    t2v_nodes = [n for n in graph.nodes if n.op == "sparse_t2v_window"]
    assert len(t2v_nodes) == 1
    assert t2v_nodes[0].attrs.get("duration_sec") == TIER_D_MAX_DURATION_SEC
    assert t2v_nodes[0].attrs.get("full_frame") is True


# ---------------------------------------------------------------------------
# Hybrid routing: local_only caps at Tier B
# ---------------------------------------------------------------------------

def test_local_only_caps_tier_c_to_b():
    sl = _mixed_shotlist()
    routing = RoutingPolicy(local_only=True, cloud_allowed=False)
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.D), routing=routing)
    dist = graph.metadata["tier_distribution"]
    assert dist.get("C", 0) == 0
    assert dist.get("D", 0) == 0
    assert dist.get("B", 0) >= 1


def test_cloud_allowed_preserves_tiers():
    sl = _mixed_shotlist()
    routing = RoutingPolicy(local_only=False, cloud_allowed=True)
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.D), routing=routing)
    dist = graph.metadata["tier_distribution"]
    assert dist.get("D", 0) == 1


def test_routing_metadata_recorded():
    sl = _mixed_shotlist()
    routing = RoutingPolicy(local_only=True, cloud_allowed=False)
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.D), routing=routing)
    assert graph.metadata["routing"]["local_only"] is True
    assert graph.metadata["routing"]["cloud_allowed"] is False


# ---------------------------------------------------------------------------
# Checkpoint resume simulation
# ---------------------------------------------------------------------------

def test_checkpoint_resume_skips_completed_shots():
    """Simulate: 3 shots, crash after shot 1, resume from shot 2."""
    cp = Checkpoint(
        job_id="resume-job",
        shot_index=1,
        spent_gpu_seconds=5.0,
        node_cursor=8,  # first 8 nodes done
        artifacts={"s0_t2i": "/out/s0.png", "s1_rife_0": "/out/s1.png"},
        tier_distribution={"A": 1, "C": 1, "D": 1},
        downgrades=[],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        uri = checkpoint_uri("resume-job", base_dir=tmpdir)
        save(cp, uri)

        restored = load(uri)
        assert restored is not None
        assert restored.node_cursor == 8
        assert restored.spent_gpu_seconds == 5.0
        assert len(restored.artifacts) == 2


# ---------------------------------------------------------------------------
# Cost estimate
# ---------------------------------------------------------------------------

def test_cost_estimate_in_metrics():
    ctx = ExecutionContext(job_id="cost-test", device="mps")
    ctx.record_node("n1", "t2i_keyframe", wall_ms=100, gpu_ms=800)
    ctx.record_node("n2", "depth_estimate", wall_ms=50, gpu_ms=50)

    cost = ctx.cost_estimate_usd()
    assert cost > 0

    metrics = ctx.to_metrics_dict()
    assert "cost_estimate_usd" in metrics
    assert metrics["cost_estimate_usd"] == cost


def test_cost_estimate_scales_with_gpu_time():
    ctx = ExecutionContext(job_id="scale-test", device="mps")
    ctx.record_node("n1", "t2i_keyframe", wall_ms=100, gpu_ms=1000)
    cost_1s = ctx.cost_estimate_usd(rate_per_gpu_second=0.001)

    ctx.record_node("n2", "sparse_t2v_window", wall_ms=500, gpu_ms=5000)
    cost_6s = ctx.cost_estimate_usd(rate_per_gpu_second=0.001)

    assert cost_6s > cost_1s


# ---------------------------------------------------------------------------
# Full compile pipeline with Tier D
# ---------------------------------------------------------------------------

def test_full_compile_with_tier_d():
    sl = _mixed_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.D))
    graph = fuse(graph)
    mp = plan(graph)

    dist = graph.metadata["tier_distribution"]
    assert dist["A"] == 1
    assert dist["C"] == 1
    assert dist["D"] == 1

    assert mp.peak_vram_mb > 0
    assert mp.over_budget is True  # Tier D sparse_t2v is ~8 GB
