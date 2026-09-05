"""Role → artifact covering. One T2I on disk, never a prepaid pair.

Task 2 of docs/superpowers/plans/2026-08-21-rfir-role-residency.md
"""
from __future__ import annotations

import pytest

from app.rfir.models.registry import REGISTRY, artifacts_for_roles, get_manifest


def test_t2i_role_returns_only_canonical_flux():
    arts = artifacts_for_roles(frozenset({"t2i_keyframe"}), t2i_model_id="flux-schnell-fp16")
    ids = {a.id for a in arts}
    assert "flux-schnell-fp16" in ids
    assert "sdxl-turbo-fp16" not in ids


def test_t2i_role_can_select_sdxl_without_flux():
    arts = artifacts_for_roles(frozenset({"t2i_keyframe"}), t2i_model_id="sdxl-turbo-fp16")
    ids = {a.id for a in arts}
    assert "sdxl-turbo-fp16" in ids
    assert "flux-schnell-fp16" not in ids


def test_t2v_role_shares_vae_checkpoint():
    arts = artifacts_for_roles(frozenset({"sparse_t2v", "vae"}), t2i_model_id="flux-schnell-fp16")
    dirs = {a.local_dir for a in arts}
    assert "cogvideox-2b" in dirs
    assert len(dirs) == 1


def test_unknown_t2i_id_raises():
    with pytest.raises(ValueError, match="t2i"):
        artifacts_for_roles(frozenset({"t2i_keyframe"}), t2i_model_id="not-a-model")


def test_t2i_id_naming_a_non_t2i_model_raises():
    with pytest.raises(ValueError, match="t2i"):
        artifacts_for_roles(frozenset({"t2i_keyframe"}), t2i_model_id="cogvideox-2b")


def test_tier_a_roles_never_pull_t2v_or_sam():
    """The Tier A working set: plan → keyframe → depth → safety. No 10 GB video model."""
    arts = artifacts_for_roles(
        frozenset({"plan_shots", "t2i_keyframe", "depth_estimate", "nsfw_classify"}),
        t2i_model_id="flux-schnell-fp16",
    )
    dirs = {a.local_dir for a in arts}
    assert "cogvideox-2b" not in dirs
    assert "sam2-hiera-tiny" not in dirs
    assert "sdxl-turbo" not in dirs


def test_empty_role_set_fetches_nothing():
    assert artifacts_for_roles(frozenset(), t2i_model_id="flux-schnell-fp16") == []


def test_unknown_role_is_ignored_not_an_error():
    """A graph op with no ML weights (ffmpeg/Vulkan) maps to no role at all."""
    assert artifacts_for_roles(frozenset({"not_a_role"}), t2i_model_id="flux-schnell-fp16") == []


def test_every_manifest_has_a_pack_and_local_dir():
    for manifest in REGISTRY.values():
        assert manifest.pack, f"{manifest.id} has no pack"
        assert manifest.local_dir, f"{manifest.id} has no local_dir"


def test_local_dirs_match_todays_loader_paths():
    """local_dir must not move weights that are already on contributors' disks."""
    expected = {
        "flux-schnell-fp16": "flux-schnell",
        "sdxl-turbo-fp16": "sdxl-turbo",
        "depth-anything-v2-small": "depth-anything-v2-small",
        "qwen2.5-3b-instruct-gguf": "qwen2.5-3b-instruct-gguf",
        "sam2-hiera-tiny": "sam2-hiera-tiny",
        "cogvideox-2b": "cogvideox-2b",
        "cogvideox-2b-vae": "cogvideox-2b",
        "nsfw-image-detection": "nsfw-image-detection",
    }
    for model_id, local_dir in expected.items():
        manifest = get_manifest(model_id)
        assert manifest is not None, f"{model_id} left the registry"
        assert manifest.local_dir == local_dir


def test_qwen_keeps_gguf_allow_patterns():
    """Only the q4_k_m file, not the whole multi-quant repo."""
    manifest = get_manifest("qwen2.5-3b-instruct-gguf")
    assert manifest.allow_patterns == ("*q4_k_m.gguf",)


def test_packs_partition_the_catalog():
    packs = {m.pack for m in REGISTRY.values()}
    assert packs == {"core", "t2i", "t2v", "sam"}
