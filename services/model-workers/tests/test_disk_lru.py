"""Pin + LRU over role directories, so the 30 GB pile cannot grow back.

Task 4 of docs/superpowers/plans/2026-08-21-rfir-role-residency.md
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.rfir.models.disk_lru import (
    LRU_STATE_FILE,
    dir_bytes,
    evict_until,
    resident_bytes,
    touch,
)
from app.rfir.models.residency import PIN_ROLES

ROLE_DIRS = {
    "t2i_keyframe": "flux-schnell",
    "sparse_t2v": "cogvideox-2b",
    "depth_estimate": "depth-anything-v2-small",
}


def _plant(root: Path, name: str, nbytes: int) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "w.bin").write_bytes(b"x" * nbytes)


def _models(tmp_path: Path) -> Path:
    models = tmp_path / "models"
    _plant(models, "flux-schnell", 50)
    _plant(models, "cogvideox-2b", 50)
    _plant(models, "depth-anything-v2-small", 10)
    return models


def test_evict_drops_oldest_unpinned_not_pins(tmp_path):
    models = _models(tmp_path)
    touch("depth_estimate", str(models))
    touch("t2i_keyframe", str(models))
    touch("sparse_t2v", str(models))

    evicted = evict_until(str(models), max_bytes=70, role_dirs=ROLE_DIRS)

    assert "cogvideox-2b" in evicted or "flux-schnell" in evicted
    assert "depth-anything-v2-small" not in evicted
    assert "depth_estimate" in PIN_ROLES


def test_eviction_order_is_least_recently_used(tmp_path):
    """T2I touched last, so the older T2V leaves first."""
    models = _models(tmp_path)
    clock = iter([100.0, 200.0])
    touch("sparse_t2v", str(models), clock=lambda: next(clock))
    touch("t2i_keyframe", str(models), clock=lambda: next(clock))

    evicted = evict_until(str(models), max_bytes=70, role_dirs=ROLE_DIRS)

    assert evicted == ["cogvideox-2b"]
    assert not (models / "cogvideox-2b").exists()
    assert (models / "flux-schnell").is_dir()


def test_evicted_directory_is_actually_deleted(tmp_path):
    models = _models(tmp_path)
    touch("sparse_t2v", str(models), clock=lambda: 1.0)
    touch("t2i_keyframe", str(models), clock=lambda: 2.0)

    evict_until(str(models), max_bytes=70, role_dirs=ROLE_DIRS)

    assert not (models / "cogvideox-2b").exists()
    assert resident_bytes(str(models), ROLE_DIRS) <= 70


def test_pins_are_kept_even_when_over_budget(tmp_path):
    """A cap below the pin set evicts everything else and then stops."""
    models = _models(tmp_path)
    touch("depth_estimate", str(models), clock=lambda: 1.0)

    evicted = evict_until(str(models), max_bytes=1, role_dirs=ROLE_DIRS)

    assert set(evicted) == {"flux-schnell", "cogvideox-2b"}
    assert (models / "depth-anything-v2-small").is_dir()


def test_untouched_roles_evict_before_touched_ones(tmp_path):
    """A role with no recorded use is the coldest thing on disk."""
    models = _models(tmp_path)
    touch("sparse_t2v", str(models), clock=lambda: 500.0)

    evicted = evict_until(str(models), max_bytes=70, role_dirs=ROLE_DIRS)

    assert evicted == ["flux-schnell"]


def test_no_eviction_when_under_budget(tmp_path):
    models = _models(tmp_path)
    touch("t2i_keyframe", str(models))

    assert evict_until(str(models), max_bytes=10_000, role_dirs=ROLE_DIRS) == []
    assert (models / "cogvideox-2b").is_dir()


def test_touch_persists_across_calls(tmp_path):
    models = _models(tmp_path)
    touch("t2i_keyframe", str(models), clock=lambda: 1.0)
    touch("sparse_t2v", str(models), clock=lambda: 2.0)

    assert (models / LRU_STATE_FILE).is_file()
    # Re-read from disk, not from memory.
    assert evict_until(str(models), max_bytes=70, role_dirs=ROLE_DIRS) == ["flux-schnell"]


def test_touch_on_missing_models_dir_does_not_raise(tmp_path):
    touch("t2i_keyframe", str(tmp_path / "nope"))


def test_corrupt_state_file_is_treated_as_empty(tmp_path):
    models = _models(tmp_path)
    (models / LRU_STATE_FILE).write_text("{not json")

    touch("t2i_keyframe", str(models), clock=lambda: 9.0)

    assert evict_until(str(models), max_bytes=70, role_dirs=ROLE_DIRS) == ["cogvideox-2b"]


def test_state_file_is_not_counted_or_evicted(tmp_path):
    models = _models(tmp_path)
    touch("t2i_keyframe", str(models))

    assert resident_bytes(str(models), ROLE_DIRS) == 110
    evict_until(str(models), max_bytes=10_000, role_dirs=ROLE_DIRS)
    assert (models / LRU_STATE_FILE).is_file()


def test_absent_role_dirs_are_skipped(tmp_path):
    models = tmp_path / "models"
    _plant(models, "flux-schnell", 50)

    assert resident_bytes(str(models), ROLE_DIRS) == 50
    assert evict_until(str(models), max_bytes=10_000, role_dirs=ROLE_DIRS) == []


def test_dir_bytes_sums_nested_files(tmp_path):
    d = tmp_path / "m"
    (d / "sub").mkdir(parents=True)
    (d / "a.bin").write_bytes(b"x" * 10)
    (d / "sub" / "b.bin").write_bytes(b"x" * 5)

    assert dir_bytes(str(d)) == 15


def test_negative_budget_rejected(tmp_path):
    with pytest.raises(ValueError, match="max_bytes"):
        evict_until(str(tmp_path), max_bytes=-1, role_dirs=ROLE_DIRS)
