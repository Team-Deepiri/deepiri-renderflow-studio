"""Op: rife_interpolate — interpolate frames between two keyframes.

Primary path: RIFE 4.6 optical-flow interpolation on CUDA/MPS (vendored net,
loaded via the model loader / registry as role "rife_interpolate").
Fallback: linear cross-fade blend (PIL only) when the model or its weights
aren't available — keeps Tier B/C functional without GPU weights, mirroring the
Tier A FFmpeg fallback philosophy.

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
    """Interpolate `factor - 1` frames between two keyframes.

    Returns `[start, *intermediates, end]` — `factor + 1` frames total. Returns linear-blend 
    function if RIFE 4.6 couldn't be loaded
    """
    factor = max(2, int(factor))
    mid = model_id or DEFAULT_MODEL

    try:
        model = load_model(mid)
    except Exception as e:  # noqa: BLE001 - missing weights/arch → blend
        logger.warning("rife model %s unavailable (%s) — using blend fallback", mid, e)
        return _blend_fallback(frame_start, frame_end, factor)

    try:
        logger.info("rife_interpolate: real RIFE, factor=%d, model=%s", factor, mid)
        intermediates = model.interpolate(frame_start, frame_end, factor)
        return [frame_start, *intermediates, frame_end]
    except Exception as e:  # noqa: BLE001 - runtime inference failure → blend
        logger.warning("rife inference failed (%s) — using blend fallback", e)
        return _blend_fallback(frame_start, frame_end, factor)
