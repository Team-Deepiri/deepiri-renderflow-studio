"""Tests for RFIR compiler memory planning pass (§2.2)."""
import pytest

from app.rfir.ir.types import (
    RfirGraph,
    RfirNode,
    Shot,
    ShotList,
    TensorDtype,
    TensorSpec,
    Tier,
    InferenceBudget,
)
from app.rfir.compiler.builder import build
from app.rfir.compiler.memory_plan import plan


def _rgb(name: str) -> TensorSpec:
    return TensorSpec(name=name, dtype=TensorDtype.RGB_U8, shape=[1, 3, 288, 512])


_RGB_MB = _rgb("x").nbytes() / (1024 * 1024)  # ~0.422 MB


def _linear_graph() -> RfirGraph:
    """A -> x -> B -> y ; vram A=1000, B=2000."""
    g = RfirGraph(tensors={"x": _rgb("x"), "y": _rgb("y")})
    g.nodes = [
        RfirNode(id="A", op="t2i_keyframe", outputs={"image": "x"}, vram_mb=1000.0),
        RfirNode(id="B", op="depth_estimate", inputs={"image": "x"}, outputs={"depth": "y"}, vram_mb=2000.0),
    ]
    return g


# ---------------------------------------------------------------------------
# Peak VRAM math
# ---------------------------------------------------------------------------

def test_peak_vram_exact():
    g = _linear_graph()
    mp = plan(g, order=["A", "B"], vram_limit_mb=10_000)
    # step 0: x live (0.422) + A working (1000) = 1000.422
    # step 1: x + y live (0.844) + B working (2000) = 2000.844  ← peak
    assert mp.peak_step == 1
    assert mp.peak_vram_mb == pytest.approx(2000.0 + 2 * _RGB_MB, rel=1e-6)
    assert mp.per_step_mb[0] == pytest.approx(1000.0 + _RGB_MB, rel=1e-6)


def test_peak_is_max_of_per_step():
    g = _linear_graph()
    mp = plan(g)
    assert mp.peak_vram_mb == max(mp.per_step_mb)


def test_order_defaults_to_topological_sort():
    g = _linear_graph()
    mp = plan(g)  # no order passed
    assert mp.peak_step == 1  # B still runs last


# ---------------------------------------------------------------------------
# Liveness: a tensor stops counting after its last consumer
# ---------------------------------------------------------------------------

def test_dead_tensor_not_counted():
    # C consumes x at step 1 then z lives alone; x must not inflate step 2.
    g = RfirGraph(tensors={"x": _rgb("x"), "y": _rgb("y"), "z": _rgb("z")})
    g.nodes = [
        RfirNode(id="A", op="t2i_keyframe", outputs={"image": "x"}, vram_mb=100.0),
        RfirNode(id="B", op="depth_estimate", inputs={"image": "x"}, outputs={"depth": "y"}, vram_mb=100.0),
        RfirNode(id="C", op="vulkan_upscale", inputs={"image": "y"}, outputs={"image_out": "z"}, vram_mb=100.0),
    ]
    mp = plan(g, order=["A", "B", "C"], vram_limit_mb=10_000)
    # step 2 (C): only y and z live (x is dead after step 1) → 100 + 2*_RGB_MB
    assert mp.per_step_mb[2] == pytest.approx(100.0 + 2 * _RGB_MB, rel=1e-6)


# ---------------------------------------------------------------------------
# Downgrade hints
# ---------------------------------------------------------------------------

def test_no_hints_when_under_budget():
    g = _linear_graph()
    mp = plan(g, vram_limit_mb=5000)
    assert mp.over_budget is False
    assert mp.downgrade_hints == []


def test_hints_emitted_when_over_budget():
    g = _linear_graph()
    mp = plan(g, vram_limit_mb=1500)  # step 1 (2000) exceeds
    assert mp.over_budget is True
    assert mp.downgrade_hints == ["B"]  # only the over-budget step's node


def test_hints_sorted_heaviest_first():
    g = RfirGraph(tensors={"x": _rgb("x"), "y": _rgb("y"), "z": _rgb("z")})
    g.nodes = [
        RfirNode(id="light", op="t2i_keyframe", outputs={"image": "x"}, vram_mb=9000.0),
        RfirNode(id="heavy", op="sparse_t2v_window",
                 inputs={"latent": "x"}, outputs={"latent_out": "y"}, vram_mb=11000.0),
        RfirNode(id="mid", op="depth_estimate",
                 inputs={"image": "y"}, outputs={"depth": "z"}, vram_mb=10000.0),
    ]
    mp = plan(g, order=["light", "heavy", "mid"], vram_limit_mb=8000)
    assert mp.downgrade_hints == ["heavy", "mid", "light"]


# ---------------------------------------------------------------------------
# Integration with real built graphs
# ---------------------------------------------------------------------------

def test_tier_c_graph_over_default_budget():
    graph = build(ShotList(prompt="action", shots=[
        Shot(index=0, description="hero running", tier=Tier.C, duration_sec=5.0, subject="hero"),
    ]))
    mp = plan(graph)  # default 7500 limit; sparse_t2v_window is 10240
    assert mp.over_budget is True
    assert mp.peak_vram_mb >= 10240
    t2v = [n.id for n in graph.nodes if n.op == "sparse_t2v_window"]
    assert any(tid in mp.downgrade_hints for tid in t2v)


def test_tier_a_graph_under_budget():
    graph = build(ShotList(prompt="calm", shots=[
        Shot(index=0, description="sunrise", tier=Tier.A, duration_sec=5.0),
    ]), budget=InferenceBudget(max_tier=Tier.A))
    mp = plan(graph)  # heaviest node is t2i at 6144 < 7500
    assert mp.over_budget is False
    assert mp.downgrade_hints == []
