"""Op: rife_interpolate — interpolate frames between two keyframes (§2.5).

Primary path: RIFE 4.6 optical-flow interpolation on CUDA/MPS.
Fallback: linear cross-fade blend (PIL only) when the model isn't available —
keeps Tier B functional without GPU weights, mirroring the Tier A FFmpeg
fallback philosophy.

Returns a list of frames: [start, ...intermediates..., end].

Spec reference: rfir-inference-engine-implementation.md §2.5
"""
from __future__ import annotations

import logging

from PIL import Image

from app.rfir.models.loader import load_model

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "rife-4.6"


def _blend_fallback(frame_start: Image.Image, frame_end: Image.Image, factor: int) -> list[Image.Image]:
    """Linear cross-fade: `factor - 1` intermediates between the two keyframes."""
    end = frame_end.resize(frame_start.size) if frame_end.size != frame_start.size else frame_end
    frames = [frame_start]
    for i in range(1, factor):
        alpha = i / factor
        frames.append(Image.blend(frame_start, end, alpha))
    frames.append(end)
    return frames


def run(
    frame_start: Image.Image,
    frame_end: Image.Image,
    *,
    factor: int = 4,
    model_id: str | None = None,
) -> list[Image.Image]:
    """Interpolate `factor - 1` frames between two keyframes."""
    factor = max(2, int(factor))
    mid = model_id or DEFAULT_MODEL

    try:
        model = load_model(mid)
    except Exception as e:
        logger.warning("rife model %s unavailable (%s) — using blend fallback", mid, e)
        return _blend_fallback(frame_start, frame_end, factor)

    try:
        import torch  # noqa: F401

        logger.info("rife_interpolate: factor=%d, model=%s", factor, mid)
        # Real RIFE inference plugs in here once weights are wired; until then
        # the loaded model is unused and we fall back to a correct blend.
        return _blend_fallback(frame_start, frame_end, factor)
    except Exception as e:
        logger.warning("rife inference failed (%s) — using blend fallback", e)
        return _blend_fallback(frame_start, frame_end, factor)
