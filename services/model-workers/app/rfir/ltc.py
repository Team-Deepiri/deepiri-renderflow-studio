"""Latent Temporal Cache (LTC) — window overlap blending and flow warp for Tier C/D.

Caches the last-frame latent, text embedding, and motion vectors per shot
so sliding diffusion windows can be conditioned on prior context rather
than starting cold.

Design reference: rfir-inference-engine-design.md §5.5
Spec reference: rfir-inference-engine-implementation.md §3.4
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_SIZE = 16
DEFAULT_OVERLAP = 4
DEFAULT_STEP = 12  # window_size - overlap


@dataclass
class LatentCacheEntry:
    """Per-shot latent cache state."""
    last_latent: torch.Tensor | None = None
    text_embedding: torch.Tensor | None = None
    flow_vectors: torch.Tensor | None = None
    dit_kv_state: Any = None
    window_index: int = 0


class LatentTemporalCache:
    """Manages per-shot cache entries during Tier C/D execution."""

    def __init__(self) -> None:
        self._entries: dict[str, LatentCacheEntry] = {}

    def get_or_create(self, shot_id: str) -> LatentCacheEntry:
        if shot_id not in self._entries:
            self._entries[shot_id] = LatentCacheEntry()
        return self._entries[shot_id]

    def update(
        self,
        shot_id: str,
        latent: torch.Tensor,
        flow: torch.Tensor | None = None,
        text_embedding: torch.Tensor | None = None,
    ) -> None:
        entry = self.get_or_create(shot_id)
        entry.last_latent = latent.detach()
        entry.window_index += 1
        if flow is not None:
            entry.flow_vectors = flow.detach()
        if text_embedding is not None:
            entry.text_embedding = text_embedding.detach()

    def release(self, shot_id: str) -> None:
        self._entries.pop(shot_id, None)

    def release_all(self) -> None:
        self._entries.clear()


def cosine_blend_weights(overlap: int, device: torch.device | str = "cpu") -> torch.Tensor:
    """Generate cosine blend weights for the overlap region.

    Returns a 1D tensor of shape (overlap,) with values in [0, 1].
    The weight ramps from 0 → 1 for the incoming window.
    Multiply the outgoing window by (1 - weights).
    """
    import torch

    if overlap <= 0:
        return torch.zeros(0, device=device)
    t = torch.linspace(0.0, 1.0, overlap, device=device)
    return 0.5 * (1.0 - torch.cos(t * torch.pi))


def blend_overlap(
    prev_frames: torch.Tensor,
    curr_frames: torch.Tensor,
    overlap: int,
) -> torch.Tensor:
    """Cosine-blend the overlap region between two consecutive windows.

    Both tensors have shape (T, C, H, W) or (T, H, W).
    prev_frames: the last `overlap` frames of the previous window.
    curr_frames: the first `overlap` frames of the current window.

    Returns the blended overlap frames with the same shape.
    """
    if overlap <= 0 or prev_frames.shape[0] == 0 or curr_frames.shape[0] == 0:
        return curr_frames

    actual_overlap = min(overlap, prev_frames.shape[0], curr_frames.shape[0])
    prev_tail = prev_frames[-actual_overlap:]
    curr_head = curr_frames[:actual_overlap]

    weights = cosine_blend_weights(actual_overlap, device=curr_frames.device)
    # Reshape weights for broadcasting: (T,) → (T, 1, 1, 1) or (T, 1, 1)
    for _ in range(curr_head.dim() - 1):
        weights = weights.unsqueeze(-1)

    blended = prev_tail * (1.0 - weights) + curr_head * weights
    return blended


def warp_latent(
    latent: torch.Tensor,
    flow: torch.Tensor,
) -> torch.Tensor:
    """Warp a latent using optical flow vectors.

    latent: (1, C, H, W) or (C, H, W)
    flow: (1, 2, H, W) or (2, H, W) — (dx, dy) displacement field

    Returns the warped latent with the same shape.
    """
    import torch

    squeeze = latent.dim() == 3
    if squeeze:
        latent = latent.unsqueeze(0)
        flow = flow.unsqueeze(0) if flow.dim() == 3 else flow

    B, C, H, W = latent.shape
    flow = flow.to(device=latent.device, dtype=latent.dtype)

    if flow.shape[-2:] != (H, W):
        flow = torch.nn.functional.interpolate(flow, size=(H, W), mode="bilinear", align_corners=False)

    # Build sampling grid: identity + flow, normalized to [-1, 1].
    grid_y, grid_x = torch.meshgrid(
        torch.linspace(-1, 1, H, device=latent.device),
        torch.linspace(-1, 1, W, device=latent.device),
        indexing="ij",
    )
    grid = torch.stack([grid_x, grid_y], dim=-1).unsqueeze(0).expand(B, -1, -1, -1)

    # Normalize flow to [-1, 1] range.
    flow_norm = torch.zeros_like(flow)
    flow_norm[:, 0] = flow[:, 0] / (W / 2.0)
    flow_norm[:, 1] = flow[:, 1] / (H / 2.0)
    flow_grid = flow_norm.permute(0, 2, 3, 1)  # (B, H, W, 2)

    sample_grid = grid + flow_grid
    warped = torch.nn.functional.grid_sample(
        latent, sample_grid, mode="bilinear", padding_mode="border", align_corners=True,
    )

    if squeeze:
        warped = warped.squeeze(0)
    return warped


def compute_flow_raft(
    frame_a: torch.Tensor,
    frame_b: torch.Tensor,
    device: str = "cpu",
) -> torch.Tensor:
    """Compute optical flow between two RGB frames using RAFT-small.

    Both frames: (3, H, W) uint8 or float tensors.
    Returns flow: (1, 2, H, W) float tensor.
    """
    import torch
    from torchvision.models.optical_flow import raft_small, Raft_Small_Weights

    weights = Raft_Small_Weights.DEFAULT
    transforms = weights.transforms()

    if frame_a.dtype == torch.uint8:
        frame_a = frame_a.float()
    if frame_b.dtype == torch.uint8:
        frame_b = frame_b.float()

    a_batch, b_batch = transforms(frame_a.unsqueeze(0), frame_b.unsqueeze(0))
    a_batch = a_batch.to(device)
    b_batch = b_batch.to(device)

    model = raft_small(weights=weights).to(device).eval()
    with torch.no_grad():
        flow_list = model(a_batch, b_batch)

    return flow_list[-1]  # (1, 2, H, W)


def sliding_window_ranges(
    total_frames: int,
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[tuple[int, int]]:
    """Compute (start, end) index pairs for sliding windows over a frame sequence."""
    if total_frames <= 0:
        return []
    if total_frames <= window_size:
        return [(0, total_frames)]

    step = max(1, window_size - overlap)
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total_frames:
        end = min(start + window_size, total_frames)
        ranges.append((start, end))
        if end >= total_frames:
            break
        start += step
    return ranges
