"""Op: vae — shared VAE encode (RGB → latent) and decode (latent → RGB).

Uses Wan's AutoencoderKLWan (default) or CogVideoX's AutoencoderKLCogVideoX —
3D video VAEs that operate on (B, C, T, H, W) tensors. A single frame is
encoded/decoded as a 1-frame "video" (T=1). Override with
$RENDERFLOW_RFIR_VAE_MODEL. The executor calls ``unload_all()`` before
encode/decode so the standalone VAE is alone on the accelerator (MPS/CUDA).

Wan multi-frame decode streams one temporal latent at a time (preserving
``feat_cache``) and converts each frame to PIL immediately so the full RGB
video is never accumulated on GPU. After each latent tensor finishes,
accelerator cache is reclaimed without touching arena PIL/keyframe data.

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

from app.rfir.models.loader import load_model, reclaim_accelerator_memory

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

    del tensor
    reclaim_accelerator_memory()

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


def _unpatchify_wan_frame(frame_5d: "torch.Tensor", patch_size: int | None) -> "torch.Tensor":
    """Apply Wan ``unpatchify`` when the VAE config uses spatial patches."""
    if patch_size is None or patch_size == 1:
        return frame_5d
    from diffusers.models.autoencoders.autoencoder_kl_wan import unpatchify

    return unpatchify(frame_5d, patch_size=patch_size)


def _stream_decode_wan(vae: object, latent: "torch.Tensor") -> list[Image.Image]:
    """Decode Wan latents one temporal step at a time without GPU RGB concat.

    Mirrors AutoencoderKLWan._decode's feat_cache loop, but converts each
    frame to PIL immediately so peak memory stays near one-frame decode.
    """
    import torch

    clear_cache = getattr(vae, "clear_cache", None)
    if clear_cache is not None:
        clear_cache()

    x = vae.post_quant_conv(latent)
    num_frame = int(x.shape[2])
    patch_size = getattr(getattr(vae, "config", None), "patch_size", None)
    frames: list[Image.Image] = []

    with torch.no_grad():
        for i in range(num_frame):
            vae._conv_idx = [0]
            kwargs: dict = {"feat_cache": vae._feat_map, "feat_idx": vae._conv_idx}
            if i == 0:
                kwargs["first_chunk"] = True
            out = vae.decoder(x[:, :, i : i + 1, :, :], **kwargs)
            out = _unpatchify_wan_frame(out, patch_size)
            out = torch.clamp(out, min=-1.0, max=1.0)
            frames.append(_tensor_frame_to_pil(out[0, :, 0]))
            del out

    if clear_cache is not None:
        clear_cache()
    del x
    return frames


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
    pipeline_kind = bundle.get("pipeline", "")

    if latent.dim() == 4:
        latent = latent.unsqueeze(2)  # (1, C, H, W) -> (1, C, 1, H, W)
    latent = latent.to(device=device, dtype=dtype)
    latent_shape = list(latent.shape)

    if denormalize is None:
        denormalize = int(latent.shape[2]) > 1
    if denormalize:
        latent = _denormalize_wan_latents(latent, vae)

    frames: list[Image.Image] = []
    try:
        if pipeline_kind == "wan" and hasattr(vae, "decoder") and hasattr(vae, "post_quant_conv"):
            frames = _stream_decode_wan(vae, latent)
        else:
            with torch.no_grad():
                decoded = vae.decode(latent).sample
            t_count = int(decoded.shape[2])
            frames = [_tensor_frame_to_pil(decoded[0, :, t]) for t in range(t_count)]
            del decoded
    finally:
        # Drop decode temps / feat_cache spill and return driver cache before
        # the next latent tensor is processed. Arena PIL outputs are already
        # on CPU and unaffected.
        if hasattr(vae, "clear_cache"):
            vae.clear_cache()
        del latent
        reclaim_accelerator_memory()

    logger.info(
        "vae_decode: latent %s → %d frame(s) %s",
        latent_shape, len(frames), frames[0].size if frames else None,
    )
    if len(frames) == 1:
        return frames[0]
    return frames
