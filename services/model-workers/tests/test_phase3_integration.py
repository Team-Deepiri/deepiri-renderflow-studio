"""Phase 3 integration test — validates Tier C compile pipeline without GPU.

Checks exit criteria:
  - Tier C graph compiles with segment, VAE, sparse_t2v, composite nodes
  - Memory planner flags Tier C as over-budget on 8 GB GPU (sparse_t2v_window = 8 GB)
  - Budget governor downgrades when VRAM hints are set
  - Tier distribution includes C shots
  - ROI crop/paste logic works with dummy images and masks
"""
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
from app.rfir.compiler.memory_plan import plan, DEFAULT_VRAM_LIMIT_MB
from app.rfir.budget import BudgetGovernor
from app.rfir.ops.sparse_t2v_window import (
    SparseT2VResult,
    _crop_to_roi,
    _latent_overlap_frames,
    _paste_roi,
    _to_tchw,
    _from_tchw,
    _video_frames_to_latent_frames,
)


def _tier_c_shotlist() -> ShotList:
    return ShotList(
        prompt="hero running through rain",
        shots=[
            Shot(index=0, description="wide shot of rainy street",
                 tier=Tier.A, duration_sec=4.0,
                 camera=CameraPath(motion=CameraMotion.STATIC)),
            Shot(index=1, description="hero sprinting with hair flying",
                 tier=Tier.C, duration_sec=3.0,
                 camera=CameraPath(motion=CameraMotion.TRACKING),
                 subject="hero"),
            Shot(index=2, description="close-up of puddle splash",
                 tier=Tier.A, duration_sec=2.0,
                 camera=CameraPath(motion=CameraMotion.ZOOM)),
        ],
    )


# ---------------------------------------------------------------------------
# Tier C graph structure
# ---------------------------------------------------------------------------

def test_tier_c_graph_has_required_ops():
    sl = _tier_c_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    ops = {n.op for n in graph.nodes}
    assert "segment_subject" in ops
    assert "vae_encode" in ops
    assert "vae_decode" in ops
    assert "sparse_t2v_window" in ops
    assert "vulkan_composite" in ops


def test_tier_c_graph_tier_distribution():
    sl = _tier_c_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    dist = graph.metadata["tier_distribution"]
    assert dist.get("A", 0) == 2
    assert dist.get("C", 0) == 1


def test_tier_c_capped_to_b():
    sl = _tier_c_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.B))
    dist = graph.metadata["tier_distribution"]
    assert dist.get("C", 0) == 0
    assert dist.get("B", 0) >= 1


# ---------------------------------------------------------------------------
# Memory planner flags Tier C as over-budget
# ---------------------------------------------------------------------------

def test_tier_c_over_vram_budget():
    sl = _tier_c_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    mp = plan(graph)
    assert mp.over_budget is True
    assert mp.peak_vram_mb >= 8192
    t2v_nodes = [n.id for n in graph.nodes if n.op == "sparse_t2v_window"]
    assert any(nid in mp.downgrade_hints for nid in t2v_nodes)


# ---------------------------------------------------------------------------
# Budget governor integration with Tier C
# ---------------------------------------------------------------------------

def test_tier_c_budget_governor_downgrades():
    sl = _tier_c_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    graph = fuse(graph)
    mp = plan(graph)

    gov = BudgetGovernor(
        InferenceBudget(max_gpu_seconds=5.0),
        vram_hints=mp.downgrade_hints,
    )

    for node in graph.nodes:
        out = gov.before_node(node)
        gov.after_node(out.estimated_gpu_ms / 1000.0)

    assert len(gov.downgrades) > 0
    metrics = gov.metrics()
    assert metrics["spent_gpu_seconds"] > 0


# ---------------------------------------------------------------------------
# ROI crop / paste
# ---------------------------------------------------------------------------

def test_crop_to_roi_basic():
    img = Image.new("RGB", (512, 288), color=(128, 128, 128))
    mask = np.zeros((288, 512), dtype=np.uint8)
    mask[100:200, 150:350] = 255
    cropped, bbox = _crop_to_roi(img, mask, pad=8)
    x0, y0, x1, y1 = bbox
    assert x0 <= 150
    assert y0 <= 100
    assert x1 >= 350
    assert y1 >= 200
    assert cropped.width == x1 - x0
    assert cropped.height == y1 - y0
    assert cropped.width % 16 == 0
    assert cropped.height % 16 == 0


def test_crop_to_roi_empty_mask():
    img = Image.new("RGB", (512, 288))
    mask = np.zeros((288, 512), dtype=np.uint8)
    _, bbox = _crop_to_roi(img, mask)
    assert bbox == (0, 0, 512, 288)


def test_paste_roi_roundtrip():
    bg = Image.new("RGB", (512, 288), color=(0, 0, 255))
    roi = Image.new("RGB", (200, 100), color=(255, 0, 0))
    mask = np.zeros((288, 512), dtype=np.uint8)
    mask[50:150, 100:300] = 255
    bbox = (100, 50, 300, 150)

    result = _paste_roi(bg, roi, mask, bbox)
    assert result.size == (512, 288)
    # Center of the ROI region should be red-ish, not blue.
    px = result.getpixel((200, 100))
    assert px[0] > px[2]  # R > B


def test_latent_temporal_helpers():
    """Video-frame counts map to Wan-style compressed latent lengths."""
    assert _video_frames_to_latent_frames(21, 4) == 6
    assert _video_frames_to_latent_frames(17, 4) == 5
    assert _latent_overlap_frames(4, 4) == 1
    assert _latent_overlap_frames(0, 4) == 0


def test_latent_tchw_roundtrip():
    import torch

    latents = torch.randn(1, 16, 6, 8, 8)
    tchw = _to_tchw(latents)
    assert tchw.shape == (6, 16, 8, 8)
    back = _from_tchw(tchw)
    assert torch.allclose(latents, back)


def test_sparse_t2v_result_is_latents_not_frames():
    """Option-2 contract: SparseT2VResult carries a latent tensor."""
    import torch

    result = SparseT2VResult(latents=torch.zeros(1, 16, 2, 4, 4), bbox=(0, 0, 64, 64))
    assert isinstance(result.latents, torch.Tensor)
    assert result.latents.dim() == 5
    assert result.bbox == (0, 0, 64, 64)


def test_tier_c_t2v_wires_image_input():
    sl = _tier_c_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    t2v = next(n for n in graph.nodes if n.op == "sparse_t2v_window")
    assert "image" in t2v.inputs
    assert "latent_out" in t2v.outputs
    decode = next(n for n in graph.nodes if n.op == "vae_decode")
    assert decode.inputs["latent"] == t2v.outputs["latent_out"]


# ---------------------------------------------------------------------------
# Metrics shape for Tier C
# ---------------------------------------------------------------------------

def test_tier_c_metrics_shape():
    sl = _tier_c_shotlist()
    graph = build(sl, budget=InferenceBudget(max_tier=Tier.C))
    mp = plan(graph)
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=10.0), vram_hints=mp.downgrade_hints)

    for node in graph.nodes:
        out = gov.before_node(node)
        gov.after_node(out.estimated_gpu_ms / 1000.0)

    metrics = gov.metrics()
    assert "tier_distribution" in graph.metadata
    assert graph.metadata["tier_distribution"].get("C", 0) == 1
    assert isinstance(metrics["downgrades"], list)
