"""Tests for RFIR role-residency math.

Run these *before* implementing fetch/LRU/quantization:

    cd services/model-workers
    poetry run pytest tests/test_residency_math.py -v
"""
from __future__ import annotations

import pytest

from app.rfir.ir.types import RfirGraph, RfirNode
from app.rfir.models.residency import (
    DEFAULT_T2I_MODEL_ID,
    FALLBACK_T2I_MODEL_ID,
    PIN_ROLES,
    ROLE_BYTES_FP16,
    FetchItem,
    catalog_bytes_fp16,
    compression_ratio,
    expected_disk_bytes,
    fetch_priority,
    miss_bytes,
    refuse_cross_architecture_residual,
    required_roles,
    resident_probability,
)


def test_required_roles_tier_a_omits_t2v():
    graph = RfirGraph(
        nodes=[
            RfirNode(id="k", op="t2i_keyframe"),
            RfirNode(id="d", op="depth_estimate"),
            RfirNode(id="p", op="vulkan_parallax"),
            RfirNode(id="u", op="vulkan_upscale"),
            RfirNode(id="m", op="ffmpeg_mux"),
        ]
    )
    assert required_roles(graph) == frozenset({"t2i_keyframe", "depth_estimate"})


def test_required_roles_tier_c_includes_t2v_and_sam():
    graph = RfirGraph(
        nodes=[
            RfirNode(id="k", op="t2i_keyframe"),
            RfirNode(id="s", op="segment_subject"),
            RfirNode(id="e", op="vae_encode"),
            RfirNode(id="t", op="sparse_t2v_window"),
            RfirNode(id="v", op="vae_decode"),
        ]
    )
    assert required_roles(graph) == frozenset(
        {"t2i_keyframe", "segment_subject", "vae", "sparse_t2v"}
    )


def test_resident_probability_hand_worked():
    # p=0.1, W=1 → 0.1; W=∞ → 1; p=1 any W>0 → 1; W=0 → 0
    assert resident_probability(0.1, 1) == pytest.approx(0.1)
    assert resident_probability(0.1, 2) == pytest.approx(1.0 - 0.9**2)
    assert resident_probability(1.0, 3) == pytest.approx(1.0)
    assert resident_probability(0.0, 10) == pytest.approx(0.0)
    assert resident_probability(0.2, 0) == pytest.approx(0.0)
    assert resident_probability(0.5, 10**6) == pytest.approx(1.0)


def test_resident_probability_rejects_bad_inputs():
    with pytest.raises(ValueError):
        resident_probability(-0.1, 1)
    with pytest.raises(ValueError):
        resident_probability(0.5, -1)


def test_expected_disk_prepaid_catalog_is_about_30gb():
    """Today's download script: W=∞ and dual T2I."""
    prepaid = catalog_bytes_fp16(include_t2i_fallback=True)
    # FLUX 12 + SDXL 6 + Cog 10 + Qwen 2 + extras ≈ 30.78 GB
    assert prepaid == (
        12 * 10**9
        + 6 * 10**9
        + 10 * 10**9
        + 2 * 10**9
        + 200 * 10**6
        + 150 * 10**6
        + 100 * 10**6
        + 330 * 10**6
    )
    assert 20 * 10**9 < prepaid < 35 * 10**9


def test_dropping_dual_t2i_saves_sdxl_bytes():
    with_both = catalog_bytes_fp16(include_t2i_fallback=True)
    canonical = catalog_bytes_fp16(include_t2i_fallback=False)
    assert with_both - canonical == ROLE_BYTES_FP16["t2i_keyframe_fallback"]


def test_working_set_window_1_beats_prepaid():
    """Pin small roles; LRU window=1 on the giants. Dual T2I off."""
    sizes = dict(ROLE_BYTES_FP16)
    p = {
        "t2i_keyframe": 1.0,
        "sparse_t2v": 0.10,
        "plan_shots": 1.0,
        "depth_estimate": 0.70,
        "segment_subject": 0.08,
        "rife_interpolate": 0.20,
        "nsfw_classify": 1.0,
        "vae": 0.10,
    }
    prepaid = catalog_bytes_fp16(include_t2i_fallback=True)
    working = expected_disk_bytes(
        sizes, p, window=1, pin=PIN_ROLES, include_t2i_fallback=False
    )
    # t2i always (p=1) + pins + 0.1 * cogvideox
    expected = (
        ROLE_BYTES_FP16["t2i_keyframe"]
        + ROLE_BYTES_FP16["plan_shots"]
        + ROLE_BYTES_FP16["depth_estimate"]
        + ROLE_BYTES_FP16["rife_interpolate"]
        + ROLE_BYTES_FP16["nsfw_classify"]
        + int(round(0.10 * ROLE_BYTES_FP16["sparse_t2v"]))
        + int(round(0.08 * ROLE_BYTES_FP16["segment_subject"]))
        # vae is 0 bytes in the table (shared with t2v checkpoint)
    )
    assert working == expected
    assert working < prepaid
    rho = compression_ratio(working, prepaid)
    assert 0.0 < rho < 0.7


def test_infinite_window_without_fallback_still_drops_sdxl():
    p = {role: 1.0 for role in ROLE_BYTES_FP16}
    infinite = expected_disk_bytes(
        ROLE_BYTES_FP16,
        p,
        window=10**6,
        pin=frozenset(),
        include_t2i_fallback=False,
    )
    assert infinite == catalog_bytes_fp16(include_t2i_fallback=False)


def test_miss_bytes_only_counts_absent_roles():
    demand = frozenset({"t2i_keyframe", "sparse_t2v", "depth_estimate"})
    hot = frozenset({"t2i_keyframe", "depth_estimate", "plan_shots"})
    assert miss_bytes(demand, hot, ROLE_BYTES_FP16) == ROLE_BYTES_FP16["sparse_t2v"]


def test_fetch_priority_current_job_before_prefetch_then_largest():
    items = [
        FetchItem(role="sparse_t2v", bytes=10 * 10**9, in_current_job=False),
        FetchItem(role="t2i_keyframe", bytes=12 * 10**9, in_current_job=True),
        FetchItem(role="depth_estimate", bytes=200 * 10**6, in_current_job=True),
    ]
    ordered = fetch_priority(items)
    assert [i.role for i in ordered] == [
        "t2i_keyframe",
        "depth_estimate",
        "sparse_t2v",
    ]


def test_refuse_cross_architecture_residual():
    refuse_cross_architecture_residual("flux-dit", "flux-dit")
    with pytest.raises(TypeError, match="undefined"):
        refuse_cross_architecture_residual("flux-dit", "sdxl-unet")
    with pytest.raises(TypeError, match="undefined"):
        refuse_cross_architecture_residual("flux-dit", "cogvideox-3d")


def test_canonical_t2i_ids_are_distinct():
    assert DEFAULT_T2I_MODEL_ID != FALLBACK_T2I_MODEL_ID
    assert "flux" in DEFAULT_T2I_MODEL_ID
    assert "sdxl" in FALLBACK_T2I_MODEL_ID


def test_compression_ratio_rejects_empty_catalog():
    with pytest.raises(ValueError):
        compression_ratio(1, 0)
