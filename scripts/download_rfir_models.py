#!/usr/bin/env python3
"""Download RFIR model weights to RENDERFLOW_MODELS_DIR.

Usage:
    export RENDERFLOW_MODELS_DIR=$HOME/renderflow-models
    pip install huggingface_hub
    python scripts/download_rfir_models.py

FLUX.1-schnell is gated — accept the license on HuggingFace then run:
    huggingface-cli login
before downloading. The script skips it gracefully if you're not logged in.
"""
from __future__ import annotations

import os
import sys

try:
    from huggingface_hub import snapshot_download
except ImportError:
    sys.exit("huggingface_hub is required: pip install huggingface_hub")

MODELS_DIR = os.environ.get("RENDERFLOW_MODELS_DIR")
if not MODELS_DIR:
    sys.exit(
        "RENDERFLOW_MODELS_DIR is not set.\n"
        "Run: export RENDERFLOW_MODELS_DIR=$HOME/renderflow-models"
    )

os.makedirs(MODELS_DIR, exist_ok=True)
print(f"Models root: {MODELS_DIR}\n")


def download(repo_id: str, local_name: str, allow_patterns: list[str] | None = None) -> None:
    dest = os.path.join(MODELS_DIR, local_name)
    if os.path.isdir(dest) and os.listdir(dest):
        print(f"  skip  {local_name}")
        return
    print(f"  fetch {repo_id} → {local_name}")
    try:
        snapshot_download(repo_id=repo_id, local_dir=dest, allow_patterns=allow_patterns)
        print(f"  done  {local_name}")
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "gated" in msg.lower() or "access" in msg.lower():
            print(f"  skip  {local_name} (gated — run: huggingface-cli login, then retry)")
        else:
            print(f"  fail  {local_name}: {exc}")


# T2I keyframes
download("black-forest-labs/FLUX.1-schnell", "flux-schnell")
download("stabilityai/sdxl-turbo", "sdxl-turbo")

# Depth estimation
download("depth-anything/Depth-Anything-V2-Small-hf", "depth-anything-v2-small")

# Shot planner — only the q4_k_m GGUF file (~2 GB instead of the full repo)
download(
    "Qwen/Qwen2.5-3B-Instruct-GGUF",
    "qwen2.5-3b-instruct-gguf",
    allow_patterns=["*q4_k_m.gguf"],
)

# Segmentation
download("facebook/sam2-hiera-tiny", "sam2-hiera-tiny")

# Sparse T2V + VAE (shared checkpoints).
download("Wan-AI/Wan2.1-T2V-1.3B-Diffusers", "wan2.1-t2v-1.3b")
download("THUDM/CogVideoX-2b", "cogvideox-2b")

# Keyframe safety classifier (~330 MB)
download("Falconsai/nsfw_image_detection", "nsfw-image-detection")

print("\nDone.")
