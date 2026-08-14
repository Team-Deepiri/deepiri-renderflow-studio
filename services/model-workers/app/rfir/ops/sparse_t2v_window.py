"""Op: sparse_t2v_window — windowed sparse text-to-video diffusion for Tier C/D.

Tier C: runs diffusion on the ROI (subject mask) crop only, then composites.
Tier D: runs full-frame diffusion (no ROI crop).

Uses Wan2.1-1.3B (default) or CogVideoX-2B via diffusers with sequential CPU
offload so the transformer and VAE are never co-resident on GPU. Override with
$RENDERFLOW_RFIR_T2V_MODEL.

Returns **latents** (not RGB). The graph's standalone ``vae_decode`` is the
single decode step (``output_type="latent"`` on the pipeline).

Design reference: rfir-inference-engine-design.md §4.3, §4.4, §5.5
Spec reference: rfir-inference-engine-implementation.md §3.3
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from app.rfir.ltc import (
    LatentTemporalCache,
    blend_overlap,
    sliding_window_ranges,
    warp_latent,
)
from app.rfir.models.loader import load_model

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "wan2.1-t2v-1.3b"
DEFAULT_STEPS = 12
DEFAULT_WINDOW_SIZE = 17
DEFAULT_OVERLAP = 4
DEFAULT_NUM_FRAMES = 21
TIER_D_MAX_DURATION_SEC = 3.0
TIER_D_DEFAULT_FPS = 24
DEFAULT_TEMPORAL_SCALE = 4


@dataclass
class SparseT2VResult:
    """Latent video clip plus optional Tier-C ROI paste metadata."""

    latents: "torch.Tensor"  # (B, C, T, H, W)
    bbox: tuple[int, int, int, int] | None = None


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


def _video_frames_to_latent_frames(num_frames: int, temporal_scale: int) -> int:
    return (num_frames - 1) // temporal_scale + 1


def _latent_overlap_frames(video_overlap: int, temporal_scale: int) -> int:
    """Map RGB-frame overlap to compressed latent temporal overlap."""
    if video_overlap <= 0:
        return 0
    return max(1, (video_overlap - 1) // temporal_scale + 1)


def _to_tchw(latents: "torch.Tensor") -> "torch.Tensor":
    """(B, C, T, H, W) → (T, C, H, W)."""
    if latents.dim() != 5:
        raise ValueError(f"expected 5D latents (B,C,T,H,W), got {tuple(latents.shape)}")
    return latents[0].permute(1, 0, 2, 3).contiguous()


def _from_tchw(tchw: "torch.Tensor") -> "torch.Tensor":
    """(T, C, H, W) → (1, C, T, H, W)."""
    return tchw.permute(1, 0, 2, 3).unsqueeze(0).contiguous()


def _temporal_scale(pipe: Any) -> int:
    scale = getattr(pipe, "vae_scale_factor_temporal", None)
    if scale is None and getattr(pipe, "vae", None) is not None:
        scale = getattr(pipe.vae.config, "scale_factor_temporal", None)
    return int(scale) if scale else DEFAULT_TEMPORAL_SCALE


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
) -> SparseT2VResult | None:
    """Generate video **latents** via sparse windowed diffusion.

    For Tier C (full_frame=False): crops to ROI mask, runs diffusion on crop.
    For Tier D (full_frame=True): runs on the full frame, hard-capped at 3s.

    Returns a ``SparseT2VResult`` with shape ``(1, C, T, H, W)``, or ``None``
    if the model is unavailable / all windows fail.
    """
    import torch

    # Tier D hard duration cap (design doc §4.4: max 3s per hero shot).
    if full_frame:
        max_frames = int(TIER_D_MAX_DURATION_SEC * fps)
        if num_frames > max_frames:
            logger.info(
                "tier_d: capping %d frames to %d (%.1fs at %d fps)",
                num_frames, max_frames, TIER_D_MAX_DURATION_SEC, fps,
            )
            num_frames = max_frames
    mid = model_id or os.environ.get("RENDERFLOW_RFIR_T2V_MODEL", DEFAULT_MODEL)

    try:
        bundle = load_model(mid)
        pipe = bundle["pipe"]
    except Exception as e:
        logger.warning("sparse_t2v model %s unavailable (%s) — no latents", mid, e)
        return None

    temporal_scale = _temporal_scale(pipe)
    latent_ov = _latent_overlap_frames(overlap, temporal_scale)

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

    # Ensure dimensions are divisible by 16.
    gen_width = (gen_width // 16) * 16 or 16
    gen_height = (gen_height // 16) * 16 or 16

    cache_entry = None
    if ltc is not None and shot_id:
        cache_entry = ltc.get_or_create(shot_id)

    windows = sliding_window_ranges(num_frames, window_size, overlap)
    all_tchw: torch.Tensor | None = None
    prev_window_tchw: torch.Tensor | None = None

    for win_idx, (start, end) in enumerate(windows):
        win_frames = end - start
        expected_t = _video_frames_to_latent_frames(win_frames, temporal_scale)
        logger.info(
            "  window %d/%d: frames %d–%d (%d video → %d latent)",
            win_idx + 1, len(windows), start, end, win_frames, expected_t,
        )

        latent_init = None
        if cache_entry is not None and cache_entry.last_latent is not None:
            cand = cache_entry.last_latent
            if cache_entry.flow_vectors is not None and cand.dim() == 4:
                cand = warp_latent(cand, cache_entry.flow_vectors)
            # Only feed init latents when the full window shape matches.
            if cand.dim() == 5 and cand.shape[2] == expected_t:
                latent_init = cand

        try:
            result = pipe(
                prompt=prompt,
                num_frames=win_frames,
                width=gen_width,
                height=gen_height,
                num_inference_steps=steps,
                guidance_scale=6.0,
                latents=latent_init,
                output_type="latent",
            )
            raw = result.frames if hasattr(result, "frames") else result[0]
            if not isinstance(raw, torch.Tensor):
                raise TypeError(f"expected latent tensor, got {type(raw)}")
            window_latents = raw if raw.dim() == 5 else raw.unsqueeze(0)
            window_latents = window_latents.detach().to(device="cpu", dtype=torch.float32)
        except Exception as e:
            logger.warning("sparse_t2v_window inference failed (%s) — skipping window", e)
            continue

        window_tchw = _to_tchw(window_latents)

        if prev_window_tchw is not None and latent_ov > 0 and win_idx > 0 and all_tchw is not None:
            blended = blend_overlap(prev_window_tchw, window_tchw, latent_ov)
            actual_ov = blended.shape[0]
            all_tchw = torch.cat(
                [all_tchw[:-actual_ov], blended, window_tchw[actual_ov:]],
                dim=0,
            )
        else:
            all_tchw = window_tchw if all_tchw is None else torch.cat([all_tchw, window_tchw], dim=0)

        prev_window_tchw = window_tchw

        if cache_entry is not None:
            # Cache last latent frame as (1, C, H, W) for LTC / warp.
            last = window_latents[:, :, -1].detach()
            ltc.update(shot_id, last)

    if all_tchw is None:
        logger.warning("sparse_t2v_window: no windows succeeded")
        return None

    # Trim to the latent length implied by the requested video frame count.
    target_t = _video_frames_to_latent_frames(num_frames, temporal_scale)
    if all_tchw.shape[0] > target_t:
        all_tchw = all_tchw[:target_t]

    out = _from_tchw(all_tchw)
    logger.info(
        "sparse_t2v_window: latents %s (bbox=%s)",
        list(out.shape), bbox,
    )
    return SparseT2VResult(latents=out, bbox=bbox)
