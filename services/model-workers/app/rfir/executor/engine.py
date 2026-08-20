"""RFIR Executor — walks a compiled graph and runs each op.

Spec reference: rfir-inference-engine-implementation.md §1.15
"""
from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.rfir.arena import TensorArena
from app.rfir.budget import BudgetGovernor
from app.rfir.checkpoint import Checkpoint, checkpoint_uri, save as save_checkpoint, load as load_checkpoint, delete as delete_checkpoint
from app.rfir.compiler.scheduler import topological_sort
from app.rfir.executor.context import ExecutionContext, decide_escalation
from app.rfir.executor.ffmpeg_mux import assemble_output_mp4
from app.rfir.executor.shot_clips import register_shot_clip, shot_index_for_node, shot_index_from_node_id
from app.rfir.ir.types import InferenceBudget, RfirGraph, RfirNode
from app.rfir.models.loader import detect_device, reclaim_accelerator_memory, unload_all, unload_model
from app.rfir.ltc import LatentTemporalCache
from app.rfir.ops import t2i_keyframe, depth_estimate, rife_interpolate, segment_subject, vae, sparse_t2v_window

logger = logging.getLogger(__name__)

_T2V_PIPELINE_IDS = (
    "wan2.1-t2v-1.3b",
    "cogvideox-2b",
)
_STANDALONE_VAE_IDS = (
    "wan2.1-t2v-1.3b-vae",
    "cogvideox-2b-vae",
)
_PRE_T2V_UNLOAD_IDS = (
    "sdxl-turbo-fp16",
    "flux-schnell-fp16",
    "qwen2.5-3b-instruct-gguf",
    "depth-anything-v2-small",
    "sam2-hiera-tiny",
    "rife-4.6",
    "nsfw-image-detection",
    *_STANDALONE_VAE_IDS,
)

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
    ctx._shots_meta = graph.metadata.get("shots")
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
            if cp.shot_clips:
                ctx.shot_clips.update(cp.shot_clips)
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
                shot_idx = shot_index_from_node_id(node_id) or -1
                spent = budget.spent_gpu_seconds if budget else 0.0
                cp = Checkpoint(
                    job_id=job_id,
                    shot_index=shot_idx,
                    spent_gpu_seconds=spent,
                    node_cursor=cursor + 1,
                    artifacts=dict(ctx.artifacts),
                    shot_clips=dict(ctx.shot_clips),
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
            shot_idx = shot_index_for_node(node, batch_index=i)
            if shot_idx is not None:
                register_shot_clip(ctx, shot_idx, [str(img_path)], node, kind="still")
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
    shot_idx = shot_index_for_node(node)
    if shot_idx is not None:
        register_shot_clip(ctx, shot_idx, [str(img_path)], node, kind="still")


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

    # Publish the frame list to every output tensor and save PNGs for the mux.
    for tensor_name in node.outputs.values():
        arena.put(tensor_name, frames)
    for i, frame in enumerate(frames):
        frame_path = out_path / f"{node.id}_{i}.png"
        frame.save(frame_path)
        ctx.artifacts[f"{node.id}_{i}"] = str(frame_path)

    shot_idx = shot_index_for_node(node)
    if shot_idx is not None:
        paths = [str(out_path / f"{node.id}_{i}.png") for i in range(len(frames))]
        register_shot_clip(ctx, shot_idx, paths, node, kind="frames")

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


def _run_vulkan_upscale_stub(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Stub: pass through (no actual upscale)."""
    input_tensor = list(node.inputs.values())[0]
    if arena.has(input_tensor):
        for tensor_name in node.outputs.values():
            arena.put(tensor_name, arena.get(input_tensor))


def _run_ffmpeg_mux(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Stitch ``ctx.shot_clips`` in shot-index order into ``output.mp4``."""
    _ = (node, arena)
    ctx.artifacts["output_mp4"] = str(assemble_output_mp4(ctx.shot_clips, out_path))
    logger.info("ffmpeg_mux: created %s from %d shot(s)", ctx.artifacts["output_mp4"], len(ctx.shot_clips))


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

    # Unload other models and always empty CUDA/MPS cache before VAE work.
    unload_all()

    latent = vae.encode(image)

    for tensor_name in node.outputs.values():
        arena.put(tensor_name, latent)

    reclaim_accelerator_memory()


def _run_vae_decode(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Decode a latent tensor to RGB (single frame or list of video frames)."""
    import torch
    from PIL import Image

    input_tensor = list(node.inputs.values())[0]
    latent = arena.get(input_tensor)

    if not isinstance(latent, torch.Tensor):
        logger.warning("vae_decode: input is not a tensor, skipping")
        return

    # Unload other models and always empty CUDA/MPS cache before VAE work.
    unload_all()

    decoded = vae.decode(latent, denormalize=True)

    roi_meta = getattr(ctx, "_roi_meta", None)
    src_meta = roi_meta.get(input_tensor) if isinstance(roi_meta, dict) else None

    for tensor_name in node.outputs.values():
        arena.put(tensor_name, decoded)
        if src_meta is not None and isinstance(roi_meta, dict):
            roi_meta[tensor_name] = src_meta

    if isinstance(decoded, list):
        frame_paths: list[str] = []
        for i, frame in enumerate(decoded):
            if isinstance(frame, Image.Image):
                frame_path = out_path / f"{node.id}_{i}.png"
                frame.save(frame_path)
                ctx.artifacts[f"{node.id}_{i}"] = str(frame_path)
                frame_paths.append(str(frame_path))
        if decoded and isinstance(decoded[0], Image.Image):
            ctx.artifacts[node.id] = ctx.artifacts.get(f"{node.id}_0", "")
        # Tier C: register_clip=False — mux must wait for a successful composite.
        if node.attrs.get("register_clip", True):
            shot_idx = shot_index_for_node(node)
            if shot_idx is not None and frame_paths:
                register_shot_clip(ctx, shot_idx, frame_paths, node, kind="frames")
    elif isinstance(decoded, Image.Image):
        img_path = out_path / f"{node.id}.png"
        decoded.save(img_path)
        ctx.artifacts[node.id] = str(img_path)
        if node.attrs.get("register_clip", True):
            shot_idx = shot_index_for_node(node)
            if shot_idx is not None:
                register_shot_clip(ctx, shot_idx, [str(img_path)], node, kind="still")

    # Arena already holds PIL outputs; reclaim GPU cache for the next op/tensor.
    reclaim_accelerator_memory()


def _run_sparse_t2v_window(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Tier C/D: sparse windowed text-to-video diffusion → latents."""
    from PIL import Image
    import torch

    prompt = node.attrs.get("prompt", "")
    steps = int(node.attrs.get("steps", 12))
    full_frame = bool(node.attrs.get("full_frame", False))
    window_size = int(node.attrs.get("window_size", 17))
    overlap_val = int(node.attrs.get("overlap", 4))
    num_frames = int(node.attrs.get("num_frames", 21))

    latent_tensor = node.inputs.get("latent", "")
    latent = arena.get(latent_tensor) if arena.has(latent_tensor) else None

    mask_tensor = node.inputs.get("mask", "")
    mask = arena.get(mask_tensor) if arena.has(mask_tensor) else None

    image_tensor = node.inputs.get("image", "")
    image = arena.get(image_tensor) if image_tensor and arena.has(image_tensor) else None
    if not isinstance(image, Image.Image):
        image = None

    shot_id = node.id.split("_")[0] if "_" in node.id else node.id
    ltc = getattr(ctx, "_ltc", None)

    for model in _PRE_T2V_UNLOAD_IDS:
        unload_model(model)

    # Prefer remote T2V when startup probe found heartbeat + shared storage.
    latents = None
    bbox = None
    try:
        from app.t2v_remote_client import remote_t2v_available, run_remote_sparse_t2v

        if remote_t2v_available():
            # Gen resolution from image / defaults (ROI sizing still local later).
            if image is not None:
                width, height = image.size
            else:
                width, height = 512, 288
            width = max(16, (width // 16) * 16)
            height = max(16, (height // 16) * 16)
            latents = run_remote_sparse_t2v(
                job_id=getattr(ctx, "job_id", "") or "job",
                op_id=node.id,
                prompt=prompt,
                width=width,
                height=height,
                num_frames=num_frames,
                steps=steps,
                window_size=window_size,
                overlap=overlap_val,
                full_frame=full_frame,
            )
            logger.info("sparse_t2v_window: remote latents %s for %s", tuple(latents.shape), node.id)
    except Exception as e:
        logger.warning("sparse_t2v_window: remote failed (%s) — falling back to local", e)
        latents = None

    if latents is None:
        result = sparse_t2v_window.run(
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
        if result is None:
            logger.warning("sparse_t2v_window: no latents produced for %s", node.id)
            return
        latents = result.latents
        bbox = result.bbox

    for tensor_name in node.outputs.values():
        arena.put(tensor_name, latents)

    # Stash ROI paste metadata for vulkan_composite (decode still returns ROI RGB).
    if bbox is not None and isinstance(mask, np.ndarray) and image is not None:
        roi_meta = getattr(ctx, "_roi_meta", None)
        if roi_meta is None:
            roi_meta = {}
            ctx._roi_meta = roi_meta
        for tensor_name in node.outputs.values():
            roi_meta[tensor_name] = {
                "bbox": bbox,
                "mask": mask,
                "background": image,
            }
            # Also key by the upcoming decode output name pattern via node id.
            roi_meta[node.id] = roi_meta[tensor_name]


def _pil_frames(value: Any) -> list[Any] | None:
    """Normalize a single PIL image or a list into a list. None if unusable."""
    from PIL import Image

    if isinstance(value, Image.Image):
        return [value]
    if isinstance(value, list) and value:
        return value
    return None


def _bg_plate_at(bg_frames: list[Any], index: int):
    from PIL import Image

    if index < len(bg_frames) and isinstance(bg_frames[index], Image.Image):
        return bg_frames[index]
    first = bg_frames[0]
    return first if isinstance(first, Image.Image) else None


def _expected_composite_size(node: RfirNode, plate) -> tuple[int, int]:
    """Plate size, optionally overridden by node width/height attrs."""
    width = node.attrs.get("width")
    height = node.attrs.get("height")
    if width is not None and height is not None:
        return (int(width), int(height))
    return plate.size


def _persist_composite_shot(
    node: RfirNode,
    ctx: ExecutionContext,
    out_path: Path,
    frames: list[Any],
    expected_size: tuple[int, int],
) -> None:
    """Write every composited frame. On any failure, delete partial files and
    do not record artifacts — a failed composite must not look like a shot.
    """
    from PIL import Image

    written: list[Path] = []
    artifact_keys: list[str] = []
    try:
        for i, frame in enumerate(frames):
            if not isinstance(frame, Image.Image) or frame.size != expected_size:
                raise ValueError(
                    f"frame {i} size {getattr(frame, 'size', None)} != {expected_size}"
                )
            dest = out_path / f"{node.id}_{i}.png"
            frame.save(dest)
            if not dest.is_file() or dest.stat().st_size <= 0:
                raise OSError(f"composite PNG missing or empty: {dest}")
            written.append(dest)
            key = f"{node.id}_{i}"
            ctx.artifacts[key] = str(dest)
            artifact_keys.append(key)
        ctx.artifacts[node.id] = str(written[0])
        shot_idx = shot_index_for_node(node)
        if shot_idx is not None:
            register_shot_clip(
                ctx,
                shot_idx,
                [str(p) for p in written],
                node,
                kind="frames" if len(written) > 1 else "still",
            )
    except Exception as e:
        logger.error("vulkan_composite: persist failed for %s (%s) — dropping shot files", node.id, e)
        for key in artifact_keys:
            ctx.artifacts.pop(key, None)
        ctx.artifacts.pop(node.id, None)
        for path in written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("vulkan_composite: could not remove partial file %s", path)
        raise RuntimeError(
            f"vulkan_composite: {node.id}: decoded frames could not be composited: persist failed ({e})"
        ) from e


def _run_vulkan_composite(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Tier C: composite foreground over background using mask (PIL fallback).

    Premultiplied alpha: C_out = C_fg + C_bg * (1 - A_fg)

    When FG frames are ROI-sized (post ``vae_decode`` of sparse T2V latents),
    paste via ``_paste_roi`` using bbox from the T2V step (or re-derived mask).

    Persists every composited frame as ``{node.id}_{i}.png``. Missing inputs,
    empty sequences, or plate-size mismatches raise: decoded frames that cannot
    be composited are a failed Tier C shot, not a silent still.
    """
    from PIL import Image

    fg_tensor = node.inputs.get("foreground", "")
    bg_tensor = node.inputs.get("background", "")
    mask_tensor = node.inputs.get("mask", "")

    fg = arena.get(fg_tensor) if arena.has(fg_tensor) else None
    bg = arena.get(bg_tensor) if arena.has(bg_tensor) else None
    mask = arena.get(mask_tensor) if arena.has(mask_tensor) else None

    def _fail(reason: str) -> None:
        result = fg or bg
        for tensor_name in node.outputs.values():
            arena.put(tensor_name, result)
        raise RuntimeError(
            f"vulkan_composite: {node.id}: decoded frames could not be composited: {reason}"
        )

    fg_frames = _pil_frames(fg)
    bg_frames = _pil_frames(bg)
    if fg_frames is None or bg_frames is None:
        _fail("missing foreground or background")

    roi_meta = getattr(ctx, "_roi_meta", {}) or {}
    # Decode output tensor may be keyed; also try shot prefix from node id.
    meta = roi_meta.get(fg_tensor)
    if meta is None:
        shot_prefix = node.id.rsplit("_", 1)[0] if "_" in node.id else node.id
        meta = roi_meta.get(f"{shot_prefix}_t2v") or roi_meta.get(f"{shot_prefix}_latent_out")

    def _composite_one(frame: Image.Image, bg_img: Image.Image) -> Image.Image:
        if isinstance(mask, np.ndarray) and frame.size != bg_img.size:
            bbox = meta["bbox"] if meta and "bbox" in meta else None
            if bbox is None:
                _, bbox = sparse_t2v_window._crop_to_roi(bg_img, mask)
            return sparse_t2v_window._paste_roi(bg_img, frame, mask, bbox)
        if isinstance(mask, np.ndarray):
            mask_pil = Image.fromarray(mask).resize(bg_img.size)
            frame_resized = frame.resize(bg_img.size) if frame.size != bg_img.size else frame
            return Image.composite(frame_resized, bg_img, mask_pil)
        return frame.resize(bg_img.size) if frame.size != bg_img.size else frame

    plate0 = _bg_plate_at(bg_frames, 0)
    if plate0 is None:
        _fail("background is not a PIL image")

    expected_size = _expected_composite_size(node, plate0)
    composited: list[Any] = []
    for i, frame in enumerate(fg_frames):
        bg_img = _bg_plate_at(bg_frames, i)
        if not isinstance(frame, Image.Image) or bg_img is None:
            _fail(f"invalid frame {i}")
        out = _composite_one(frame, bg_img)
        if not isinstance(out, Image.Image) or out.size != expected_size:
            _fail(f"frame {i} size {getattr(out, 'size', None)} != expected {expected_size}")
        composited.append(out)

    result: Any = composited[0] if len(composited) == 1 else composited
    for tensor_name in node.outputs.values():
        arena.put(tensor_name, result)
    _persist_composite_shot(node, ctx, out_path, composited, expected_size)


def _noop(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Placeholder for ops not yet implemented."""
    pass
