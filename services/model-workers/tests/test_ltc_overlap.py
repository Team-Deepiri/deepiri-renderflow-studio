"""Tests for RFIR Latent Temporal Cache — overlap blending, flow warp, windows (§3.4).

All tests run on CPU with small tensors — no GPU required.
"""
import torch
import pytest

from app.rfir.ltc import (
    LatentCacheEntry,
    LatentTemporalCache,
    blend_overlap,
    cosine_blend_weights,
    sliding_window_ranges,
    warp_latent,
)


# ---------------------------------------------------------------------------
# Cosine blend weights
# ---------------------------------------------------------------------------

def test_cosine_weights_shape_and_range():
    w = cosine_blend_weights(8)
    assert w.shape == (8,)
    assert w[0].item() == pytest.approx(0.0, abs=0.05)
    assert w[-1].item() == pytest.approx(1.0, abs=0.05)
    assert all(0.0 <= v <= 1.0 for v in w.tolist())


def test_cosine_weights_monotonic():
    w = cosine_blend_weights(16)
    diffs = w[1:] - w[:-1]
    assert all(d >= 0 for d in diffs.tolist())


def test_cosine_weights_zero_overlap():
    w = cosine_blend_weights(0)
    assert w.shape == (0,)


# ---------------------------------------------------------------------------
# Overlap blending
# ---------------------------------------------------------------------------

def test_blend_overlap_basic():
    prev = torch.zeros(4, 3, 8, 8)
    curr = torch.ones(4, 3, 8, 8)
    blended = blend_overlap(prev, curr, overlap=4)
    assert blended.shape == (4, 3, 8, 8)
    # First frame should be close to prev (0), last close to curr (1).
    assert blended[0].mean().item() < 0.15
    assert blended[-1].mean().item() > 0.85


def test_blend_overlap_zero():
    prev = torch.zeros(4, 3, 8, 8)
    curr = torch.ones(4, 3, 8, 8)
    blended = blend_overlap(prev, curr, overlap=0)
    assert torch.equal(blended, curr)


def test_blend_overlap_partial():
    prev = torch.zeros(2, 3, 8, 8)
    curr = torch.ones(6, 3, 8, 8)
    blended = blend_overlap(prev, curr, overlap=4)
    # actual overlap is min(4, 2, 6) = 2
    assert blended.shape == (2, 3, 8, 8)


def test_blend_overlap_symmetry():
    prev = torch.ones(4, 3, 8, 8) * 0.2
    curr = torch.ones(4, 3, 8, 8) * 0.8
    blended = blend_overlap(prev, curr, overlap=4)
    # Midpoint should be approximately the average.
    mid_val = blended[2].mean().item()
    assert 0.3 < mid_val < 0.7


# ---------------------------------------------------------------------------
# Flow warp
# ---------------------------------------------------------------------------

def test_warp_identity_flow():
    latent = torch.rand(1, 4, 16, 16)
    flow = torch.zeros(1, 2, 16, 16)
    warped = warp_latent(latent, flow)
    assert warped.shape == latent.shape
    assert torch.allclose(warped, latent, atol=0.05)


def test_warp_3d_input():
    latent = torch.rand(4, 16, 16)
    flow = torch.zeros(2, 16, 16)
    warped = warp_latent(latent, flow)
    assert warped.shape == (4, 16, 16)


def test_warp_flow_resize():
    latent = torch.rand(1, 4, 32, 32)
    flow = torch.zeros(1, 2, 16, 16)  # smaller flow
    warped = warp_latent(latent, flow)
    assert warped.shape == (1, 4, 32, 32)


# ---------------------------------------------------------------------------
# Sliding window ranges
# ---------------------------------------------------------------------------

def test_window_ranges_short_sequence():
    ranges = sliding_window_ranges(10, window_size=16, overlap=4)
    assert ranges == [(0, 10)]


def test_window_ranges_exact_window():
    ranges = sliding_window_ranges(16, window_size=16, overlap=4)
    assert ranges == [(0, 16)]


def test_window_ranges_two_windows():
    ranges = sliding_window_ranges(24, window_size=16, overlap=4)
    assert len(ranges) == 2
    assert ranges[0] == (0, 16)
    assert ranges[1][0] == 12  # step = 16 - 4 = 12
    assert ranges[1][1] == 24


def test_window_ranges_covers_all_frames():
    total = 50
    ranges = sliding_window_ranges(total, window_size=16, overlap=4)
    covered = set()
    for start, end in ranges:
        covered.update(range(start, end))
    assert covered == set(range(total))


def test_window_ranges_empty():
    assert sliding_window_ranges(0) == []


# ---------------------------------------------------------------------------
# Latent Temporal Cache
# ---------------------------------------------------------------------------

def test_cache_get_or_create():
    ltc = LatentTemporalCache()
    entry = ltc.get_or_create("shot_0")
    assert isinstance(entry, LatentCacheEntry)
    assert entry.last_latent is None
    assert entry.window_index == 0


def test_cache_update_increments_window():
    ltc = LatentTemporalCache()
    ltc.update("shot_0", torch.rand(1, 4, 8, 8))
    entry = ltc.get_or_create("shot_0")
    assert entry.window_index == 1
    assert entry.last_latent is not None


def test_cache_release():
    ltc = LatentTemporalCache()
    ltc.update("shot_0", torch.rand(1, 4, 8, 8))
    ltc.release("shot_0")
    entry = ltc.get_or_create("shot_0")
    assert entry.last_latent is None
    assert entry.window_index == 0


def test_cache_release_all():
    ltc = LatentTemporalCache()
    ltc.update("s0", torch.rand(1, 4, 8, 8))
    ltc.update("s1", torch.rand(1, 4, 8, 8))
    ltc.release_all()
    assert ltc.get_or_create("s0").last_latent is None
    assert ltc.get_or_create("s1").last_latent is None
