"""Tests for RFIR IR types + graph validation."""
import pytest

from app.rfir.ir.types import (
    CameraMotion,
    CameraPath,
    InferenceBudget,
    RfirGraph,
    RfirNode,
    Shot,
    ShotList,
    TensorDtype,
    TensorLifetime,
    TensorSpec,
    Tier,
)
from app.rfir.ir.ops import OP_REGISTRY
from app.rfir.ir.validate import validate


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

def test_tensor_spec_nbytes():
    t = TensorSpec(name="img", dtype=TensorDtype.RGB_U8, shape=[1, 3, 288, 512])
    assert t.nbytes() == 1 * 3 * 288 * 512


def test_shot_list_total_duration():
    sl = ShotList(shots=[
        Shot(index=0, description="a", duration_sec=5.0),
        Shot(index=1, description="b", duration_sec=3.0),
    ])
    assert sl.total_duration_sec() == 8.0


def test_shot_list_tier_distribution():
    sl = ShotList(shots=[
        Shot(index=0, description="a", tier=Tier.A),
        Shot(index=1, description="b", tier=Tier.A),
        Shot(index=2, description="c", tier=Tier.B),
    ])
    dist = sl.tier_distribution()
    assert dist == {"A": 2, "B": 1}


def test_budget_can_afford():
    b = InferenceBudget(max_gpu_seconds=10.0, spent_gpu_seconds=8.0)
    assert b.can_afford(1.5) is True
    assert b.can_afford(3.0) is False


def test_budget_spend():
    b = InferenceBudget(max_gpu_seconds=10.0)
    b.spend(4.0)
    assert b.spent_gpu_seconds == 4.0
    assert b.remaining_gpu_seconds == 6.0


# ---------------------------------------------------------------------------
# Validation — valid graph
# ---------------------------------------------------------------------------

def _make_valid_tier_a_graph() -> RfirGraph:
    """Minimal valid Tier A graph: t2i → depth → parallax → upscale → mux."""
    g = RfirGraph()
    g.tensors["img"] = TensorSpec("img", TensorDtype.RGB_U8, [1, 3, 288, 512])
    g.tensors["dep"] = TensorSpec("dep", TensorDtype.DEPTH_F32, [1, 1, 288, 512])
    g.tensors["frames"] = TensorSpec("frames", TensorDtype.RGB_U8, [24, 3, 288, 512])
    g.tensors["out"] = TensorSpec("out", TensorDtype.RGB_U8, [24, 3, 1080, 1920])
    g.nodes = [
        RfirNode(id="n1", op="t2i_keyframe", outputs={"image": "img"}),
        RfirNode(id="n2", op="depth_estimate", inputs={"image": "img"}, outputs={"depth": "dep"}),
        RfirNode(id="n3", op="vulkan_parallax", inputs={"image": "img", "depth": "dep"}, outputs={"frames": "frames"}),
        RfirNode(id="n4", op="vulkan_upscale", inputs={"image": "frames"}, outputs={"image_out": "out"}),
        RfirNode(id="n5", op="ffmpeg_mux", inputs={"frames": "out"}),
    ]
    return g


def test_valid_graph_passes():
    errors = validate(_make_valid_tier_a_graph())
    assert errors == []


# ---------------------------------------------------------------------------
# Validation — unknown op
# ---------------------------------------------------------------------------

def test_unknown_op():
    g = RfirGraph(nodes=[RfirNode(id="bad", op="not_a_real_op")])
    errors = validate(g)
    assert any("unknown op" in e.message for e in errors)


# ---------------------------------------------------------------------------
# Validation — duplicate IDs
# ---------------------------------------------------------------------------

def test_duplicate_ids():
    g = RfirGraph(nodes=[
        RfirNode(id="dup", op="t2i_keyframe"),
        RfirNode(id="dup", op="depth_estimate"),
    ])
    errors = validate(g)
    assert any("duplicate" in e.message for e in errors)


# ---------------------------------------------------------------------------
# Validation — missing tensor ref
# ---------------------------------------------------------------------------

def test_missing_tensor_ref():
    g = RfirGraph(nodes=[
        RfirNode(id="n1", op="depth_estimate", inputs={"image": "nonexistent"}),
    ])
    errors = validate(g)
    assert any("unknown tensor" in e.message for e in errors)


# ---------------------------------------------------------------------------
# Validation — dtype mismatch
# ---------------------------------------------------------------------------

def test_dtype_mismatch():
    g = RfirGraph()
    g.tensors["wrong"] = TensorSpec("wrong", TensorDtype.DEPTH_F32, [1, 1, 288, 512])
    g.nodes = [
        RfirNode(id="n1", op="depth_estimate", inputs={"image": "wrong"}),
    ]
    errors = validate(g)
    assert any("expects rgb_u8" in e.message for e in errors)


# ---------------------------------------------------------------------------
# Validation — cycle detection
# ---------------------------------------------------------------------------

def test_cycle_detected():
    g = RfirGraph()
    g.tensors["a"] = TensorSpec("a", TensorDtype.RGB_U8, [1])
    g.tensors["b"] = TensorSpec("b", TensorDtype.RGB_U8, [1])
    g.nodes = [
        RfirNode(id="n1", op="vulkan_upscale", inputs={"image": "b"}, outputs={"image_out": "a"}),
        RfirNode(id="n2", op="vulkan_upscale", inputs={"image": "a"}, outputs={"image_out": "b"}),
    ]
    errors = validate(g)
    assert any("cycle" in e.message for e in errors)


# ---------------------------------------------------------------------------
# Op registry
# ---------------------------------------------------------------------------

def test_op_registry_has_all_ops():
    expected = {
        "plan_shots", "t2i_keyframe", "depth_estimate", "segment_subject",
        "vae_encode", "vae_decode", "sparse_t2v_window", "rife_interpolate",
        "vulkan_parallax", "vulkan_upscale", "vulkan_composite",
        "vulkan_motion_blur", "ffmpeg_mux",
    }
    assert expected.issubset(set(OP_REGISTRY.keys()))
