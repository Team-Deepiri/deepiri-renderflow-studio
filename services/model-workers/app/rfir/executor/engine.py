"""RFIR Executor — walks a compiled graph and runs each op.

Spec reference: rfir-inference-engine-implementation.md §1.15
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.rfir.arena import TensorArena
from app.rfir.compiler.scheduler import topological_sort
from app.rfir.executor.context import ExecutionContext, decide_escalation
from app.rfir.ir.types import RfirGraph, RfirNode
from app.rfir.models.loader import detect_device, unload_all
from app.rfir.ops import t2i_keyframe, depth_estimate, rife_interpolate

logger = logging.getLogger(__name__)

_OP_HANDLERS: dict[str, Any] = {}


def _register_handlers() -> None:
    _OP_HANDLERS["t2i_keyframe"] = _run_t2i_keyframe
    _OP_HANDLERS["depth_estimate"] = _run_depth_estimate
    _OP_HANDLERS["vulkan_parallax"] = _run_vulkan_parallax_stub
    _OP_HANDLERS["vulkan_upscale"] = _run_vulkan_upscale_stub
    _OP_HANDLERS["ffmpeg_mux"] = _run_ffmpeg_mux
    _OP_HANDLERS["vulkan_composite"] = _noop
    _OP_HANDLERS["vulkan_motion_blur"] = _noop
    _OP_HANDLERS["vae_encode"] = _noop
    _OP_HANDLERS["vae_decode"] = _noop
    _OP_HANDLERS["segment_subject"] = _noop
    _OP_HANDLERS["sparse_t2v_window"] = _noop
    _OP_HANDLERS["rife_interpolate"] = _run_rife_interpolate
    _OP_HANDLERS["plan_shots"] = _noop


def run_graph(graph: RfirGraph, job_id: str, output_dir: str) -> ExecutionContext:
    """Execute all nodes in dependency order. Returns execution context with metrics."""
    if not _OP_HANDLERS:
        _register_handlers()

    device = detect_device()
    ctx = ExecutionContext(job_id=job_id, device=device)
    arena = TensorArena()
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    order = topological_sort(graph)
    logger.info("Executing %d nodes on %s for job %s", len(order), device, job_id)

    try:
        for node_id in order:
            node = graph.get_node(node_id)
            if node is None:
                continue

            handler = _OP_HANDLERS.get(node.op)
            if handler is None:
                logger.warning("No handler for op %s (node %s), skipping", node.op, node_id)
                continue

            t0 = time.monotonic()
            handler(node, arena, ctx, out_path)
            wall_ms = (time.monotonic() - t0) * 1000
            ctx.record_node(node_id, node.op, wall_ms)
            logger.info("  %s (%s): %.0f ms", node_id, node.op, wall_ms)
    finally:
        arena.release_all()
        unload_all()

    return ctx


# ---------------------------------------------------------------------------
# Op handlers
# ---------------------------------------------------------------------------

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
            arena.put(tensor_name, image)
            img_path = out_path / f"{node.id}_{i}.png"
            image.save(img_path)
            ctx.artifacts[f"{node.id}_{i}"] = str(img_path)
        return

    prompt = node.attrs.get("prompt", "")
    image = t2i_keyframe.run(prompt, width=width, height=height, steps=steps, seed=seed)

    for port_name, tensor_name in node.outputs.items():
        arena.put(tensor_name, image)

    img_path = out_path / f"{node.id}.png"
    image.save(img_path)
    ctx.artifacts[node.id] = str(img_path)


def _run_depth_estimate(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
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
    """Create an MP4 from keyframe images using FFmpeg zoompan (Ken Burns effect)."""
    keyframe_pngs = [v for k, v in sorted(ctx.artifacts.items()) if v.endswith(".png") and "depth" not in k]

    if not keyframe_pngs:
        logger.warning("ffmpeg_mux: no keyframe PNGs found")
        return

    output_mp4 = out_path / "output.mp4"

    import subprocess
    import shutil

    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg not found in PATH")
        return

    first_png = keyframe_pngs[0]
    duration = 5
    fps = 24

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", first_png,
        "-vf", f"zoompan=z='min(zoom+0.001,1.2)':d={duration * fps}:s=1920x1080:fps={fps}",
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(output_mp4),
    ]

    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        ctx.artifacts["output_mp4"] = str(output_mp4)
        logger.info("ffmpeg_mux: created %s", output_mp4)
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg_mux failed: %s", e.stderr.decode()[:200] if e.stderr else str(e))
    except FileNotFoundError:
        logger.error("ffmpeg not found")


def _noop(node: RfirNode, arena: TensorArena, ctx: ExecutionContext, out_path: Path) -> None:
    """Placeholder for ops not yet implemented."""
    pass
