"""Demand-priority role fetch. No network, no torch.

Task 3 of docs/superpowers/plans/2026-08-21-rfir-role-residency.md
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.rfir.models.fetcher import ensure_roles, packs_to_roles
from app.rfir.models.residency import DEFAULT_T2I_MODEL_ID, FALLBACK_T2I_MODEL_ID


def _recorder() -> tuple[list[str], object]:
    """A stand-in for snapshot_download that records repos and plants a dir."""
    calls: list[str] = []

    def fake_download(repo_id: str, local_dir: str, allow_patterns=None) -> str:
        calls.append(repo_id)
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "ok").write_text("1")
        return local_dir

    return calls, fake_download


def test_ensure_roles_skips_present_and_fetches_missing(tmp_path):
    models = tmp_path / "models"
    (models / "depth-anything-v2-small").mkdir(parents=True)
    (models / "depth-anything-v2-small" / "config.json").write_text("{}")
    calls, download = _recorder()

    ensure_roles(
        frozenset({"t2i_keyframe", "depth_estimate"}),
        models_dir=str(models),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=download,
    )
    assert "black-forest-labs/FLUX.1-schnell" in calls
    assert "stabilityai/sdxl-turbo" not in calls
    # depth already on disk → not fetched
    assert all("Depth-Anything" not in c for c in calls)


def test_ensure_roles_does_not_fetch_t2v_for_tier_a(tmp_path):
    calls, download = _recorder()
    ensure_roles(
        frozenset({"t2i_keyframe"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=download,
    )
    assert all("cogvideox" not in c.lower() for c in calls)


def test_ensure_roles_returns_local_dirs_that_now_exist(tmp_path):
    _, download = _recorder()
    dirs = ensure_roles(
        frozenset({"t2i_keyframe", "depth_estimate"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=download,
    )
    assert set(dirs) == {"flux-schnell", "depth-anything-v2-small"}
    for name in dirs:
        assert (tmp_path / name).is_dir()


def test_empty_dir_counts_as_missing(tmp_path):
    """An interrupted download leaves an empty dir; that is not 'resident'."""
    (tmp_path / "flux-schnell").mkdir(parents=True)
    calls, download = _recorder()
    ensure_roles(
        frozenset({"t2i_keyframe"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=download,
    )
    assert "black-forest-labs/FLUX.1-schnell" in calls


def test_largest_missing_role_is_fetched_first(tmp_path):
    """Demand-priority pop: the biggest blocker goes first, not insertion order."""
    calls, download = _recorder()
    ensure_roles(
        frozenset({"t2i_keyframe", "sparse_t2v", "depth_estimate", "nsfw_classify"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=download,
    )
    assert calls[0] == "black-forest-labs/FLUX.1-schnell"  # 12 GB
    assert calls[1] == "THUDM/CogVideoX-2b"                # 10 GB


def test_shared_checkpoint_is_fetched_once(tmp_path):
    calls, download = _recorder()
    ensure_roles(
        frozenset({"sparse_t2v", "vae"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=download,
    )
    assert calls.count("THUDM/CogVideoX-2b") == 1


def test_allow_patterns_are_passed_through(tmp_path):
    seen: dict[str, object] = {}

    def download(repo_id: str, local_dir: str, allow_patterns=None) -> str:
        seen[repo_id] = allow_patterns
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "ok").write_text("1")
        return local_dir

    ensure_roles(
        frozenset({"plan_shots"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=download,
    )
    assert seen["Qwen/Qwen2.5-3B-Instruct-GGUF"] == ["*q4_k_m.gguf"]


def test_roles_without_a_repo_are_not_fetched(tmp_path):
    """RIFE weights ship as in-repo LFS; there is no HF repo to snapshot."""
    calls, download = _recorder()
    ensure_roles(
        frozenset({"rife_interpolate"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=download,
    )
    assert calls == []


def test_selecting_sdxl_never_touches_flux(tmp_path):
    calls, download = _recorder()
    ensure_roles(
        frozenset({"t2i_keyframe"}),
        models_dir=str(tmp_path),
        t2i_model_id=FALLBACK_T2I_MODEL_ID,
        download=download,
    )
    assert calls == ["stabilityai/sdxl-turbo"]


def test_incomplete_fetch_raises_rather_than_running_the_graph(tmp_path):
    """A 401/truncated snapshot must not look like success to the executor."""

    def bad_download(repo_id: str, local_dir: str, allow_patterns=None) -> str:
        Path(local_dir).mkdir(parents=True, exist_ok=True)  # empty → still missing
        return local_dir

    with pytest.raises(RuntimeError, match="flux-schnell"):
        ensure_roles(
            frozenset({"t2i_keyframe"}),
            models_dir=str(tmp_path),
            t2i_model_id=DEFAULT_T2I_MODEL_ID,
            download=bad_download,
        )


def test_download_error_names_the_role(tmp_path):
    def boom(repo_id: str, local_dir: str, allow_patterns=None) -> str:
        raise OSError("gated repo")

    with pytest.raises(RuntimeError, match="t2i_keyframe"):
        ensure_roles(
            frozenset({"t2i_keyframe"}),
            models_dir=str(tmp_path),
            t2i_model_id=DEFAULT_T2I_MODEL_ID,
            download=boom,
        )


def test_no_roles_is_a_noop(tmp_path):
    calls, download = _recorder()
    assert ensure_roles(
        frozenset(), models_dir=str(tmp_path), t2i_model_id=DEFAULT_T2I_MODEL_ID, download=download
    ) == []
    assert calls == []


def test_default_packs_exclude_t2v_and_second_t2i():
    roles = packs_to_roles(["core", "t2i"])
    assert "t2i_keyframe" in roles
    assert "sparse_t2v" not in roles


def test_all_pack_includes_everything():
    roles = packs_to_roles(["all"])
    assert {"t2i_keyframe", "sparse_t2v", "segment_subject", "plan_shots"} <= roles


def test_unknown_pack_raises():
    with pytest.raises(ValueError, match="unknown pack"):
        packs_to_roles(["nonsense"])
