"""Op: vae — shared VAE encode (RGB → latent) and decode (latent → RGB).

Uses CogVideoX's AutoencoderKLCogVideoX from diffusers — a 3D video VAE that
operates on (B, C, T, H, W) tensors, not plain 2D images. A single frame is
encoded/decoded as a 1-frame "video" (T=1). The VAE is shared across shots
to avoid redundant weight loads. Works on CUDA, MPS (fp16), and CPU (fp32).

Spec reference: rfir-inference-engine-implementation.md §3.2
"""
from __future__ import annotations

import logging

import numpy as np
import torch
from PIL import Image

from app.rfir.models.loader import load_model

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "cogvideox-2b-vae"


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
    mid = model_id or DEFAULT_MODEL
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


def decode(
    latent: torch.Tensor,
    *,
    model_id: str | None = None,
) -> Image.Image:
    """Decode a latent tensor back to an RGB PIL image.

    Accepts a tensor of shape (1, C, T, H', W') (T=1 for a single frame, the
    common case here) or (1, C, H', W'), which is promoted to T=1. Returns a
    PIL Image of the first decoded frame.
    """
    mid = model_id or DEFAULT_MODEL
    bundle = load_model(mid)
    vae = bundle["vae"]
    device = bundle["device"]
    dtype = bundle["dtype"]

    if latent.dim() == 4:
        latent = latent.unsqueeze(2)  # (1, C, H, W) -> (1, C, 1, H, W)
    latent = latent.to(device=device, dtype=dtype)

    with torch.no_grad():
        decoded = vae.decode(latent).sample

    # decoded: (1, 3, T, H, W) -> take the first frame -> (3, H, W)
    frame = decoded[0, :, 0]
    # Denormalize from [-1, 1] to [0, 255].
    frame = (frame.clamp(-1, 1) + 1.0) / 2.0 * 255.0
    frame = frame.permute(1, 2, 0).cpu().to(torch.uint8).numpy()

    logger.info("vae_decode: latent %s → image %s", list(latent.shape), frame.shape[:2])
    return Image.fromarray(frame)
