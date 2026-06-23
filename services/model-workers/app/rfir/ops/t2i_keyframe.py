"""Op: t2i_keyframe — generate a keyframe image from a text prompt.

Uses FLUX.1-schnell (primary) or SDXL-Turbo (fallback).
Works on CUDA (fp16/INT4) and MPS (fp16).

Spec reference: rfir-inference-engine-implementation.md §1.4
"""
from __future__ import annotations

import logging
import os
from typing import Any

from PIL import Image

from app.rfir.models.loader import load_model

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "flux-schnell-fp16"
FALLBACK_MODEL = "sdxl-turbo-fp16"


def run(
    prompt: str,
    *,
    model_id: str | None = None,
    width: int = 512,
    height: int = 288,
    steps: int = 4,
    seed: int | None = None,
) -> Image.Image:
    """Generate a single keyframe image from a text prompt."""
    mid = model_id or os.environ.get("RENDERFLOW_RFIR_T2I_MODEL", DEFAULT_MODEL)

    try:
        pipe = load_model(mid)
    except Exception as e:
        logger.warning("Failed to load %s: %s — trying fallback", mid, e)
        mid = FALLBACK_MODEL
        pipe = load_model(mid)

    import torch

    generator = torch.Generator()
    if seed is not None:
        generator.manual_seed(seed)
    else:
        generator.seed()

    logger.info("t2i_keyframe: prompt=%r, model=%s, %dx%d, %d steps", prompt[:60], mid, width, height, steps)

    result = pipe(
        prompt=prompt,
        width=width,
        height=height,
        num_inference_steps=steps,
        generator=generator,
        guidance_scale=0.0 if "flux" in mid else 1.0,
    )

    image: Image.Image = result.images[0]
    return image
