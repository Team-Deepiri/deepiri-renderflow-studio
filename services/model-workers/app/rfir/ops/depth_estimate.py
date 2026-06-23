"""Op: depth_estimate — generate a depth map from an RGB image.

Uses Depth Anything V2 Small. Works on CUDA and MPS (fp16).

Spec reference: rfir-inference-engine-implementation.md §1.5
"""
from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from app.rfir.models.loader import load_model

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "depth-anything-v2-small"


def run(image: Image.Image, *, model_id: str | None = None) -> np.ndarray:
    """Estimate a depth map from an RGB image.

    Returns a float32 numpy array (H, W) with values in [0, 1].
    """
    import torch

    mid = model_id or DEFAULT_MODEL
    bundle = load_model(mid)
    model = bundle["model"]
    processor = bundle["processor"]
    device = bundle["device"]

    logger.info("depth_estimate: %dx%d, model=%s, device=%s", image.width, image.height, mid, device)

    inputs = processor(images=image, return_tensors="pt")
    if device in ("cuda", "mps"):
        inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        depth = outputs.predicted_depth

    depth = torch.nn.functional.interpolate(
        depth.unsqueeze(1),
        size=(image.height, image.width),
        mode="bicubic",
        align_corners=False,
    ).squeeze()

    depth_np = depth.cpu().numpy()
    depth_min = depth_np.min()
    depth_max = depth_np.max()
    if depth_max - depth_min > 0:
        depth_np = (depth_np - depth_min) / (depth_max - depth_min)
    else:
        depth_np = np.zeros_like(depth_np)

    return depth_np.astype(np.float32)
