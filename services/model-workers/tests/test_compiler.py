"""Tests for RFIR compiler — builder + scheduler."""
import json

import pytest

from app.rfir.ir.types import (
    CameraMotion,
    CameraPath,
    InferenceBudget,
    Shot,
    ShotList,
    Tier,
)
from app.rfir.ir.validate import validate
from app.rfir.compiler.builder import CompileError, build
from app.rfir.compiler.scheduler import CycleError, schedule_with_barriers, topological_sort


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _3_shot_list() -> ShotList:
    return ShotList(
        prompt="A cinematic nature documentary",
        shots=[
            Shot(
                index=0, description="Sunrise over mountains",
                tier=Tier.A, duration_sec=5.0,
                camera=CameraPath(motion=CameraMotion.PAN),
            ),
            Shot(
                index=1, description="Eagle soaring through clouds",
                tier=Tier.B, duration_sec=4.0,
                camera=CameraPath(motion=CameraMotion.TRACKING),
            ),
            Shot(
                index=2, description="Close-up of flowing river",
                tier=Tier.A, duration_sec=3.0,
                camera=CameraPath(motion=CameraMotion.DOLLY),
            ),
        ],
    )


def _single_tier_c() -> ShotList:
    return ShotList(
        prompt="Action scene",
        shots=[
            Shot(
                index=0, description="Hero running through city",
                tier=Tier.C, duration_sec=5.0,
                subject="hero",
            ),
        ],
    )


def _single_tier_d() -> ShotList:
    return ShotList(
        prompt="Hero shot",
        shots=[
            Shot(index=0, description="Dramatic reveal", tier=Tier.D, duration_sec=3.0),
        ],
    )


# ---------------------------------------------------------------------------
# Builder tests
# ---------------------------------------------------------------------------

def test_build_3_shot_valid():
    graph = build(_3_shot_list())
    errors = validate(graph)
    assert errors == [], f"Validation errors: {errors}"


def test_build_3_shot_node_count():
    graph = build(_3_shot_list())
    # Tier A: 4 nodes, Tier B: 4 nodes, Tier A: 4 nodes, + 1 mux = 13
    assert len(graph.nodes) == 13


def test_build_3_shot_metadata():
    graph = build(_3_shot_list())
    assert graph.metadata["shot_count"] == 3
    assert graph.metadata["total_duration_sec"] == 12.0


def test_build_tier_c_valid():
    graph = build(_single_tier_c())
    errors = validate(graph)
    assert errors == [], f"Validation errors: {errors}"


def test_build_tier_c_has_segment_and_composite():
    graph = build(_single_tier_c())
    ops = [n.op for n in graph.nodes]
    assert "segment_subject" in ops
    assert "vulkan_composite" in ops
    assert "sparse_t2v_window" in ops


def test_build_tier_d_valid():
    graph = build(_single_tier_d(), budget=InferenceBudget(max_tier=Tier.D))
    errors = validate(graph)
    assert errors == [], f"Validation errors: {errors}"


def test_build_tier_d_has_full_frame_t2v():
    graph = build(_single_tier_d(), budget=InferenceBudget(max_tier=Tier.D))
    t2v_nodes = [n for n in graph.nodes if n.op == "sparse_t2v_window"]
    assert len(t2v_nodes) == 1
    assert t2v_nodes[0].attrs.get("full_frame") is True


def test_build_empty_shot_list_raises():
    with pytest.raises(CompileError, match="empty"):
        build(ShotList())


def test_build_ai_disabled_raises():
    with pytest.raises(CompileError, match="AI is disabled"):
        build(_3_shot_list(), ai_enabled=False)


def test_tier_cap_downgrades():
    shots = ShotList(shots=[
        Shot(index=0, description="test", tier=Tier.D, duration_sec=3.0),
    ])
    budget = InferenceBudget(max_tier=Tier.B)
    graph = build(shots, budget=budget)
    ops = [n.op for n in graph.nodes]
    assert "sparse_t2v_window" not in ops
    assert "rife_interpolate" in ops


def test_graph_serializable_to_json():
    graph = build(_3_shot_list())
    data = {
        "nodes": [
            {"id": n.id, "op": n.op, "inputs": n.inputs, "outputs": n.outputs, "attrs": n.attrs}
            for n in graph.nodes
        ],
        "tensors": {k: {"dtype": v.dtype.value, "shape": v.shape} for k, v in graph.tensors.items()},
        "metadata": graph.metadata,
    }
    serialized = json.dumps(data)
    assert len(serialized) > 100
    parsed = json.loads(serialized)
    assert parsed["metadata"]["shot_count"] == 3


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------

def test_topological_sort_order():
    graph = build(_3_shot_list())
    order = topological_sort(graph)
    assert len(order) == len(graph.nodes)
    # Every dependency should come before its dependent
    id_to_idx = {nid: i for i, nid in enumerate(order)}
    for node in graph.nodes:
        for tensor_name in node.inputs.values():
            for other in graph.nodes:
                if tensor_name in other.outputs.values():
                    assert id_to_idx[other.id] < id_to_idx[node.id], \
                        f"{other.id} should come before {node.id}"


def test_schedule_has_barriers():
    graph = build(_3_shot_list())
    schedule = schedule_with_barriers(graph)
    barriers = [s for s in schedule if s.startswith("barrier:")]
    assert len(barriers) > 0


def test_schedule_barrier_between_cuda_and_vulkan():
    graph = build(_3_shot_list())
    schedule = schedule_with_barriers(graph)
    assert any("cuda→vulkan" in b for b in schedule)
