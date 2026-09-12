"""RFIR Executor — walks a compiled graph and runs each op.

Spec reference: rfir-inference-engine-implementation.md §1.15
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.rfir.arena import TensorArena
from app.rfir.budget import BudgetGovernor
from app.rfir.checkpoint import Checkpoint, checkpoint_uri, save as save_checkpoint, load as load_checkpoint, delete as delete_checkpoint
from app.rfir.compiler.scheduler import topological_sort
from app.rfir.executor.context import ExecutionContext, decide_escalation
from app.rfir.ir.types import InferenceBudget, RfirGraph, RfirNode
from app.rfir.models.loader import detect_device, unload_all
from app.rfir.ltc import LatentTemporalCache
from app.rfir.ops import t2i_keyframe, depth_estimate, rife_interpolate, segment_subject, vae, sparse_t2v_window
from app.rfir.ops import ffmpeg_mux as ffmpeg_mux_op

logger = logging.getLogger(__name__)

_OP_HANDLERS: dict[str, Any] = {}


def _register_handlers() -> None:
    _OP_HANDLERS["t2i_keyframe"] = _run_t2i_keyframe
    _OP_HANDLERS["depth_estimate"] = _run_depth_estimate
    _OP_HANDLERS["vulkan_parallax"] = _run_vulkan_parallax_stub
    _OP_HANDLERS["vulkan_upscale"] = _run_vulkan_upscale_stub
    _OP_HANDLERS["ffmpeg_mux"] = _run_ffmpeg_mux
    _OP_HANDLERS["vulkan_composite"] = _run_vulkan_composite
    _OP_HANDLERS["vulkan_motion_blur"] = _noop
    _OP_HANDLERS["vae_encode"] = _run_vae_encode
    _OP_HANDLERS["vae_decode"] = _run_vae_decode
    _OP_HANDLERS["segment_subject"] = _run_segment_subject
    _OP_HANDLERS["sparse_t2v_window"] = _run_sparse_t2v_window
    _OP_HANDLERS["rife_interpolate"] = _run_rife_interpolate
    _OP_HANDLERS["plan_shots"] = _noop


def run_graph(
    graph: RfirGraph,
    job_id: str,
    output_dir: str,
    budget: InferenceBudget | None = None,
    checkpoint_dir: str | None = None,
    on_node_start: Callable[[RfirNode], None] | None = None,
    keyframe_check: Callable[..., Any] | None = None,
) -> ExecutionContext:
    """Execute all nodes in dependency order. Returns execution context with metrics.

    If checkpoint_dir is set, saves state at shot boundaries and supports
    resuming from a prior checkpoint (§4.2 / §4.3).

    on_node_start is invoked with each node before its handler runs, so
    callers can surface per-stage progress. Exceptions it raises propagate
    out of run_graph (after arena/model cleanup), which callers may use to
    abort a cancelled job.
    """
    if not _OP_HANDLERS:
        _register_handlers()

    device = detect_device()
    ctx = ExecutionContext(job_id=job_id, device=device)
    ctx.tier_distribution = dict(graph.metadata.get("tier_distribution", {}))
    ctx.nsfw_mode = graph.metadata.get("nsfw_mode", "block")
    ctx.keyframe_check = keyframe_check
    arena = TensorArena()
    ltc = LatentTemporalCache()
    ctx._ltc = ltc
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    governor = None
    if budget is not None:
        governor = BudgetGovernor(budget, vram_hints=graph.metadata.get("downgrade_hints", []))

    order = topological_sort(graph)

    # Resume from checkpoint if one exists.
    cp_uri = checkpoint_uri(job_id, checkpoint_dir) if checkpoint_dir is not None else None
    start_cursor = 0
    if cp_uri:
        cp = load_checkpoint(cp_uri)
        if cp is not None:
            start_cursor = cp.node_cursor
            ctx.artifacts.update(cp.artifacts)
            ctx.downgrades = cp.downgrades
            if budget is not None:
                budget.spent_gpu_seconds = cp.spent_gpu_seconds
            logger.info("Resuming job %s from node %d/%d (%.1fs GPU spent)",
                        job_id, start_cursor, len(order), cp.spent_gpu_seconds)

    logger.info("Executing %d nodes on %s for job %s (starting at %d)",
                len(order), device, job_id, start_cursor)

    try:
        for cursor, node_id in enumerate(order):
            if cursor < start_cursor:
                continue

            node = graph.get_node(node_id)
            if node is None:
                continue

            handler = _OP_HANDLERS.get(node.op)
            if handler is None:
                logger.warning("No handler for op %s (node %s), skipping", node.op, node_id)
                continue

            if on_node_start is not None:
                on_node_start(node)

            if governor is not None:
                node = governor.before_node(node)

            t0 = time.monotonic()
            handler(node, arena, ctx, out_path)
            wall_ms = (time.monotonic() - t0) * 1000
            ctx.record_node(node_id, node.op, wall_ms, gpu_ms=node.estimated_gpu_ms)
            if governor is not None:
                governor.after_node(node.estimated_gpu_ms / 1000.0)
            logger.info("  %s (%s): %.0f ms", node_id, node.op, wall_ms)

            # Checkpoint at shot boundaries (upscale is the last node per shot).
            if cp_uri and node.op in ("vulkan_upscale", "ffmpeg_mux"):
                shot_idx = _shot_index_from_node_id(node_id)
                spent = budget.spent_gpu_seconds if budget else 0.0
                cp = Checkpoint(
                    job_id=job_id,
                    shot_index=shot_idx,
                    spent_gpu_seconds=spent,
                    node_cursor=cursor + 1,
                    artifacts=dict(ctx.artifacts),
                    tier_distribution=ctx.tier_distribution,
                    downgrades=governor.metrics()["downgrades"] if governor else [],
                )
                save_checkpoint(cp, cp_uri)
    finally:
        arena.release_all()
        ltc.release_all()
        # Keep models resident between jobs by default: unloading throws away
        # the Metal/CUDA-compiled kernels, so the next job pays the full JIT
        # warmup again (~200s on MPS for the SDXL UNet). Opt back into
        # per-job unloading on memory-constrained hosts via env.
        if os.environ.get("RENDERFLOW_RFIR_UNLOAD_MODELS", "0") == "1":
            unload_all()

    if governor is not None:
        ctx.downgrades = governor.metrics()["downgrades"]

    # Clean up checkpoint on successful completion.
    if cp_uri:
        delete_checkpoint(cp_uri)

    from app.rfir.metrics import registry as metrics_registry
    metrics_registry.record_job(ctx)

    return ctx


# ---------------------------------------------------------------------------
# Op handlers
# ---------------------------------------------------------------------------

def _encode_png(image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _run_t2i_keyframe(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    steps = node.attrs.get("steps", 4)
    width = node.attrs.get("width", 512)
    height = node.attrs.get("height", 288)
    seed = node.attrs.get("seed")

    # for fusion shots ("batch" attr)
    if node.attrs.get("batch"):
        prompts = node.attrs.get("prompts", [])
        out_tensors = list(node.outputs.values())  # ordered image_0..image_{n-1}
        for i, (prompt, tensor_name) in enumerate(zip(prompts, out_tensors)):
            image = t2i_keyframe.run(prompt, width=width, height=height, steps=steps, seed=seed)

            if ctx.keyframe_check is not None:
                result = ctx.keyframe_check(_encode_png(image), ctx.nsfw_mode, frame_index=i)
                if not result.passed:
                    raise RuntimeError(f"generation blocked: {node.id}[{i}]: {result.message}")

            arena.put(tensor_name, image)
            img_path = out_path / f"{node.id}_{i}.png"
            image.save(img_path)
            ctx.artifacts[f"{node.id}_{i}"] = str(img_path)
        return

    prompt = node.attrs.get("prompt", "")
    image = t2i_keyframe.run(prompt, width=width, height=height, steps=steps, seed=seed)

    if ctx.keyframe_check is not None:
        result = ctx.keyframe_check(_encode_png(image), ctx.nsfw_mode)
        if not result.passed:
            raise RuntimeError(f"generation blocked: {node.id}: {result.message}")

    for port_name, tensor_name in node.outputs.items():
        arena.put(tensor_name, image)

    img_path = out_path / f"{node.id}.png"
    image.save(img_path)
    ctx.artifacts[node.id] = str(img_path)


def _run_depth_estimate(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    from PIL import Image

    input_tensor = list(node.inputs.values())[0]
    image = arena.get(input_tensor)

    if not isinstance(image, Image.Image):
        logger.warning("depth_estimate: input is not a PIL Image, skipping")
        return

    depth_map = depth_estimate.run(image, infer_scale=float(node.attrs.get("infer_scale", 1.0)))

    for tensor_name in node.outputs.values():
        arena.put(tensor_name, depth_map)

    depth_vis = (depth_map * 255).astype(np.uint8)
    depth_img = Image.fromarray(depth_vis)
    depth_path = out_path / f"{node.id}.png"
    depth_img.save(depth_path)
    ctx.artifacts[node.id] = str(depth_path)


def _run_rife_interpolate(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Tier B: interpolate frames between the start/end keyframes (§2.5)."""
    from PIL import Image

    start_t = node.inputs.get("frame_start", "")
    end_t = node.inputs.get("frame_end", "")
    if not (arena.has(start_t) and arena.has(end_t)):
        logger.warning("rife_interpolate: missing keyframe inputs, skipping")
        return

    start_img = arena.get(start_t)
    end_img = arena.get(end_t)
    if not (isinstance(start_img, Image.Image) and isinstance(end_img, Image.Image)):
        logger.warning("rife_interpolate: inputs are not PIL Images, skipping")
        return

    factor = int(node.attrs.get("factor", 4))
    frames = rife_interpolate.run(start_img, end_img, factor=factor)

    # Publish the frame list. Persistence to disk happens once, at the
    # shot's terminal tensor (Step 3) — not here, which would otherwise
    # write every shot's frames twice (vulkan_upscale is a pass-through
    # stub downstream of this node).
    for tensor_name in node.outputs.values():
        arena.put(tensor_name, frames)

    # SSIM quality gate (§2.6)
    verify_t = node.attrs.get("verify_keyframe")
    if verify_t and arena.has(verify_t) and len(frames) >= 3:
        verify_img = arena.get(verify_t)
        if isinstance(verify_img, Image.Image):
            score = compute_ssim(frames[len(frames) // 2], verify_img)
            decision = decide_escalation(
                score, escalations_remaining=int(node.attrs.get("escalations_remaining", 0))
            )
            ctx.record_escalation(node.id, decision)


def compute_ssim(a: Image.Image, b: Image.Image) -> float:
    """Structural similarity in [0, 1] between two images."""
    from skimage.metrics import structural_similarity as ssim

    arr_a = np.asarray(a.convert("L"), dtype="float32")
    b_resized = b.resize(a.size) if b.size != a.size else b
    arr_b = np.asarray(b_resized.convert("L"), dtype="float32")
    score = ssim(arr_a, arr_b, data_range=255.0)
    return float(max(0.0, min(1.0, score)))


def _run_vulkan_parallax_stub(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Stub: pass through the input image as 'frames' (no actual parallax)."""
    img_tensor = node.inputs.get("image", "")
    if arena.has(img_tensor):
        for tensor_name in node.outputs.values():
            arena.put(tensor_name, arena.get(img_tensor))


def _persist_frames(frames: list, tensor_name: str, ctx: ExecutionContext, out_path: Path) -> str:
    """Write frames as out_path/frames/<tensor>/%05d.png; return the dir.

    Zero-padded so numeric order matches lexicographic order (fixes the
    `_10 < _2` sort bug — Cause 2), and written under a `frames/` subdir so
    the output dir root stays PNG-free (`test_cfsv_pipeline.py:122`, which
    globs non-recursively).
    """
    frame_dir = out_path / "frames" / tensor_name
    frame_dir.mkdir(parents=True, exist_ok=True)
    for i, frame in enumerate(frames):
        frame.save(frame_dir / f"{i:05d}.png")
    ctx.artifacts[f"frames::{tensor_name}"] = str(frame_dir)
    return str(frame_dir)


def _run_vulkan_upscale_stub(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Stub: pass through (no actual upscale).

    This is the terminal node of every current tier's subgraph (Step 3): if
    its output is a frame sequence, persist it to disk now — keyed by
    tensor name so it survives fusion — and drop it from the arena
    (Decision 5). A single still image (today, only Tier A) is left as-is;
    the mux falls back to the keyframe PNG already on disk for that case.
    """
    input_tensor = list(node.inputs.values())[0]
    if not arena.has(input_tensor):
        return

    value = arena.get(input_tensor)
    for tensor_name in node.outputs.values():
        arena.put(tensor_name, value)

    if isinstance(value, list):
        for tensor_name in node.outputs.values():
            _persist_frames(value, tensor_name, ctx, out_path)
            arena.release(tensor_name)
        arena.release(input_tensor)


def _run_ffmpeg_mux(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Concatenate every shot into one output.mp4 (Step 4).

    A thin adapter: resolves each shot's frame dir / still from ctx.artifacts
    (disk, not the arena — Decision 5, and what makes checkpoint-resume work)
    and delegates the actual ffmpeg invocation to ops.ffmpeg_mux.run().
    """
    shots = node.attrs.get("shots", [])
    fps = int(round(float(node.attrs.get("fps", 24))))
    width = int(node.attrs.get("width", 1920))
    height = int(node.attrs.get("height", 1080))

    frame_dirs: dict[str, str] = {}
    stills: dict[str, str] = {}
    for shot in shots:
        tensor = shot.get("output_tensor", "")
        frame_key = f"frames::{tensor}"
        if frame_key in ctx.artifacts:
            frame_dirs[tensor] = ctx.artifacts[frame_key]
            continue
        still_key = f"s{shot.get('index')}_t2i"
        if still_key in ctx.artifacts:
            stills[tensor] = ctx.artifacts[still_key]

    result = ffmpeg_mux_op.run(shots, frame_dirs, stills, out_path, fps=fps, width=width, height=height)
    if result is None:
        logger.error("ffmpeg_mux: failed to produce output.mp4")
        return

    ctx.artifacts["output_mp4"] = result
    logger.info("ffmpeg_mux: created %s", result)

    keep_frames = os.environ.get("RENDERFLOW_RFIR_KEEP_FRAMES", "false").lower() == "true"
    if not keep_frames:
        for tensor, frame_dir in frame_dirs.items():
            shutil.rmtree(frame_dir, ignore_errors=True)
            ctx.artifacts.pop(f"frames::{tensor}", None)


def _run_segment_subject(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Tier C: generate a binary subject mask via SAM2."""
    from PIL import Image

    input_tensor = list(node.inputs.values())[0]
    image = arena.get(input_tensor)

    if not isinstance(image, Image.Image):
        logger.warning("segment_subject: input is not a PIL Image, skipping")
        return

    mask = segment_subject.run(image)

    for tensor_name in node.outputs.values():
        arena.put(tensor_name, mask)

    mask_img = Image.fromarray(mask)
    mask_path = out_path / f"{node.id}.png"
    mask_img.save(mask_path)
    ctx.artifacts[node.id] = str(mask_path)


def _run_vae_encode(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Encode an RGB image to latent space."""
    from PIL import Image

    input_tensor = list(node.inputs.values())[0]
    image = arena.get(input_tensor)

    if not isinstance(image, Image.Image):
        logger.warning("vae_encode: input is not a PIL Image, skipping")
        return

    latent = vae.encode(image)

    for tensor_name in node.outputs.values():
        arena.put(tensor_name, latent)


def _run_vae_decode(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Decode a latent tensor to RGB image(s) (Decision 1 / Cause 1 fix).

    sparse_t2v_window decodes internally and returns list[Image] directly —
    that list arrives here as the "latent" input, so it passes straight
    through. A real latent tensor (no production caller today; kept for the
    graph shape design §4.3/§4.4 draws — §10 known debt) is decoded via
    vae.decode_frames() into the equivalent list. Either way the output
    tensor holds a *sequence*, not a single collapsed frame.
    """
    import torch

    input_tensor = list(node.inputs.values())[0]
    latent = arena.get(input_tensor)

    if isinstance(latent, list):
        frames = latent
    elif isinstance(latent, torch.Tensor):
        frames = vae.decode_frames(latent)
    else:
        logger.warning("vae_decode: input is neither a tensor nor a frame list, skipping")
        return

    for tensor_name in node.outputs.values():
        arena.put(tensor_name, frames)


def _run_sparse_t2v_window(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Tier C/D: sparse windowed text-to-video diffusion."""
    from PIL import Image
    import torch

    prompt = node.attrs.get("prompt", "")
    steps = int(node.attrs.get("steps", 10))
    full_frame = bool(node.attrs.get("full_frame", False))
    window_size = int(node.attrs.get("window_size", 16))
    overlap_val = int(node.attrs.get("overlap", 4))
    num_frames = int(node.attrs.get("num_frames", 24))

    latent_tensor = node.inputs.get("latent", "")
    latent = arena.get(latent_tensor) if arena.has(latent_tensor) else None

    mask_tensor = node.inputs.get("mask", "")
    mask = arena.get(mask_tensor) if arena.has(mask_tensor) else None

    # Find the source image from earlier in the arena (the keyframe).
    image = None
    if latent_tensor:
        # Walk back to find the original image from the VAE encode's input.
        for n in ctx.node_metrics:
            if n.node_id in ctx.artifacts and ctx.artifacts[n.node_id].endswith(".png"):
                try:
                    image = Image.open(ctx.artifacts[n.node_id])
                except Exception:
                    pass

    shot_id = node.id.split("_")[0] if "_" in node.id else node.id
    ltc = getattr(ctx, "_ltc", None)

    frames = sparse_t2v_window.run(
        prompt=prompt,
        latent=latent if isinstance(latent, torch.Tensor) else None,
        mask=mask if isinstance(mask, np.ndarray) else None,
        image=image,
        full_frame=full_frame,
        steps=steps,
        window_size=window_size,
        overlap=overlap_val,
        num_frames=num_frames,
        shot_id=shot_id,
        ltc=ltc,
    )

    # Persistence happens once, at the shot's terminal tensor (Step 3) — not
    # here, which would otherwise write every shot's frames twice
    # (vulkan_upscale/vulkan_composite are pass-through/broadcast downstream
    # of this node for every current tier).
    for tensor_name in node.outputs.values():
        arena.put(tensor_name, frames)


def _run_vulkan_composite(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Tier C: composite foreground over background using mask (PIL fallback).

    Premultiplied alpha: C_out = C_fg + C_bg * (1 - A_fg)
    """
    from PIL import Image

    fg_tensor = node.inputs.get("foreground", "")
    bg_tensor = node.inputs.get("background", "")
    mask_tensor = node.inputs.get("mask", "")

    fg = arena.get(fg_tensor) if arena.has(fg_tensor) else None
    bg = arena.get(bg_tensor) if arena.has(bg_tensor) else None
    mask = arena.get(mask_tensor) if arena.has(mask_tensor) else None

    if fg is None or bg is None:
        logger.warning("vulkan_composite: missing foreground or background, passing through")
        result = fg or bg
        for tensor_name in node.outputs.values():
            arena.put(tensor_name, result)
        return

    # fg may be a list of frames (from sparse_t2v_window) or a single image.
    if isinstance(fg, list):
        bg_img = bg if isinstance(bg, Image.Image) else bg
        mask_pil = Image.fromarray(mask) if isinstance(mask, np.ndarray) else None

        composited = []
        for frame in fg:
            if not isinstance(frame, Image.Image):
                composited.append(frame)
                continue
            frame_resized = frame.resize(bg_img.size) if frame.size != bg_img.size else frame
            if mask_pil is not None:
                mask_resized = mask_pil.resize(bg_img.size)
                comp = Image.composite(frame_resized, bg_img, mask_resized)
            else:
                comp = frame_resized
            composited.append(comp)

        # Persistence happens once, at the shot's terminal tensor (Step 3) —
        # not here; vulkan_upscale downstream broadcasts this list through.
        for tensor_name in node.outputs.values():
            arena.put(tensor_name, composited)
    elif isinstance(fg, Image.Image):
        bg_img = bg if isinstance(bg, Image.Image) else fg
        if isinstance(mask, np.ndarray):
            mask_pil = Image.fromarray(mask).resize(bg_img.size)
            fg_resized = fg.resize(bg_img.size) if fg.size != bg_img.size else fg
            result = Image.composite(fg_resized, bg_img, mask_pil)
        else:
            result = fg
        for tensor_name in node.outputs.values():
            arena.put(tensor_name, result)
    else:
        for tensor_name in node.outputs.values():
            arena.put(tensor_name, fg)


def _shot_index_from_node_id(node_id: str) -> int:
    """Extract the shot index from a node ID like 's2_upscale' → 2."""
    prefix = node_id.split("_")[0]
    if prefix.startswith("s") and prefix[1:].isdigit():
        return int(prefix[1:])
    return -1


def _noop(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Placeholder for ops not yet implemented."""
    pass
