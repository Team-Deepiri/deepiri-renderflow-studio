"""Op: sparse_t2v_window — windowed sparse text-to-video diffusion for Tier C/D.

Tier C: runs diffusion on the ROI (subject mask) crop only, then composites.
Tier D: runs full-frame diffusion (no ROI crop).

Uses Wan2.1-1.3B (default) or CogVideoX-2B via diffusers with sequential CPU
offload so the transformer and VAE are never co-resident on GPU. Override with
$RENDERFLOW_RFIR_T2V_MODEL.

Design reference: rfir-inference-engine-design.md §4.3, §4.4, §5.5
Spec reference: rfir-inference-engine-implementation.md §3.3
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from app.rfir.ltc import (
    LatentTemporalCache,
    blend_overlap,
    cosine_blend_weights,
    sliding_window_ranges,
    warp_latent,
)
from app.rfir.models.loader import load_model

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "wan2.1-t2v-1.3b"
DEFAULT_STEPS = 6
DEFAULT_WINDOW_SIZE = 9
DEFAULT_OVERLAP = 2
DEFAULT_NUM_FRAMES = 17
TIER_D_MAX_DURATION_SEC = 3.0
TIER_D_DEFAULT_FPS = 24


def _crop_to_roi(
    image: Image.Image,
    mask: np.ndarray,
    pad: int = 16,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Crop image to the bounding box of the mask with padding.

    Returns the cropped image and the (x0, y0, x1, y1) bbox.
    """
    ys, xs = np.where(mask > 127)
    if len(ys) == 0:
        return image, (0, 0, image.width, image.height)

    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(image.width, int(xs.max()) + pad)
    y1 = min(image.height, int(ys.max()) + pad)

    # Ensure dimensions are divisible by 16 for CogVideoX & VAE compatibility.
    x1 = x0 + ((x1 - x0) // 16) * 16
    y1 = y0 + ((y1 - y0) // 16) * 16
    if x1 <= x0:
        x1 = x0 + 16
    if y1 <= y0:
        y1 = y0 + 16

    return image.crop((x0, y0, x1, y1)), (x0, y0, x1, y1)


def _paste_roi(
    background: Image.Image,
    roi_frame: Image.Image,
    mask: np.ndarray,
    bbox: tuple[int, int, int, int],
) -> Image.Image:
    """Paste the ROI frame back onto the background using the mask."""
    x0, y0, x1, y1 = bbox
    roi_resized = roi_frame.resize((x1 - x0, y1 - y0), Image.BILINEAR)
    mask_crop = mask[y0:y1, x0:x1]
    mask_pil = Image.fromarray(mask_crop).resize(roi_resized.size, Image.BILINEAR)

    result = background.copy()
    result.paste(roi_resized, (x0, y0), mask_pil)
    return result


def run(
    *,
    prompt: str,
    latent: torch.Tensor | None = None,
    mask: np.ndarray | None = None,
    image: Image.Image | None = None,
    full_frame: bool = False,
    steps: int = DEFAULT_STEPS,
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    num_frames: int = DEFAULT_NUM_FRAMES,
    fps: int = TIER_D_DEFAULT_FPS,
    shot_id: str = "",
    ltc: LatentTemporalCache | None = None,
    model_id: str | None = None,
) -> list[Image.Image]:
    """Generate video frames via sparse windowed diffusion.

    For Tier C (full_frame=False): crops to ROI mask, runs diffusion on crop.
    For Tier D (full_frame=True): runs on the full frame, hard-capped at 3s.

    Returns a list of PIL Images (generated frames).
    """
    import torch

    # Tier D hard duration cap (design doc §4.4: max 3s per hero shot).
    if full_frame:
        max_frames = int(TIER_D_MAX_DURATION_SEC * fps)
        if num_frames > max_frames:
            logger.info("tier_d: capping %d frames to %d (%.1fs at %d fps)",
                        num_frames, max_frames, TIER_D_MAX_DURATION_SEC, fps)
            num_frames = max_frames
    mid = model_id or os.environ.get("RENDERFLOW_RFIR_T2V_MODEL", DEFAULT_MODEL)

    try:
        bundle = load_model(mid)
        pipe = bundle["pipe"]
        device = bundle["device"]
    except Exception as e:
        logger.warning("sparse_t2v model %s unavailable (%s) — returning placeholder frames", mid, e)
        return _placeholder_frames(image, num_frames)

    # ROI crop for Tier C.
    bbox = None
    if not full_frame and mask is not None and image is not None:
        cropped_image, bbox = _crop_to_roi(image, mask)
        gen_width, gen_height = cropped_image.size
        roi_pct = (gen_width * gen_height) / (image.width * image.height) * 100
        logger.info(
            "sparse_t2v_window: ROI crop %dx%d (%.0f%% of frame), %d steps, %d windows",
            gen_width, gen_height, roi_pct, steps,
            len(sliding_window_ranges(num_frames, window_size, overlap)),
        )
    else:
        gen_width = image.width if image else 512
        gen_height = image.height if image else 288
        logger.info("sparse_t2v_window: full frame %dx%d, %d steps", gen_width, gen_height, steps)

    # Ensure dimensions are divisible by 8.
    gen_width = (gen_width // 16) * 16 or 16
    gen_height = (gen_height // 16) * 16 or 16

    # LTC: condition on previous window's last latent if available.
    cache_entry = None
    if ltc is not None and shot_id:
        cache_entry = ltc.get_or_create(shot_id)

    windows = sliding_window_ranges(num_frames, window_size, overlap)
    all_frames: list[Image.Image] = []
    prev_window_frames: torch.Tensor | None = None

    for win_idx, (start, end) in enumerate(windows):
        win_frames = end - start
        logger.info("  window %d/%d: frames %d–%d (%d frames)", win_idx + 1, len(windows), start, end, win_frames)

        # Condition on flow-warped prior latent if LTC has one.
        latent_init = None
        if cache_entry is not None and cache_entry.last_latent is not None:
            if cache_entry.flow_vectors is not None:
                latent_init = warp_latent(cache_entry.last_latent, cache_entry.flow_vectors)
            else:
                latent_init = cache_entry.last_latent

        try:
            result = pipe(
                prompt=prompt,
                num_frames=win_frames,
                width=gen_width,
                height=gen_height,
                num_inference_steps=steps,
                guidance_scale=6.0,
                latents=latent_init,
            )
            window_images = result.frames[0] if hasattr(result, "frames") else result.images
        except Exception as e:
            logger.warning("sparse_t2v_window inference failed (%s) — using placeholders for window", e)
            window_images = _placeholder_frames(image, win_frames)

        # Convert to tensors for overlap blending.
        window_tensors = torch.stack([
            torch.from_numpy(np.array(f, dtype=np.float32)).permute(2, 0, 1)
            for f in window_images
        ])

        # Cosine blend with previous window's overlap region.
        if prev_window_frames is not None and overlap > 0 and win_idx > 0:
            blended = blend_overlap(prev_window_frames, window_tensors, overlap)
            # Replace the overlap region in window_tensors.
            actual_ov = blended.shape[0]
            window_tensors = torch.cat([blended, window_tensors[actual_ov:]], dim=0)
            # Only append the non-overlapping portion to all_frames.
            new_images = [
                Image.fromarray(window_tensors[i].permute(1, 2, 0).to(torch.uint8).numpy())
                for i in range(actual_ov, window_tensors.shape[0])
            ]
            # Replace the last `actual_ov` frames with blended versions.
            blended_images = [
                Image.fromarray(blended[i].permute(1, 2, 0).clamp(0, 255).to(torch.uint8).numpy())
                for i in range(actual_ov)
            ]
            all_frames[-actual_ov:] = blended_images
            all_frames.extend(new_images)
        else:
            all_frames.extend([
                Image.fromarray(window_tensors[i].permute(1, 2, 0).to(torch.uint8).numpy())
                for i in range(window_tensors.shape[0])
            ])

        prev_window_frames = window_tensors

        # Update LTC with last frame's state.
        if cache_entry is not None and len(window_images) > 0:
            last_tensor = window_tensors[-1].unsqueeze(0) / 255.0
            ltc.update(shot_id, last_tensor)

    # Tier C: paste ROI frames back onto the background.
    if bbox is not None and image is not None and mask is not None:
        all_frames = [_paste_roi(image, f, mask, bbox) for f in all_frames]

    logger.info("sparse_t2v_window: generated %d frames total", len(all_frames))
    return all_frames[:num_frames]


def _placeholder_frames(image: Image.Image | None, count: int) -> list[Image.Image]:
    """Generate placeholder frames when the model is unavailable."""
    if image is not None:
        return [image.copy() for _ in range(count)]
    placeholder = Image.new("RGB", (512, 288), color=(64, 64, 64))
    return [placeholder.copy() for _ in range(count)]
