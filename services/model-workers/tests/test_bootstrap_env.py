"""Bootstrap environment tests for Task 3.

Verifies:
  - RENDERFLOW_MODELS_DIR is set and the directory exists
  - Each expected model subdirectory is present and non-empty
  - detect_device() returns a valid device string
  - Registry manifests match the directory names the loader expects

Run after `scripts/download_rfir_models.py`:
    RENDERFLOW_MODELS_DIR=$HOME/renderflow-models poetry run pytest tests/test_bootstrap_env.py -v
"""
from __future__ import annotations

import os

import pytest

from app.rfir.models.loader import detect_device
from app.rfir.models.registry import REGISTRY

MODELS_DIR = os.environ.get("RENDERFLOW_MODELS_DIR")

# Subdirectory names that loader.py checks under RENDERFLOW_MODELS_DIR
EXPECTED_DIRS = {
    "flux-schnell":             "flux-schnell-fp16 (T2I keyframes)",
    "sdxl-turbo":               "sdxl-turbo-fp16 (T2I keyframes fallback)",
    "depth-anything-v2-small":  "depth-anything-v2-small (depth estimation)",
    "qwen2.5-3b-instruct-gguf": "qwen2.5-3b-instruct-gguf (shot planner)",
    "sam2-hiera-tiny":          "sam2-hiera-tiny (segmentation)",
    "wan2.1-t2v-1.3b":          "wan2.1-t2v-1.3b (primary sparse T2V + VAE)",
    "cogvideox-2b":             "cogvideox-2b (sparse T2V fallback)",
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
@pytest.mark.parametrize("subdir,label", EXPECTED_DIRS.items())
def test_model_directory_exists_and_non_empty(subdir: str, label: str):
    path = os.path.join(MODELS_DIR, subdir)  # type: ignore[arg-type]
    assert os.path.isdir(path), (
        f"Missing: {path}\n"
        f"Model: {label}\n"
        "Run scripts/download_rfir_models.py to download."
    )
    contents = os.listdir(path)
    assert contents, f"{path} exists but is empty — download may have been interrupted."


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
    assert "wan2.1-t2v-1.3b" in registry_ids
    assert "wan2.1-t2v-1.3b-vae" in registry_ids
    assert "cogvideox-2b" in registry_ids
    assert "cogvideox-2b-vae" in registry_ids


def test_wan_is_default_sparse_t2v_and_vae():
    from app.rfir.models.registry import default_model_for_role
    from app.rfir.ops.sparse_t2v_window import DEFAULT_MODEL as T2V_DEFAULT
    from app.rfir.ops.vae import DEFAULT_MODEL as VAE_DEFAULT

    assert default_model_for_role("sparse_t2v").id == "wan2.1-t2v-1.3b"
    assert default_model_for_role("vae").id == "wan2.1-t2v-1.3b-vae"
    assert T2V_DEFAULT == "wan2.1-t2v-1.3b"
    assert VAE_DEFAULT == "wan2.1-t2v-1.3b-vae"
