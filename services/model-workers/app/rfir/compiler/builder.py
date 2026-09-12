"""RFIR Compiler — Build pass: ShotList → RfirGraph.

Creates one subgraph per shot based on its tier, then merges into a single graph.

Tier A: t2i_keyframe → depth_estimate → vulkan_parallax → vulkan_upscale
Tier B: t2i_keyframe(start) + t2i_keyframe(end) → rife_interpolate → vulkan_upscale
Tier C: t2i_keyframe(bg) → depth + segment_subject → vae_encode → sparse_t2v_window → vae_decode → vulkan_composite → vulkan_upscale
Tier D: t2i_keyframe → vae_encode → sparse_t2v_window(full) → vae_decode → vulkan_upscale

Spec reference: rfir-inference-engine-implementation.md §0.4
Mux/manifest reference: docs/specs/rfir-mp4-output-pipeline.md §6 Step 1
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


DEFAULT_FPS_NUM = 24
DEFAULT_FPS_DEN = 1
MUX_WIDTH = 1920
MUX_HEIGHT = 1080
TIER_D_MAX_DURATION_SEC = 3.0

# Cost model constants (Step 1): estimated_gpu_ms must scale with num_frames
# or BudgetGovernor approves work it cannot afford. Values are order-of-
# magnitude estimates anchored to the previous flat defaults at ~1s/24fps.
_RIFE_MS_PER_FRAME = 8.0
_SPARSE_T2V_MS_PER_FRAME_TIER_C = 125.0
_SPARSE_T2V_MS_PER_FRAME_TIER_D = 210.0


def _num_frames(effective_duration_sec: float, fps_num: int, fps_den: int) -> int:
    return max(1, round(effective_duration_sec * fps_num / fps_den))


def build(
    shot_list: ShotList,
    budget: InferenceBudget | None = None,
    ai_enabled: bool = True,
    routing: RoutingPolicy | None = None,
    fps_num: int = DEFAULT_FPS_NUM,
    fps_den: int = DEFAULT_FPS_DEN,
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
    shots_manifest: list[dict] = []
    shot_output_tensors: list[str] = []

    for shot in shot_list.shots:
        effective_tier = _cap_tier(shot.tier, budget.max_tier)
        effective_tier = routing.effective_max_tier(effective_tier)
        tier_distribution[effective_tier.value] = tier_distribution.get(effective_tier.value, 0) + 1

        effective_duration_sec = shot.duration_sec
        if effective_tier == Tier.D:
            effective_duration_sec = min(shot.duration_sec, TIER_D_MAX_DURATION_SEC)

        num_frames = _num_frames(effective_duration_sec, fps_num, fps_den)
        terminal_tensor = _build_shot_subgraph(
            graph, shot, effective_tier,
            num_frames=num_frames, fps_num=fps_num, fps_den=fps_den,
        )
        shot_output_tensors.append(terminal_tensor)

        shots_manifest.append({
            "index": shot.index,
            "tier": effective_tier.value,
            "duration_sec": shot.duration_sec,
            "effective_duration_sec": effective_duration_sec,
            "fps": fps_num / fps_den,
            "num_frames": num_frames,
            "camera": shot.camera.motion.value,
            "camera_speed": shot.camera.speed,
            "output_tensor": terminal_tensor,
        })

    # Record the *effective* (post-cap) tier mix for job metrics (§12).
    graph.metadata["tier_distribution"] = tier_distribution

    graph.nodes.append(RfirNode(
        id="mux",
        op="ffmpeg_mux",
        inputs={f"frames_{i}": t for i, t in enumerate(shot_output_tensors)},
        attrs={
            "fps": fps_num / fps_den,
            "width": MUX_WIDTH,
            "height": MUX_HEIGHT,
            "shots": shots_manifest,
        },
    ))

    return graph


def _cap_tier(requested: Tier, max_tier: Tier) -> Tier:
    order = [Tier.A, Tier.B, Tier.C, Tier.D]
    max_idx = order.index(max_tier)
    req_idx = order.index(requested)
    if req_idx > max_idx:
        return max_tier
    return requested


def _build_shot_subgraph(
    graph: RfirGraph, shot: Shot, tier: Tier, *,
    num_frames: int, fps_num: int, fps_den: int,
) -> str:
    """Build the subgraph for one shot; return its terminal output tensor."""
    prefix = f"s{shot.index}"

    if tier == Tier.A:
        return _build_tier_a(graph, prefix, shot)
    elif tier == Tier.B:
        return _build_tier_b(graph, prefix, shot, num_frames=num_frames)
    elif tier == Tier.C:
        return _build_tier_c(graph, prefix, shot, num_frames=num_frames)
    elif tier == Tier.D:
        return _build_tier_d(graph, prefix, shot, num_frames=num_frames)
    raise CompileError(f"unknown tier: {tier!r}")


def _add_tensor(graph: RfirGraph, name: str, dtype: TensorDtype, lifetime: TensorLifetime = TensorLifetime.SHOT) -> str:
    graph.tensors[name] = TensorSpec(name=name, dtype=dtype, shape=[1, 3, 288, 512], lifetime=lifetime)
    return name


def _build_tier_a(graph: RfirGraph, prefix: str, shot: Shot) -> str:
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
    return out


def _build_tier_b(graph: RfirGraph, prefix: str, shot: Shot, *, num_frames: int) -> str:
    img_start = _add_tensor(graph, f"{prefix}_kf_start", TensorDtype.RGB_U8)
    img_end = _add_tensor(graph, f"{prefix}_kf_end", TensorDtype.RGB_U8)
    interp = _add_tensor(graph, f"{prefix}_interp", TensorDtype.RGB_U8)
    out = _add_tensor(graph, f"{prefix}_upscaled", TensorDtype.RGB_U8)

    # factor = num_frames - 1 so rife_interpolate.run() returns num_frames
    # frames total (Decision 3 / §6 Step 6).
    factor = max(1, num_frames - 1)
    rife_ms = max(1, num_frames) * _RIFE_MS_PER_FRAME

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
            attrs={"factor": factor, "num_frames": num_frames},
            estimated_gpu_ms=rife_ms, vram_mb=2048,
        ),
        RfirNode(
            id=f"{prefix}_upscale", op="vulkan_upscale",
            inputs={"image": interp}, outputs={"image_out": out},
        ),
    ])
    return out


def _build_tier_c(graph: RfirGraph, prefix: str, shot: Shot, *, num_frames: int) -> str:
    bg_img = _add_tensor(graph, f"{prefix}_bg", TensorDtype.RGB_U8)
    bg_depth = _add_tensor(graph, f"{prefix}_bg_depth", TensorDtype.DEPTH_F32)
    bg_frames = _add_tensor(graph, f"{prefix}_bg_parallax", TensorDtype.RGB_U8)
    mask = _add_tensor(graph, f"{prefix}_mask", TensorDtype.MASK_U8)
    latent_in = _add_tensor(graph, f"{prefix}_latent_in", TensorDtype.LATENT_F16)
    latent_out = _add_tensor(graph, f"{prefix}_latent_out", TensorDtype.LATENT_F16)
    fg_frames = _add_tensor(graph, f"{prefix}_fg", TensorDtype.RGB_U8)
    composite = _add_tensor(graph, f"{prefix}_composite", TensorDtype.RGB_U8)
    out = _add_tensor(graph, f"{prefix}_upscaled", TensorDtype.RGB_U8)

    t2v_ms = max(1, num_frames) * _SPARSE_T2V_MS_PER_FRAME_TIER_C

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
            attrs={"prompt": shot.description, "steps": 10, "window_size": 16, "overlap": 4,
                   "num_frames": num_frames},
            estimated_gpu_ms=t2v_ms, vram_mb=10240,
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
    return out


def _build_tier_d(graph: RfirGraph, prefix: str, shot: Shot, *, num_frames: int) -> str:
    img = _add_tensor(graph, f"{prefix}_keyframe", TensorDtype.RGB_U8)
    latent_in = _add_tensor(graph, f"{prefix}_latent_in", TensorDtype.LATENT_F16)
    latent_out = _add_tensor(graph, f"{prefix}_latent_out", TensorDtype.LATENT_F16)
    frames = _add_tensor(graph, f"{prefix}_frames", TensorDtype.RGB_U8)
    out = _add_tensor(graph, f"{prefix}_upscaled", TensorDtype.RGB_U8)
    dummy_mask = _add_tensor(graph, f"{prefix}_dummy_mask", TensorDtype.MASK_U8)

    t2v_ms = max(1, num_frames) * _SPARSE_T2V_MS_PER_FRAME_TIER_D

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
            inputs={"latent": latent_in, "mask": dummy_mask},
            outputs={"latent_out": latent_out},
            attrs={
                "prompt": shot.description, "steps": 10, "full_frame": True,
                "duration_sec": min(shot.duration_sec, TIER_D_MAX_DURATION_SEC),
                "num_frames": num_frames,
            },
            estimated_gpu_ms=t2v_ms, vram_mb=10240,
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
    return out
