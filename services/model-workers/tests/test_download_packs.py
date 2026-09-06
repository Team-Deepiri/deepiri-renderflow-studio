"""What the bootstrap download script pulls by default.

The old script downloaded every repo unconditionally — both T2I backends and
CogVideoX — which is the prepaid 30 GB this PR removes.

Task 6 of docs/superpowers/plans/2026-08-21-rfir-role-residency.md
"""
from __future__ import annotations

import pytest

from app.rfir.models.fetcher import DEFAULT_PACKS, packs_to_roles, plan_downloads
from app.rfir.models.residency import DEFAULT_T2I_MODEL_ID, FALLBACK_T2I_MODEL_ID


def test_default_packs_are_core_and_t2i():
    assert set(DEFAULT_PACKS) == {"core", "t2i"}


def test_default_packs_exclude_t2v_and_sam():
    roles = packs_to_roles(DEFAULT_PACKS)
    assert "t2i_keyframe" in roles
    assert "sparse_t2v" not in roles
    assert "segment_subject" not in roles


def test_default_plan_pulls_one_t2i_not_two():
    plan = plan_downloads(DEFAULT_PACKS, t2i_model_id=DEFAULT_T2I_MODEL_ID)
    dirs = [m.local_dir for m in plan]
    assert "flux-schnell" in dirs
    assert "sdxl-turbo" not in dirs


def test_default_plan_is_well_under_the_old_catalog():
    """core+t2i is the ~14 GB working set, not the ~30 GB pile."""
    from app.rfir.models.residency import ROLE_BYTES_FP16

    plan = plan_downloads(DEFAULT_PACKS, t2i_model_id=DEFAULT_T2I_MODEL_ID)
    total = sum(ROLE_BYTES_FP16.get(m.role, 0) for m in plan)
    assert total < 16 * 10**9


def test_plan_is_ordered_biggest_first():
    plan = plan_downloads(["all"], t2i_model_id=DEFAULT_T2I_MODEL_ID)
    dirs = [m.local_dir for m in plan]
    assert dirs[0] == "flux-schnell"     # 12 GB
    assert dirs[1] == "cogvideox-2b"     # 10 GB


def test_all_pack_still_gets_everything_except_the_spare_t2i():
    plan = plan_downloads(["all"], t2i_model_id=DEFAULT_T2I_MODEL_ID)
    dirs = {m.local_dir for m in plan}
    assert {"flux-schnell", "cogvideox-2b", "sam2-hiera-tiny"} <= dirs
    assert "sdxl-turbo" not in dirs


def test_sdxl_selection_swaps_the_t2i_artifact():
    plan = plan_downloads(DEFAULT_PACKS, t2i_model_id=FALLBACK_T2I_MODEL_ID)
    dirs = {m.local_dir for m in plan}
    assert "sdxl-turbo" in dirs
    assert "flux-schnell" not in dirs


def test_shared_cogvideox_checkpoint_appears_once():
    plan = plan_downloads(["t2v"], t2i_model_id=DEFAULT_T2I_MODEL_ID)
    dirs = [m.local_dir for m in plan]
    assert dirs.count("cogvideox-2b") == 1


def test_plan_omits_roles_with_no_hf_repo():
    """RIFE ships as in-repo LFS; the script has nothing to snapshot."""
    plan = plan_downloads(["core"], t2i_model_id=DEFAULT_T2I_MODEL_ID)
    assert all(m.repo for m in plan)
    assert "rife-4.6" not in {m.local_dir for m in plan}


def test_unknown_pack_raises():
    with pytest.raises(ValueError, match="unknown pack"):
        plan_downloads(["nonsense"], t2i_model_id=DEFAULT_T2I_MODEL_ID)
