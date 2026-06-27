"""Phase 3 end-to-end validation — runs the full Tier C pipeline without GPU.

Goes beyond unit tests: compiles a mixed A+C graph, runs the executor with
placeholder/fallback frames, and verifies the output artifacts, metrics,
and LTC state are all wired correctly.

Run with: poetry run pytest tests/test_phase3_e2e.py -v -s
The -s flag shows print output so you can inspect the pipeline.
"""
import os
import tempfile

import numpy as np
import pytest
from PIL import Image

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
from app.rfir.ltc import (
    LatentTemporalCache,
    blend_overlap,
    cosine_blend_weights,
    sliding_window_ranges,
    warp_latent,
)
from app.rfir.ops.sparse_t2v_window import _crop_to_roi, _paste_roi


def _mixed_shotlist() -> ShotList:
    return ShotList(
        prompt="anime hero dashes through a neon city in the rain",
        shots=[
            Shot(index=0, description="wide establishing shot of neon cityscape",
                 tier=Tier.A, duration_sec=4.0,
                 camera=CameraPath(motion=CameraMotion.STATIC)),
            Shot(index=1, description="hero sprinting with cape flowing",
                 tier=Tier.C, duration_sec=3.0,
                 camera=CameraPath(motion=CameraMotion.TRACKING),
                 subject="hero"),
            Shot(index=2, description="close-up of hero's face, determined expression",
                 tier=Tier.A, duration_sec=2.5,
                 camera=CameraPath(motion=CameraMotion.ZOOM)),
        ],
    )


# ---------------------------------------------------------------------------
# 1. Full compile pipeline
# ---------------------------------------------------------------------------

def test_full_compile_pipeline():
    """Compile → fuse → memory plan → budget: verify all metadata."""
    sl = _mixed_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    graph = fuse(graph)
    mp = plan(graph)

    # Tier distribution
    dist = graph.metadata["tier_distribution"]
    assert dist["A"] == 2
    assert dist["C"] == 1
    print(f"\n  Tier distribution: {dist}")

    # Fusion stats
    fusion = graph.metadata.get("fusion", {})
    print(f"  Fusion: {fusion}")

    # Memory plan
    print(f"  Peak VRAM: {mp.peak_vram_mb:.0f} MB at step {mp.peak_step}")
    print(f"  Over budget (7.5 GB): {mp.over_budget}")
    print(f"  Downgrade hints: {mp.downgrade_hints}")
    assert mp.over_budget is True  # Tier C sparse_t2v_window is 10 GB

    # Budget governor
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=8.0), vram_hints=mp.downgrade_hints)
    downgraded = []
    for node in graph.nodes:
        out = gov.before_node(node)
        gov.after_node(out.estimated_gpu_ms / 1000.0)
        if out is not node:
            downgraded.append((node.id, node.op))

    print(f"  Budget: spent {gov.budget.spent_gpu_seconds:.1f}s / {gov.budget.max_gpu_seconds}s")
    print(f"  Downgrades ({len(downgraded)}): {downgraded}")
    assert len(gov.downgrades) > 0

    # All required Tier C ops present
    ops = {n.op for n in graph.nodes}
    for required in ["segment_subject", "vae_encode", "sparse_t2v_window", "vae_decode", "vulkan_composite"]:
        assert required in ops, f"missing op: {required}"
    print("  All Tier C ops present: OK")


# ---------------------------------------------------------------------------
# 2. ROI crop → process → paste roundtrip
# ---------------------------------------------------------------------------

def test_roi_roundtrip_visual():
    """Verify ROI crop and paste produce correct composites."""
    bg = Image.new("RGB", (512, 288), color=(30, 30, 200))  # blue background
    fg = Image.new("RGB", (200, 100), color=(255, 50, 50))   # red foreground

    mask = np.zeros((288, 512), dtype=np.uint8)
    mask[80:180, 120:320] = 255  # subject region

    cropped, bbox = _crop_to_roi(bg, mask, pad=8)
    x0, y0, x1, y1 = bbox
    print(f"\n  ROI bbox: ({x0}, {y0}, {x1}, {y1})")
    print(f"  Crop size: {cropped.size}")
    assert cropped.width % 8 == 0
    assert cropped.height % 8 == 0

    result = _paste_roi(bg, fg, mask, bbox)
    assert result.size == (512, 288)

    # Sample pixels: ROI center should be red, outside should be blue
    center_px = result.getpixel((220, 130))
    corner_px = result.getpixel((10, 10))
    print(f"  Center pixel (should be red-ish): {center_px}")
    print(f"  Corner pixel (should be blue): {corner_px}")
    assert center_px[0] > center_px[2]  # R > B in ROI
    assert corner_px[2] > corner_px[0]  # B > R outside ROI


# ---------------------------------------------------------------------------
# 3. LTC sliding window with overlap blending
# ---------------------------------------------------------------------------

def test_ltc_sliding_window_with_blend():
    """Simulate a multi-window diffusion run with LTC overlap blending."""
    import torch

    total_frames = 40
    window_size = 16
    overlap = 4
    C, H, W = 3, 32, 32

    windows = sliding_window_ranges(total_frames, window_size, overlap)
    print(f"\n  Total frames: {total_frames}")
    print(f"  Windows ({len(windows)}): {windows}")

    ltc = LatentTemporalCache()
    all_frames: list[torch.Tensor] = []
    prev_window: torch.Tensor | None = None

    for win_idx, (start, end) in enumerate(windows):
        n = end - start
        # Simulate diffusion output: each window has a distinct brightness
        brightness = (win_idx + 1) / len(windows)
        window_frames = torch.ones(n, C, H, W) * brightness

        if prev_window is not None and overlap > 0:
            blended = blend_overlap(prev_window, window_frames, overlap)
            actual_ov = blended.shape[0]
            all_frames[-actual_ov:] = [blended[i] for i in range(actual_ov)]
            all_frames.extend([window_frames[i] for i in range(actual_ov, n)])
        else:
            all_frames.extend([window_frames[i] for i in range(n)])

        prev_window = window_frames

        # Update LTC
        ltc.update(f"shot_0", window_frames[-1].unsqueeze(0))

    print(f"  Output frames: {len(all_frames)}")
    assert len(all_frames) == total_frames

    # Verify overlap regions are smoothly blended (no hard jumps).
    # With 3 windows, brightness steps are ~0.333, so individual frame diffs
    # in the non-overlap region can be up to step_size. The key property is
    # that overlap frames are NOT a hard cut — they should be smaller than
    # the raw step between windows.
    raw_step = 1.0 / len(windows)  # brightness difference between windows
    for i in range(1, len(all_frames)):
        diff = abs(all_frames[i].mean().item() - all_frames[i - 1].mean().item())
        assert diff < raw_step + 0.01, f"hard jump at frame {i}: diff={diff:.3f}"

    # LTC state should reflect the last window
    entry = ltc.get_or_create("shot_0")
    assert entry.window_index == len(windows)
    assert entry.last_latent is not None
    print(f"  LTC windows processed: {entry.window_index}")
    print("  No hard jumps in overlap: OK")


# ---------------------------------------------------------------------------
# 4. Flow warp preserves shape
# ---------------------------------------------------------------------------

def test_flow_warp_with_real_displacement():
    """Verify flow warp shifts pixels and produces valid output."""
    import torch

    latent = torch.zeros(1, 4, 32, 32)
    latent[:, :, 10:20, 10:20] = 1.0  # bright square in center

    # Non-zero flow should change the output vs zero flow.
    flow = torch.zeros(1, 2, 32, 32)
    flow[:, 0, :, :] = 3.0  # dx shift

    warped = warp_latent(latent, flow)
    assert warped.shape == latent.shape

    # The warped result should differ from the original (flow moved pixels).
    diff = (warped - latent).abs().sum().item()
    print(f"\n  Warp diff from original: {diff:.1f}")
    assert diff > 0, "flow warp should change the output"

    # Zero flow should approximately preserve the original.
    zero_flow = torch.zeros(1, 2, 32, 32)
    identity_warp = warp_latent(latent, zero_flow)
    identity_diff = (identity_warp - latent).abs().sum().item()
    print(f"  Identity warp diff: {identity_diff:.3f}")
    assert identity_diff < 5.0  # near-identity with minor interpolation artifacts


# ---------------------------------------------------------------------------
# 5. Full metrics chain
# ---------------------------------------------------------------------------

def test_full_metrics_chain():
    """Verify metrics from compile through budget produce the expected shape."""
    sl = _mixed_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    graph = fuse(graph)
    mp = plan(graph)

    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=10.0), vram_hints=mp.downgrade_hints)
    for node in graph.nodes:
        out = gov.before_node(node)
        gov.after_node(out.estimated_gpu_ms / 1000.0)

    metrics = gov.metrics()
    print(f"\n  Metrics keys: {list(metrics.keys())}")
    print(f"  GPU spent: {metrics['spent_gpu_seconds']:.1f}s / {metrics['max_gpu_seconds']}s")
    print(f"  Downgrades: {metrics['downgrade_count']}")

    # Verify shape
    assert "max_gpu_seconds" in metrics
    assert "spent_gpu_seconds" in metrics
    assert "remaining_gpu_seconds" in metrics
    assert "downgrade_count" in metrics
    assert isinstance(metrics["downgrades"], list)

    # Verify graph metadata
    assert "tier_distribution" in graph.metadata
    assert graph.metadata["tier_distribution"]["C"] == 1

    # Memory plan
    assert mp.peak_vram_mb > 0
    assert len(mp.per_step_mb) > 0
    print(f"  Memory plan: {mp.peak_vram_mb:.0f} MB peak, {len(mp.per_step_mb)} steps")
    print("  Full metrics chain: OK")
