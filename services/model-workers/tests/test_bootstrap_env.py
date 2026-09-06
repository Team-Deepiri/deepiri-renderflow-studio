"""Bootstrap environment tests for Task 3.

Verifies:
  - RENDERFLOW_MODELS_DIR is set and the directory exists
  - The core + T2I working set is present and non-empty
  - On-demand packs (T2V, SAM) are reported but do not fail the suite
  - detect_device() returns a valid device string
  - Registry manifests match the directory names the loader expects

Disk is a working set, not a prepaid catalog: a laptop that has never run a
Tier C/D job has no CogVideoX on disk, and that is correct rather than broken.
The executor fetches those roles when a compiled graph names them.

Run after `scripts/download_rfir_models.py`:
    RENDERFLOW_MODELS_DIR=$HOME/renderflow-models poetry run pytest tests/test_bootstrap_env.py -v
"""
from __future__ import annotations

import os

import pytest

from app.rfir.models.fetcher import DEFAULT_PACKS, is_resident, plan_downloads
from app.rfir.models.loader import detect_device
from app.rfir.models.registry import REGISTRY
from app.rfir.models.residency import DEFAULT_T2I_MODEL_ID

MODELS_DIR = os.environ.get("RENDERFLOW_MODELS_DIR")
T2I_MODEL_ID = os.environ.get("RENDERFLOW_RFIR_T2I_MODEL") or DEFAULT_T2I_MODEL_ID

# Required: what scripts/download_rfir_models.py installs by default (core + one T2I).
REQUIRED_DIRS = {
    m.local_dir: f"{m.id} ({m.role})"
    for m in plan_downloads(DEFAULT_PACKS, t2i_model_id=T2I_MODEL_ID)
}

# Optional: fetched on demand the first time a graph names the role.
OPTIONAL_DIRS = {
    "sam2-hiera-tiny": "sam2-hiera-tiny (segmentation, Tier C)",
    "cogvideox-2b":    "cogvideox-2b (sparse T2V + VAE, Tier C/D)",
}


def test_models_dir_env_var_is_set():
    assert MODELS_DIR, (
        "RENDERFLOW_MODELS_DIR is not set. "
        "Run: export RENDERFLOW_MODELS_DIR=$HOME/renderflow-models"
    )


def test_models_dir_exists():
    assert MODELS_DIR and os.path.isdir(MODELS_DIR), (
        f"RENDERFLOW_MODELS_DIR={MODELS_DIR!r} does not exist on disk. "
        "Run: mkdir -p $RENDERFLOW_MODELS_DIR"
    )


@pytest.mark.skipif(not MODELS_DIR, reason="RENDERFLOW_MODELS_DIR not set")
@pytest.mark.parametrize("subdir,label", REQUIRED_DIRS.items())
def test_core_and_t2i_present(subdir: str, label: str):
    """The default install: every Tier A job needs these."""
    path = os.path.join(MODELS_DIR, subdir)  # type: ignore[arg-type]
    assert os.path.isdir(path), (
        f"Missing: {path}\n"
        f"Model: {label}\n"
        "Run scripts/download_rfir_models.py to download."
    )
    assert is_resident(MODELS_DIR, subdir), (  # type: ignore[arg-type]
        f"{path} holds no weights file — an interrupted or gated download.\n"
        f"Model: {label}\n"
        f"Delete it and re-run scripts/download_rfir_models.py "
        f"(gated repos need: huggingface-cli login)."
    )


@pytest.mark.skipif(not MODELS_DIR, reason="RENDERFLOW_MODELS_DIR not set")
@pytest.mark.parametrize("subdir,label", OPTIONAL_DIRS.items())
def test_t2v_and_sam_optional(subdir: str, label: str):
    """Absent is fine — the executor fetches these when a graph names them.

    Present but empty is not: that is an interrupted download the loader would
    trip over.
    """
    path = os.path.join(MODELS_DIR, subdir)  # type: ignore[arg-type]
    if not os.path.isdir(path):
        pytest.skip(f"{label} not installed; fetched on first use")
    assert is_resident(MODELS_DIR, subdir), (  # type: ignore[arg-type]
        f"{path} exists but holds no weights — interrupted download. "
        f"Delete it and let the executor re-fetch, or run "
        f"scripts/download_rfir_models.py --pack all."
    )


@pytest.mark.skipif(not MODELS_DIR, reason="RENDERFLOW_MODELS_DIR not set")
def test_only_one_t2i_backend_is_installed():
    """Shipping FLUX and SDXL together is 6 GB of prepaid disk for nothing."""
    present = [
        d for d in ("flux-schnell", "sdxl-turbo")
        if is_resident(MODELS_DIR, d)  # type: ignore[arg-type]
    ]
    if len(present) < 2:
        return
    assert os.environ.get("RENDERFLOW_RFIR_KEEP_BOTH_T2I") == "1", (
        "Both T2I backends are on disk. Keep one, or set "
        "RENDERFLOW_RFIR_KEEP_BOTH_T2I=1 if you deliberately want both."
    )


def test_detect_device_returns_valid_string():
    device = detect_device()
    assert device in ("cuda", "mps", "cpu"), f"Unexpected device: {device!r}"


def test_registry_covers_all_expected_dirs():
    registry_ids = set(REGISTRY.keys())
    assert "flux-schnell-fp16" in registry_ids
    assert "sdxl-turbo-fp16" in registry_ids
    assert "depth-anything-v2-small" in registry_ids
    assert "qwen2.5-3b-instruct-gguf" in registry_ids
    assert "sam2-hiera-tiny" in registry_ids
    assert "cogvideox-2b" in registry_ids
    assert "cogvideox-2b-vae" in registry_ids
