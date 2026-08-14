"""Op: vae — shared VAE encode (RGB → latent) and decode (latent → RGB).

Uses Wan's AutoencoderKLWan (default) or CogVideoX's AutoencoderKLCogVideoX —
3D video VAEs that operate on (B, C, T, H, W) tensors. A single frame is
encoded/decoded as a 1-frame "video" (T=1). Override with
$RENDERFLOW_RFIR_VAE_MODEL. The executor unloads T2V transformer weights
before loading the standalone VAE so they are never co-resident on GPU.

For Wan, latents from the diffusion pipeline are denormalized with
``latents_mean`` / ``latents_std`` before decode (same as WanPipeline).

Spec reference: rfir-inference-engine-implementation.md §3.2
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from app.rfir.models.loader import load_model

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "wan2.1-t2v-1.3b-vae"


def encode(
    image: Image.Image,
    *,
    model_id: str | None = None,
) -> torch.Tensor:
    """Encode an RGB PIL image to a latent tensor.

    Returns a float16/float32 tensor of shape (1, C, 1, H', W') on the model
    device — the VAE is 3D (video) and requires a temporal dimension even for
    a single frame.
    """
    import torch

    mid = model_id or os.environ.get("RENDERFLOW_RFIR_VAE_MODEL", DEFAULT_MODEL)
    bundle = load_model(mid)
    vae = bundle["vae"]
    device = bundle["device"]
    dtype = bundle["dtype"]

    rgb = image.convert("RGB")
    arr = np.array(rgb, dtype=np.float32) / 255.0
    tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).unsqueeze(2)  # (1, 3, 1, H, W)
    tensor = tensor.to(device=device, dtype=dtype)
    # Normalize to [-1, 1] as expected by most VAEs.
    tensor = tensor * 2.0 - 1.0

    with torch.no_grad():
        latent = vae.encode(tensor).latent_dist.sample()

    logger.info("vae_encode: %s → latent %s on %s", image.size, list(latent.shape), device)
    return latent


def _denormalize_wan_latents(latent: "torch.Tensor", vae: object) -> "torch.Tensor":
    """Apply WanPipeline's pre-decode latent mean/std transform when configured."""
    import torch

    cfg = getattr(vae, "config", None)
    mean = getattr(cfg, "latents_mean", None) if cfg is not None else None
    std = getattr(cfg, "latents_std", None) if cfg is not None else None
    if mean is None or std is None:
        return latent

    z_dim = int(getattr(cfg, "z_dim", latent.shape[1]))
    latents_mean = (
        torch.tensor(mean, device=latent.device, dtype=latent.dtype)
        .view(1, z_dim, 1, 1, 1)
    )
    latents_std = (
        1.0
        / torch.tensor(std, device=latent.device, dtype=latent.dtype)
        .view(1, z_dim, 1, 1, 1)
    )
    return latent / latents_std + latents_mean


def _tensor_frame_to_pil(frame: "torch.Tensor") -> Image.Image:
    """(3, H, W) float in roughly [-1, 1] → RGB PIL."""
    import torch

    frame = (frame.clamp(-1, 1) + 1.0) / 2.0 * 255.0
    arr = frame.permute(1, 2, 0).cpu().to(torch.uint8).numpy()
    return Image.fromarray(arr)


def decode(
    latent: torch.Tensor,
    *,
    model_id: str | None = None,
    denormalize: bool | None = None,
) -> Image.Image | list[Image.Image]:
    """Decode a latent tensor back to RGB.

    Accepts ``(1, C, T, H', W')`` (or ``(1, C, H', W')`` promoted to T=1).
    Returns a single ``Image`` when T=1, otherwise a list of frames.

    ``denormalize``: when True, apply Wan ``latents_mean``/``latents_std``
    (required for diffusion latents from ``output_type="latent"``). Default
    is True for T>1 video clips and False for single-frame encode/decode.
    """
    import torch

    mid = model_id or os.environ.get("RENDERFLOW_RFIR_VAE_MODEL", DEFAULT_MODEL)
    bundle = load_model(mid)
    vae = bundle["vae"]
    device = bundle["device"]
    dtype = bundle["dtype"]

    if latent.dim() == 4:
        latent = latent.unsqueeze(2)  # (1, C, H, W) -> (1, C, 1, H, W)
    latent = latent.to(device=device, dtype=dtype)

    if denormalize is None:
        denormalize = int(latent.shape[2]) > 1
    if denormalize:
        latent = _denormalize_wan_latents(latent, vae)

    with torch.no_grad():
        decoded = vae.decode(latent).sample

    # decoded: (1, 3, T, H, W)
    t_count = int(decoded.shape[2])
    frames = [_tensor_frame_to_pil(decoded[0, :, t]) for t in range(t_count)]

    logger.info(
        "vae_decode: latent %s → %d frame(s) %s",
        list(latent.shape), len(frames), frames[0].size if frames else None,
    )
    if len(frames) == 1:
        return frames[0]
    return frames
