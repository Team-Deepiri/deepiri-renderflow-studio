"""Tests for the Step 1 mux pipeline: shot manifest, variadic mux ports,
duration-dependent cost estimates, and ordering-only memory planning.

Spec reference: docs/specs/rfir-mp4-output-pipeline.md §6 Step 1, §8.
"""
from __future__ import annotations

import pytest

from app.rfir.compiler.builder import build
from app.rfir.compiler.fusion import fuse
from app.rfir.compiler.memory_plan import plan
from app.rfir.ir.types import CameraMotion, CameraPath, InferenceBudget, Shot, ShotList, Tier


def _mixed_shot_list() -> ShotList:
    return ShotList(prompt="p", shots=[
        Shot(index=0, description="a", tier=Tier.A, duration_sec=2.0,
             camera=CameraPath(motion=CameraMotion.STATIC)),
        Shot(index=1, description="b", tier=Tier.B, duration_sec=1.0,
             camera=CameraPath(motion=CameraMotion.PAN)),
        Shot(index=2, description="c", tier=Tier.D, duration_sec=5.0,
             camera=CameraPath(motion=CameraMotion.ZOOM)),
    ])


# ---------------------------------------------------------------------------
# Builder: manifest + variadic mux ports (Step 1)
# ---------------------------------------------------------------------------

def test_mux_has_one_port_per_shot():
    graph = build(_mixed_shot_list(), budget=InferenceBudget(max_tier=Tier.D))
    mux = graph.get_node("mux")
    assert set(mux.inputs.keys()) == {"frames_0", "frames_1", "frames_2"}


def test_manifest_on_mux_attrs_is_json_serializable():
    import json

    graph = build(_mixed_shot_list(), budget=InferenceBudget(max_tier=Tier.D))
    mux = graph.get_node("mux")
    shots = mux.attrs["shots"]
    assert len(shots) == 3
    json.dumps(shots)  # must not raise


def test_manifest_effective_duration_caps_tier_d():
    """Tier D caps at 3s (Decision 6): a 5s shot's effective_duration_sec
    must reflect the cap, while duration_sec keeps what the planner asked."""
    graph = build(_mixed_shot_list(), budget=InferenceBudget(max_tier=Tier.D))
    mux = graph.get_node("mux")
    shot_2 = next(s for s in mux.attrs["shots"] if s["index"] == 2)
    assert shot_2["duration_sec"] == 5.0
    assert shot_2["effective_duration_sec"] == 3.0
    assert shot_2["num_frames"] == round(3.0 * 24)


def test_manifest_output_tensor_matches_upscaled_tensor():
    graph = build(_mixed_shot_list(), budget=InferenceBudget(max_tier=Tier.D))
    mux = graph.get_node("mux")
    for shot in mux.attrs["shots"]:
        assert shot["output_tensor"] == f"s{shot['index']}_upscaled"


def test_rife_estimated_gpu_ms_scales_with_duration():
    short = build(ShotList(prompt="p", shots=[
        Shot(index=0, description="a", tier=Tier.B, duration_sec=1.0),
    ]))
    long = build(ShotList(prompt="p", shots=[
        Shot(index=0, description="a", tier=Tier.B, duration_sec=8.0),
    ]))
    short_rife = short.get_node("s0_rife")
    long_rife = long.get_node("s0_rife")
    assert long_rife.estimated_gpu_ms > short_rife.estimated_gpu_ms


def test_manifest_survives_fusion():
    """The mux node is not a fusion candidate, so its attrs must survive
    fuse() unchanged (§6 Step 1)."""
    sl = ShotList(prompt="p", shots=[
        Shot(index=0, description="a", tier=Tier.A, duration_sec=2.0),
        Shot(index=1, description="b", tier=Tier.A, duration_sec=3.0),
    ])
    graph = build(sl)
    before = graph.get_node("mux").attrs["shots"]
    graph = fuse(graph)
    after = graph.get_node("mux").attrs["shots"]
    assert after == before


# ---------------------------------------------------------------------------
# memory_plan: ffmpeg_mux inputs are ordering-only (Decision 5)
# ---------------------------------------------------------------------------

def test_memory_plan_peak_vram_does_not_scale_with_shot_count():
    one_shot = build(ShotList(prompt="p", shots=[
        Shot(index=0, description="a", tier=Tier.C, subject="hero"),
    ]))
    three_shots = build(ShotList(prompt="p", shots=[
        Shot(index=i, description="a", tier=Tier.C, subject="hero") for i in range(3)
    ]))
    mp1 = plan(one_shot)
    mp3 = plan(three_shots)
    # If the mux's frames_i inputs extended tensor liveness, peak VRAM for 3
    # concurrently-live Tier C frame lists would dwarf a single shot's.
    assert mp3.peak_vram_mb == pytest.approx(mp1.peak_vram_mb, rel=0.05)
