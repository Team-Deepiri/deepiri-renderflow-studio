"""Model loader — load/unload models with CUDA/MPS/CPU auto-detection.

Uses the same device detection pattern as Cyrex (deepiri-modelkit):
CUDA -> MPS -> CPU with real tensor test before committing.

Spec reference: rfir-inference-engine-implementation.md §1.2
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.rfir.models.precision import PrecisionConfig, resolve as resolve_precision
from app.rfir.models.registry import ModelManifest, get_manifest

logger = logging.getLogger(__name__)

_loaded: dict[str, Any] = {}


def detect_device() -> str:
    """Detect best available device: CUDA -> MPS -> CPU.

    Tests with a real tensor op before returning.
    """
    try:
        import torch
    except ImportError:
        return "cpu"

    if torch.cuda.is_available():
        try:
            t = torch.tensor([1.0], device="cuda")
            _ = (t * 2.0).cpu()
            del t
            torch.cuda.empty_cache()
            gpu_name = torch.cuda.get_device_name(0)
            logger.info("CUDA detected: %s", gpu_name)
            return "cuda"
        except RuntimeError as e:
            logger.warning("CUDA available but test failed: %s", e)

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        try:
            t = torch.tensor([1.0], device="mps")
            _ = (t * 2.0).cpu()
            del t
            logger.info("MPS (Apple Silicon) detected")
            return "mps"
        except RuntimeError as e:
            logger.warning("MPS available but test failed: %s", e)

    logger.info("Using CPU (no GPU detected)")
    return "cpu"


def load_model(model_id: str, device: str | None = None) -> Any:
    """Load a model by registry ID. Returns the loaded pipeline/model object."""
    if model_id in _loaded:
        return _loaded[model_id]

    manifest = get_manifest(model_id)
    if manifest is None:
        raise ValueError(f"Unknown model: {model_id!r}")

    device = device or detect_device()
    precision = resolve_precision(device, manifest.vram_mb)

    logger.info("Loading %s on %s (dtype=%s, quant=%s)", model_id, device, precision.torch_dtype, precision.quantization)

    if manifest.role == "t2i_keyframe":
        pipeline = _load_t2i_pipeline(manifest, device, precision)
    elif manifest.role == "depth_estimate":
        pipeline = _load_depth_model(manifest, device, precision)
    elif manifest.role == "plan_shots":
        pipeline = _load_llm(manifest, device)
    else:
        raise ValueError(f"No loader for role: {manifest.role!r}")

    _loaded[model_id] = pipeline
    return pipeline


def unload_model(model_id: str) -> None:
    """Unload a model and free memory."""
    pipeline = _loaded.pop(model_id, None)
    if pipeline is None:
        return
    del pipeline
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    logger.info("Unloaded %s", model_id)


def unload_all() -> None:
    for mid in list(_loaded.keys()):
        unload_model(mid)


def _get_torch_dtype(dtype_str: str):
    import torch
    return {"float16": torch.float16, "bfloat16": torch.bfloat16, "float32": torch.float32}[dtype_str]


def _load_t2i_pipeline(manifest: ModelManifest, device: str, precision: PrecisionConfig) -> Any:
    from diffusers import FluxPipeline, StableDiffusionXLPipeline
    import torch

    torch_dtype = _get_torch_dtype(precision.torch_dtype)
    models_dir = os.environ.get("RENDERFLOW_MODELS_DIR")

    if "flux" in manifest.id:
        repo = models_dir if models_dir and os.path.isdir(os.path.join(models_dir, "flux-schnell")) else manifest.repo
        pipe = FluxPipeline.from_pretrained(repo, torch_dtype=torch_dtype)
    else:
        repo = models_dir if models_dir and os.path.isdir(os.path.join(models_dir, "sdxl-turbo")) else manifest.repo
        pipe = StableDiffusionXLPipeline.from_pretrained(repo, torch_dtype=torch_dtype)

    if device == "mps":
        pipe = pipe.to("mps")
    elif device == "cuda":
        if precision.device_map:
            pass  # already handled by from_pretrained device_map
        else:
            pipe = pipe.to("cuda")
    else:
        pipe = pipe.to("cpu")

    return pipe


def _load_depth_model(manifest: ModelManifest, device: str, precision: PrecisionConfig) -> Any:
    from transformers import AutoModelForDepthEstimation, AutoImageProcessor
    import torch

    torch_dtype = _get_torch_dtype(precision.torch_dtype)
    models_dir = os.environ.get("RENDERFLOW_MODELS_DIR")

    repo = manifest.repo
    if models_dir and os.path.isdir(os.path.join(models_dir, "depth-anything-v2-small")):
        repo = os.path.join(models_dir, "depth-anything-v2-small")

    processor = AutoImageProcessor.from_pretrained(repo)
    model = AutoModelForDepthEstimation.from_pretrained(repo, torch_dtype=torch_dtype)

    if device in ("cuda", "mps"):
        model = model.to(device)

    return {"model": model, "processor": processor, "device": device}


def _load_llm(manifest: ModelManifest, device: str) -> Any:
    from llama_cpp import Llama

    n_ctx = int(manifest.extras.get("n_ctx", 4096))
    filename = manifest.extras.get("filename", "*.gguf")
    n_gpu_layers = -1 if device in ("cuda", "mps") else 0  # -1 = offload all layers

    models_dir = os.environ.get("RENDERFLOW_MODELS_DIR")
    local_dir = os.path.join(models_dir, manifest.id) if models_dir else None
    if local_dir and os.path.isdir(local_dir):
        import glob
        matches = glob.glob(os.path.join(local_dir, filename))
        if not matches:
            raise FileNotFoundError(f"no GGUF matching {filename!r} in {local_dir}")
        return Llama(model_path=matches[0], n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=False)

    # Download (and cache) the quantized file from HuggingFace.
    return Llama.from_pretrained(
        repo_id=manifest.repo,
        filename=filename,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        verbose=False,
    )
