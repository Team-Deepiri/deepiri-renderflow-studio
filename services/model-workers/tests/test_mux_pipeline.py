"""Tests for the RFIR mux pipeline: shot manifest, variadic mux ports,
duration-dependent cost estimates, ordering-only memory planning,
per-shot frame persistence, and the real ffmpeg concat.

Spec reference: docs/specs/rfir-mp4-output-pipeline.md §6 Steps 1, 3, 4, §8.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from app.rfir.arena import TensorArena
from app.rfir.compiler.builder import build
from app.rfir.compiler.fusion import fuse
from app.rfir.compiler.memory_plan import plan
from app.rfir.executor import engine
from app.rfir.executor.context import ExecutionContext
from app.rfir.ir.types import CameraMotion, CameraPath, InferenceBudget, RfirNode, Shot, ShotList, Tier
from app.rfir.ops import ffmpeg_mux

ffmpeg_required = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not found in PATH")


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


# ---------------------------------------------------------------------------
# _persist_frames (Step 3)
# ---------------------------------------------------------------------------

def test_persist_frames_zero_pads_for_numeric_order(tmp_path):
    ctx = ExecutionContext(job_id="j")
    frames = [Image.new("RGB", (4, 4), (i, i, i)) for i in range(11)]
    frame_dir = engine._persist_frames(frames, "s0_upscaled", ctx, tmp_path)

    names = sorted(p.name for p in (tmp_path / "frames" / "s0_upscaled").iterdir())
    assert names == [f"{i:05d}.png" for i in range(11)]
    assert ctx.artifacts["frames::s0_upscaled"] == frame_dir


def test_persist_frames_writes_under_frames_subdir_not_root(tmp_path):
    ctx = ExecutionContext(job_id="j")
    engine._persist_frames([Image.new("RGB", (2, 2))], "s0_upscaled", ctx, tmp_path)
    assert not list(tmp_path.glob("*.png"))


def test_vulkan_upscale_stub_persists_list_and_releases_arena(tmp_path):
    arena = TensorArena()
    ctx = ExecutionContext(job_id="j")
    frames = [Image.new("RGB", (2, 2)) for _ in range(3)]
    arena.put("s0_interp", frames)
    node = RfirNode(id="s0_upscale", op="vulkan_upscale",
                     inputs={"image": "s0_interp"}, outputs={"image_out": "s0_upscaled"})

    engine._run_vulkan_upscale_stub(node, arena, ctx, tmp_path)

    assert "frames::s0_upscaled" in ctx.artifacts
    assert not arena.has("s0_upscaled")
    assert not arena.has("s0_interp")


def test_vulkan_upscale_stub_leaves_single_still_in_arena(tmp_path):
    """Tier A's terminal tensor is a single image, not a list — nothing to
    persist as a frame dir; the mux falls back to the s{N}_t2i still."""
    arena = TensorArena()
    ctx = ExecutionContext(job_id="j")
    img = Image.new("RGB", (2, 2))
    arena.put("s0_parallax", img)
    node = RfirNode(id="s0_upscale", op="vulkan_upscale",
                     inputs={"image": "s0_parallax"}, outputs={"image_out": "s0_upscaled"})

    engine._run_vulkan_upscale_stub(node, arena, ctx, tmp_path)

    assert "frames::s0_upscaled" not in ctx.artifacts
    assert arena.has("s0_upscaled")


# ---------------------------------------------------------------------------
# ops.ffmpeg_mux.run — real ffmpeg (Step 4)
# ---------------------------------------------------------------------------

@ffmpeg_required
def test_ffmpeg_mux_missing_shot_emits_black_segment_and_logs_error(tmp_path, caplog):
    shots = [
        {"index": 0, "output_tensor": "s0_upscaled", "effective_duration_sec": 1.0, "fps": 8,
         "camera": "static", "camera_speed": 1.0},
    ]
    with caplog.at_level("ERROR"):
        result = ffmpeg_mux.run(shots, frame_dirs={}, stills={}, out_path=tmp_path, fps=8, width=64, height=64)

    assert result is not None
    assert (tmp_path / "output.mp4").exists()
    assert any("black segment" in r.message for r in caplog.records)


@ffmpeg_required
def test_ffmpeg_mux_still_and_frame_dir_concat_single_pass(tmp_path, monkeypatch):
    still_path = tmp_path / "still.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(still_path)

    frame_dir = tmp_path / "frames" / "s1_upscaled"
    frame_dir.mkdir(parents=True)
    for i in range(4):
        Image.new("RGB", (64, 64), (i * 10, 0, 0)).save(frame_dir / f"{i:05d}.png")

    shots = [
        {"index": 0, "output_tensor": "s0_upscaled", "effective_duration_sec": 0.5, "fps": 8,
         "camera": "zoom", "camera_speed": 1.0},
        {"index": 1, "output_tensor": "s1_upscaled", "effective_duration_sec": 0.5, "fps": 8,
         "camera": "static", "camera_speed": 1.0},
    ]
    stills = {"s0_upscaled": str(still_path)}
    frame_dirs = {"s1_upscaled": str(frame_dir)}

    calls = []
    import subprocess as sp
    real_run = sp.run

    def _spy(cmd, **kw):
        calls.append(cmd)
        return real_run(cmd, **kw)

    monkeypatch.setattr(ffmpeg_mux.subprocess, "run", _spy)

    result = ffmpeg_mux.run(shots, frame_dirs, stills, tmp_path, fps=8, width=64, height=64)

    assert result is not None
    assert len(calls) == 1, "expected exactly one ffmpeg invocation"
    assert Path(result).exists()


# ---------------------------------------------------------------------------
# engine._run_ffmpeg_mux adapter (Step 4)
# ---------------------------------------------------------------------------

@ffmpeg_required
def test_run_ffmpeg_mux_adapter_reads_from_disk_not_arena(tmp_path):
    """Decision 5: the mux reads ctx.artifacts (disk), never the arena — a
    resumed job whose arena is empty for completed shots must still mux."""
    ctx = ExecutionContext(job_id="j")
    still_path = tmp_path / "s0_t2i.png"
    Image.new("RGB", (32, 32), (5, 5, 5)).save(still_path)
    ctx.artifacts["s0_t2i"] = str(still_path)

    node = RfirNode(
        id="mux", op="ffmpeg_mux",
        inputs={"frames_0": "s0_upscaled"},
        attrs={
            "fps": 8, "width": 32, "height": 32,
            "shots": [{"index": 0, "output_tensor": "s0_upscaled",
                       "effective_duration_sec": 0.25, "fps": 8,
                       "camera": "static", "camera_speed": 1.0}],
        },
    )
    arena = TensorArena()  # deliberately empty — simulates post-resume state

    engine._run_ffmpeg_mux(node, arena, ctx, tmp_path)

    assert "output_mp4" in ctx.artifacts
    assert Path(ctx.artifacts["output_mp4"]).exists()
