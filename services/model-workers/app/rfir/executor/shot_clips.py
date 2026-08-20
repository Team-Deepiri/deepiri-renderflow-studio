"""Per-shot deliverable paths for mux (step 2 of the ffmpeg assembly pipeline).

Maps shot_index → ordered PNG paths produced by the last clip-registering op
for that shot (t2i still, RIFE sequence, composite, or Tier D vae_decode).
Tier C decode does not register; composite does.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.rfir.ir.types import RfirNode

logger = logging.getLogger(__name__)

DEFAULT_DURATION_SEC = 5.0
DEFAULT_FPS = 24


@dataclass
class ShotClip:
    shot_index: int
    duration_sec: float
    fps: int = DEFAULT_FPS
    kind: str = "frames"  # "still" | "frames"
    paths: list[str] = field(default_factory=list)
    source_node: str = ""


def shot_index_from_node_id(node_id: str) -> int | None:
    """Extract shot index from node IDs like ``s2_rife`` → 2."""
    prefix = node_id.split("_")[0]
    if prefix.startswith("s") and len(prefix) > 1 and prefix[1:].isdigit():
        return int(prefix[1:])
    return None


def shot_index_from_tensor(tensor_name: str) -> int | None:
    """Extract shot index from tensor names like ``s1_keyframe`` → 1."""
    if not tensor_name.startswith("s"):
        return None
    prefix = tensor_name.split("_", 1)[0]
    if len(prefix) > 1 and prefix[1:].isdigit():
        return int(prefix[1:])
    return None


def shot_index_for_node(node: RfirNode, *, batch_index: int | None = None) -> int | None:
    """Resolve the timeline shot index for a node (or one batch output)."""
    if batch_index is not None and node.attrs.get("batch"):
        indices = node.attrs.get("batch_shot_indices")
        if isinstance(indices, list) and batch_index < len(indices):
            return int(indices[batch_index])
        out_tensors = list(node.outputs.values())
        if batch_index < len(out_tensors):
            from_tensor = shot_index_from_tensor(out_tensors[batch_index])
            if from_tensor is not None:
                return from_tensor

    raw = node.attrs.get("shot_index")
    if raw is not None and not node.attrs.get("batch"):
        return int(raw)

    return shot_index_from_node_id(node.id)


def clip_duration_sec(node: RfirNode, shots_meta: list[dict[str, Any]] | None, shot_index: int) -> float:
    if "duration_sec" in node.attrs:
        return float(node.attrs["duration_sec"])
    if shots_meta:
        for entry in shots_meta:
            if int(entry.get("index", -1)) == shot_index:
                return float(entry.get("duration_sec", DEFAULT_DURATION_SEC))
    return DEFAULT_DURATION_SEC


def _validate_paths(paths: list[str]) -> list[str] | None:
    """Return verified paths, or None if any path is missing/empty."""
    verified: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file() or path.stat().st_size <= 0:
            logger.warning("shot_clips: path missing or empty: %s", raw)
            return None
        verified.append(str(path))
    return verified if verified else None


def register_shot_clip(
    ctx: Any,
    shot_index: int,
    paths: list[str],
    node: RfirNode,
    *,
    kind: str | None = None,
) -> None:
    """Record deliverable paths for one shot. Last writer wins per shot_index."""
    if shot_index < 0:
        logger.warning("shot_clips: invalid shot_index %r from %s", shot_index, node.id)
        return

    verified = _validate_paths(paths)
    if verified is None:
        logger.warning("shot_clips: not registering shot %d from %s (bad paths)", shot_index, node.id)
        return

    if kind is None:
        kind = "still" if len(verified) == 1 else "frames"

    shots_meta = getattr(ctx, "_shots_meta", None)
    duration = clip_duration_sec(node, shots_meta, shot_index)
    fps = DEFAULT_FPS
    if kind == "frames" and duration > 0:
        fps = max(1, round(len(verified) / duration))

    ctx.shot_clips[shot_index] = ShotClip(
        shot_index=shot_index,
        duration_sec=duration,
        fps=fps,
        kind=kind,
        paths=verified,
        source_node=node.id,
    )
