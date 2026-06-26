"""Phase 2 integration test — validates the full compile pipeline without GPU.

Checks exit criteria:
  - Mixed Tier A + B graph compiles and fuses correctly
  - tier_distribution present in metadata
  - Automatic downgrade when max_gpu_seconds is low
  - Metrics JSON has the right shape
"""
from app.rfir.ir.types import (
    CameraMotion,
    CameraPath,
    InferenceBudget,
    Shot,
    ShotList,
    Tier,
)
from app.rfir.compiler.builder import build
from app.rfir.compiler.fusion import fuse
from app.rfir.compiler.memory_plan import plan
from app.rfir.budget import BudgetGovernor
from app.rfir.router import assign_tiers


def _sample_shotlist() -> ShotList:
    return ShotList(
        prompt="a hero runs through a forest at dawn",
        shots=[
            Shot(index=0, description="wide establishing shot of a misty forest",
                 tier=Tier.A, duration_sec=5.0,
                 camera=CameraPath(motion=CameraMotion.STATIC)),
            Shot(index=1, description="hero walking down a trail",
                 tier=Tier.B, duration_sec=4.0,
                 camera=CameraPath(motion=CameraMotion.TRACKING)),
            Shot(index=2, description="close-up of sunlight through leaves",
                 tier=Tier.A, duration_sec=3.0,
                 camera=CameraPath(motion=CameraMotion.ZOOM)),
            Shot(index=3, description="hero running across a clearing",
                 tier=Tier.B, duration_sec=4.0,
                 camera=CameraPath(motion=CameraMotion.PAN)),
        ],
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def test_router_assigns_tiers():
    sl = _sample_shotlist()
    for s in sl.shots:
        s.tier = Tier.A  # reset
    assign_tiers(sl, max_tier=Tier.B)
    tiers = [s.tier for s in sl.shots]
    assert all(t in (Tier.A, Tier.B) for t in tiers)
    dist = sl.tier_distribution()
    assert "A" in dist or "B" in dist


# ---------------------------------------------------------------------------
# Build + Fuse
# ---------------------------------------------------------------------------

def test_build_mixed_tier_a_b():
    sl = _sample_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.B))
    assert "tier_distribution" in graph.metadata
    dist = graph.metadata["tier_distribution"]
    assert dist.get("A", 0) + dist.get("B", 0) == len(sl.shots)


def test_fusion_batches_t2i_nodes():
    sl = _sample_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.B))
    t2i_before = sum(1 for n in graph.nodes if n.op == "t2i_keyframe")
    graph = fuse(graph)
    t2i_after = sum(1 for n in graph.nodes if n.op == "t2i_keyframe")
    assert "fusion" in graph.metadata
    if t2i_before >= 2:
        assert t2i_after < t2i_before


# ---------------------------------------------------------------------------
# Memory plan
# ---------------------------------------------------------------------------

def test_memory_plan_produces_per_step_data():
    sl = _sample_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.B))
    graph = fuse(graph)
    mp = plan(graph)
    assert mp.peak_vram_mb > 0
    assert len(mp.per_step_mb) > 0
    assert mp.peak_vram_mb == max(mp.per_step_mb)


# ---------------------------------------------------------------------------
# Budget governor — automatic downgrade
# ---------------------------------------------------------------------------

def test_downgrade_on_tight_budget():
    sl = _sample_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.B))
    graph = fuse(graph)
    mp = plan(graph)

    gov = BudgetGovernor(
        InferenceBudget(max_gpu_seconds=2.0),
        vram_hints=mp.downgrade_hints,
    )

    downgraded_ids = []
    for node in graph.nodes:
        out = gov.before_node(node)
        gov.after_node(out.estimated_gpu_ms / 1000.0)
        if out is not node:
            downgraded_ids.append(node.id)

    assert len(gov.downgrades) > 0, "tight budget should trigger at least one downgrade"
    metrics = gov.metrics()
    assert "downgrades" in metrics
    assert "spent_gpu_seconds" in metrics


def test_no_downgrade_on_generous_budget():
    sl = _sample_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.B))
    graph = fuse(graph)

    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=600.0))

    for node in graph.nodes:
        out = gov.before_node(node)
        gov.after_node(out.estimated_gpu_ms / 1000.0)

    assert len(gov.downgrades) == 0


# ---------------------------------------------------------------------------
# Full pipeline: metrics JSON shape
# ---------------------------------------------------------------------------

def test_metrics_json_shape():
    sl = _sample_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.B))
    graph = fuse(graph)
    mp = plan(graph)

    gov = BudgetGovernor(
        InferenceBudget(max_gpu_seconds=3.0),
        vram_hints=mp.downgrade_hints,
    )
    for node in graph.nodes:
        out = gov.before_node(node)
        gov.after_node(out.estimated_gpu_ms / 1000.0)

    metrics = gov.metrics()
    assert "max_gpu_seconds" in metrics
    assert "spent_gpu_seconds" in metrics
    assert "remaining_gpu_seconds" in metrics
    assert "downgrade_count" in metrics
    assert isinstance(metrics["downgrades"], list)
    for d in metrics["downgrades"]:
        assert "node_id" in d
        assert "op" in d
        assert "trigger" in d
        assert "reason" in d
        assert "before_ms" in d
        assert "after_ms" in d

    assert "tier_distribution" in graph.metadata
