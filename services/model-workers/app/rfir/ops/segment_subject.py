"""Op: segment_subject — generate a binary subject mask using SAM2.

Uses sam2-hiera-tiny for speed. The mask isolates the main subject (ROI)
so Tier C can run sparse diffusion on the subject region only.

Works on CUDA, MPS (fp16), and CPU (fp32).

Spec reference: rfir-inference-engine-implementation.md §3.1
"""
from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from app.rfir.models.loader import load_model

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sam2-hiera-tiny"


def run(
    image: Image.Image,
    *,
    model_id: str | None = None,
    center_point: tuple[int, int] | None = None,
) -> np.ndarray:
    """Segment the main subject and return a binary mask.

    Returns a uint8 numpy array (H, W) with 255 for subject, 0 for background.
    If no center_point is given, uses the image center as the prompt.
    """
    mid = model_id or DEFAULT_MODEL
    bundle = load_model(mid)
    predictor = bundle["predictor"]
    device = bundle["device"]

    rgb = np.array(image.convert("RGB"))
    predictor.set_image(rgb)

    h, w = rgb.shape[:2]
    if center_point is None:
        center_point = (w // 2, h // 2)

    point_coords = np.array([[center_point[0], center_point[1]]], dtype=np.float32)
    point_labels = np.array([1], dtype=np.int32)  # 1 = foreground

    masks, scores, _ = predictor.predict(
        point_coords=point_coords,
        point_labels=point_labels,
        multimask_output=True,
    )

    # Pick the mask with the highest confidence.
    best_idx = int(np.argmax(scores))
    mask = masks[best_idx]

    mask_u8 = (mask.astype(np.uint8)) * 255

    fg_ratio = mask.sum() / mask.size
    logger.info(
        "segment_subject: %dx%d, point=(%d,%d), score=%.3f, fg=%.1f%%",
        w, h, center_point[0], center_point[1], scores[best_idx], fg_ratio * 100,
    )

    return mask_u8
