"""RFIR Compiler — Build pass: ShotList → RfirGraph.

Creates one subgraph per shot based on its tier, then merges into a single graph.

Tier A: t2i_keyframe → depth_estimate → vulkan_parallax → vulkan_upscale
Tier B: t2i_keyframe(start) + t2i_keyframe(end) → rife_interpolate → vulkan_upscale
Tier C: t2i_keyframe(bg) → depth + segment_subject → vae_encode → sparse_t2v_window → vae_decode → vulkan_composite → vulkan_upscale
Tier D: t2i_keyframe → vae_encode → sparse_t2v_window(full) → vae_decode → vulkan_upscale

Spec reference: rfir-inference-engine-implementation.md §0.4
"""
from __future__ import annotations

from app.rfir.ir.types import (
    InferenceBudget,
    RfirGraph,
    RfirNode,
    RoutingPolicy,
    Shot,
    ShotList,
    TensorDevice,
    TensorDtype,
    TensorLifetime,
    TensorSpec,
    Tier,
)


class CompileError(Exception):
    pass


def build(
    shot_list: ShotList,
    budget: InferenceBudget | None = None,
    ai_enabled: bool = True,
    routing: RoutingPolicy | None = None,
) -> RfirGraph:
    """Compile a ShotList into an RfirGraph."""
    if not ai_enabled:
        raise CompileError("AI is disabled for this project")

    if not shot_list.shots:
        raise CompileError("ShotList is empty")

    budget = budget or InferenceBudget()
    routing = routing or RoutingPolicy()

    if routing.local_only and not routing.cloud_allowed:
        pass  # local_only already caps tier; cloud_allowed=false is redundant

    graph = RfirGraph(metadata={
        "prompt": shot_list.prompt,
        "shot_count": len(shot_list.shots),
        "total_duration_sec": shot_list.total_duration_sec(),
        "routing": {"local_only": routing.local_only, "cloud_allowed": routing.cloud_allowed},
    })

    tier_distribution: dict[str, int] = {}
    for shot in shot_list.shots:
        effective_tier = _cap_tier(shot.tier, budget.max_tier)
        effective_tier = routing.effective_max_tier(effective_tier)
        tier_distribution[effective_tier.value] = tier_distribution.get(effective_tier.value, 0) + 1
        _build_shot_subgraph(graph, shot, effective_tier)

    # Record the *effective* (post-cap) tier mix for job metrics (§12).
    graph.metadata["tier_distribution"] = tier_distribution

    graph.nodes.append(RfirNode(
        id="mux",
        op="ffmpeg_mux",
        inputs={"frames": _last_output_tensor(graph)},
    ))

    return graph


def _cap_tier(requested: Tier, max_tier: Tier) -> Tier:
    order = [Tier.A, Tier.B, Tier.C, Tier.D]
    max_idx = order.index(max_tier)
    req_idx = order.index(requested)
    if req_idx > max_idx:
        return max_tier
    return requested


def _build_shot_subgraph(graph: RfirGraph, shot: Shot, tier: Tier) -> None:
    prefix = f"s{shot.index}"

    if tier == Tier.A:
        _build_tier_a(graph, prefix, shot)
    elif tier == Tier.B:
        _build_tier_b(graph, prefix, shot)
    elif tier == Tier.C:
        _build_tier_c(graph, prefix, shot)
    elif tier == Tier.D:
        _build_tier_d(graph, prefix, shot)


def _add_tensor(graph: RfirGraph, name: str, dtype: TensorDtype, lifetime: TensorLifetime = TensorLifetime.SHOT) -> str:
    graph.tensors[name] = TensorSpec(name=name, dtype=dtype, shape=[1, 3, 288, 512], lifetime=lifetime)
    return name


def _build_tier_a(graph: RfirGraph, prefix: str, shot: Shot) -> None:
    img = _add_tensor(graph, f"{prefix}_keyframe", TensorDtype.RGB_U8)
    depth = _add_tensor(graph, f"{prefix}_depth", TensorDtype.DEPTH_F32)
    frames = _add_tensor(graph, f"{prefix}_parallax", TensorDtype.RGB_U8)
    out = _add_tensor(graph, f"{prefix}_upscaled", TensorDtype.RGB_U8)

    graph.nodes.extend([
        RfirNode(
            id=f"{prefix}_t2i", op="t2i_keyframe",
            outputs={"image": img},
            attrs={"prompt": shot.description, "steps": 2},
            estimated_gpu_ms=800, vram_mb=6144,
        ),
        RfirNode(
            id=f"{prefix}_depth", op="depth_estimate",
            inputs={"image": img}, outputs={"depth": depth},
            estimated_gpu_ms=50, vram_mb=1024,
        ),
        RfirNode(
            id=f"{prefix}_parallax", op="vulkan_parallax",
            inputs={"image": img, "depth": depth}, outputs={"frames": frames},
            attrs={"camera": shot.camera.motion.value, "duration_sec": shot.duration_sec},
        ),
        RfirNode(
            id=f"{prefix}_upscale", op="vulkan_upscale",
            inputs={"image": frames}, outputs={"image_out": out},
        ),
    ])


def _build_tier_b(graph: RfirGraph, prefix: str, shot: Shot) -> None:
    img_start = _add_tensor(graph, f"{prefix}_kf_start", TensorDtype.RGB_U8)
    img_end = _add_tensor(graph, f"{prefix}_kf_end", TensorDtype.RGB_U8)
    interp = _add_tensor(graph, f"{prefix}_interp", TensorDtype.RGB_U8)
    out = _add_tensor(graph, f"{prefix}_upscaled", TensorDtype.RGB_U8)

    graph.nodes.extend([
        RfirNode(
            id=f"{prefix}_t2i_start", op="t2i_keyframe",
            outputs={"image": img_start},
            attrs={"prompt": shot.description, "steps": 2, "keyframe": "start"},
            estimated_gpu_ms=800, vram_mb=6144,
        ),
        RfirNode(
            id=f"{prefix}_t2i_end", op="t2i_keyframe",
            outputs={"image": img_end},
            attrs={"prompt": shot.description, "steps": 2, "keyframe": "end"},
            estimated_gpu_ms=800, vram_mb=6144,
        ),
        RfirNode(
            id=f"{prefix}_rife", op="rife_interpolate",
            inputs={"frame_start": img_start, "frame_end": img_end},
            outputs={"frames": interp},
            estimated_gpu_ms=200, vram_mb=2048,
        ),
        RfirNode(
            id=f"{prefix}_upscale", op="vulkan_upscale",
            inputs={"image": interp}, outputs={"image_out": out},
        ),
    ])


def _build_tier_c(graph: RfirGraph, prefix: str, shot: Shot) -> None:
    bg_img = _add_tensor(graph, f"{prefix}_bg", TensorDtype.RGB_U8)
    bg_depth = _add_tensor(graph, f"{prefix}_bg_depth", TensorDtype.DEPTH_F32)
    bg_frames = _add_tensor(graph, f"{prefix}_bg_parallax", TensorDtype.RGB_U8)
    mask = _add_tensor(graph, f"{prefix}_mask", TensorDtype.MASK_U8)
    latent_in = _add_tensor(graph, f"{prefix}_latent_in", TensorDtype.LATENT_F16)
    latent_out = _add_tensor(graph, f"{prefix}_latent_out", TensorDtype.LATENT_F16)
    fg_frames = _add_tensor(graph, f"{prefix}_fg", TensorDtype.RGB_U8)
    composite = _add_tensor(graph, f"{prefix}_composite", TensorDtype.RGB_U8)
    out = _add_tensor(graph, f"{prefix}_upscaled", TensorDtype.RGB_U8)

    graph.nodes.extend([
        # Background plate (Tier A)
        RfirNode(
            id=f"{prefix}_bg_t2i", op="t2i_keyframe",
            outputs={"image": bg_img},
            attrs={"prompt": shot.description, "steps": 2},
            estimated_gpu_ms=800, vram_mb=6144,
        ),
        RfirNode(
            id=f"{prefix}_bg_depth", op="depth_estimate",
            inputs={"image": bg_img}, outputs={"depth": bg_depth},
            estimated_gpu_ms=50, vram_mb=1024,
        ),
        RfirNode(
            id=f"{prefix}_bg_parallax", op="vulkan_parallax",
            inputs={"image": bg_img, "depth": bg_depth}, outputs={"frames": bg_frames},
            attrs={"camera": shot.camera.motion.value, "duration_sec": shot.duration_sec},
        ),
        # Subject ROI
        RfirNode(
            id=f"{prefix}_segment", op="segment_subject",
            inputs={"image": bg_img}, outputs={"mask": mask},
            estimated_gpu_ms=100, vram_mb=2048,
        ),
        RfirNode(
            id=f"{prefix}_vae_enc", op="vae_encode",
            inputs={"image": bg_img}, outputs={"latent": latent_in},
            estimated_gpu_ms=30, vram_mb=1024,
        ),
        RfirNode(
            id=f"{prefix}_t2v", op="sparse_t2v_window",
            inputs={"latent": latent_in, "mask": mask}, outputs={"latent_out": latent_out},
            attrs={
                "prompt": shot.description,
                "steps": 6,
                "window_size": 9,
                "overlap": 2,
                "num_frames": 9,
            },
            estimated_gpu_ms=3000, vram_mb=8192,
        ),
        RfirNode(
            id=f"{prefix}_vae_dec", op="vae_decode",
            inputs={"latent": latent_out}, outputs={"image": fg_frames},
            estimated_gpu_ms=30, vram_mb=1024,
        ),
        # Composite
        RfirNode(
            id=f"{prefix}_comp", op="vulkan_composite",
            inputs={"foreground": fg_frames, "background": bg_frames, "mask": mask},
            outputs={"image": composite},
        ),
        RfirNode(
            id=f"{prefix}_upscale", op="vulkan_upscale",
            inputs={"image": composite}, outputs={"image_out": out},
        ),
    ])


TIER_D_MAX_DURATION_SEC = 3.0


def _build_tier_d(graph: RfirGraph, prefix: str, shot: Shot) -> None:
    capped_duration = min(shot.duration_sec, TIER_D_MAX_DURATION_SEC)
    img = _add_tensor(graph, f"{prefix}_keyframe", TensorDtype.RGB_U8)
    latent_in = _add_tensor(graph, f"{prefix}_latent_in", TensorDtype.LATENT_F16)
    latent_out = _add_tensor(graph, f"{prefix}_latent_out", TensorDtype.LATENT_F16)
    frames = _add_tensor(graph, f"{prefix}_frames", TensorDtype.RGB_U8)
    out = _add_tensor(graph, f"{prefix}_upscaled", TensorDtype.RGB_U8)

    graph.nodes.extend([
        RfirNode(
            id=f"{prefix}_t2i", op="t2i_keyframe",
            outputs={"image": img},
            attrs={"prompt": shot.description, "steps": 2},
            estimated_gpu_ms=800, vram_mb=6144,
        ),
        RfirNode(
            id=f"{prefix}_vae_enc", op="vae_encode",
            inputs={"image": img}, outputs={"latent": latent_in},
            estimated_gpu_ms=30, vram_mb=1024,
        ),
        RfirNode(
            id=f"{prefix}_t2v", op="sparse_t2v_window",
            inputs={"latent": latent_in, "mask": f"{prefix}_dummy_mask"},
            outputs={"latent_out": latent_out},
            attrs={
                "prompt": shot.description,
                "steps": 6,
                "window_size": 9,
                "overlap": 2,
                "num_frames": 9,
                "full_frame": True,
                "duration_sec": capped_duration,
            },
            estimated_gpu_ms=5000, vram_mb=8192,
        ),
        RfirNode(
            id=f"{prefix}_vae_dec", op="vae_decode",
            inputs={"latent": latent_out}, outputs={"image": frames},
            estimated_gpu_ms=30, vram_mb=1024,
        ),
        RfirNode(
            id=f"{prefix}_upscale", op="vulkan_upscale",
            inputs={"image": frames}, outputs={"image_out": out},
        ),
    ])
    # Tier D needs a full-frame mask placeholder
    _add_tensor(graph, f"{prefix}_dummy_mask", TensorDtype.MASK_U8)


def _last_output_tensor(graph: RfirGraph) -> str:
    """Find the last upscaled tensor to feed into ffmpeg_mux."""
    for node in reversed(graph.nodes):
        if node.op == "vulkan_upscale" and "image_out" in node.outputs:
            return node.outputs["image_out"]
    for node in reversed(graph.nodes):
        if node.outputs:
            return next(iter(node.outputs.values()))
    return ""
