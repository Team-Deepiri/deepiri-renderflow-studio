"""Op: vae — shared VAE encode (RGB → latent) and decode (latent → RGB).

Uses CogVideoX's AutoencoderKLCogVideoX from diffusers — a 3D video VAE that
operates on (B, C, T, H, W) tensors, not plain 2D images. A single frame is
encoded/decoded as a 1-frame "video" (T=1). The VAE is shared across shots
to avoid redundant weight loads. Works on CUDA, MPS (fp16), and CPU (fp32).

Spec reference: rfir-inference-engine-implementation.md §3.2
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from app.rfir.models.loader import load_model

if TYPE_CHECKING:
    import torch

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
    import torch

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


def decode_frames(
    latent: torch.Tensor,
    *,
    model_id: str | None = None,
) -> list[Image.Image]:
    """Decode every frame in a (1, C, T, H', W') latent.

    Accepts a tensor of shape (1, C, T, H', W') or (1, C, H', W'), which is
    promoted to T=1. Returns one PIL Image per frame (Decision 1 — Tier C/D
    need the whole sequence, not just frame 0).
    """
    import torch

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

    # decoded: (1, 3, T, H, W). Denormalize from [-1, 1] to [0, 255] and
    # split into one PIL Image per frame.
    decoded = (decoded.clamp(-1, 1) + 1.0) / 2.0 * 255.0
    num_frames = decoded.shape[2]
    frames = []
    for t in range(num_frames):
        frame = decoded[0, :, t].permute(1, 2, 0).cpu().to(torch.uint8).numpy()
        frames.append(Image.fromarray(frame))

    logger.info("vae_decode: latent %s → %d image(s)", list(latent.shape), len(frames))
    return frames


def decode(
    latent: torch.Tensor,
    *,
    model_id: str | None = None,
) -> Image.Image:
    """Decode a latent tensor back to a single RGB PIL image (first frame).

    Thin wrapper over decode_frames() kept for callers that only ever want
    one frame.
    """
    return decode_frames(latent, model_id=model_id)[0]
