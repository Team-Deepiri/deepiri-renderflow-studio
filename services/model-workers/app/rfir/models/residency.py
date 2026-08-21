"""Role-residency math for RFIR disk working sets.

Capability is the catalog of roles. Disk is the resident subset. The compiler
already knows which roles a job needs before any GPU work, so fetch is a
covering problem, not a guess.

Do not compute weight-space residuals between different architectures
(FLUX DiT vs SDXL UNet vs CogVideoX). Those parameter vectors do not live
in the same space; LoRA/SVD of (θ_i − θ_j) is undefined.

Spec: docs/superpowers/specs/2026-08-21-rfir-role-residency-design.md
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.rfir.ir.types import RfirGraph

# Graph op name → catalog role. Vulkan / ffmpeg ops need no ML weights.
OP_TO_ROLE: dict[str, str] = {
    "plan_shots": "plan_shots",
    "t2i_keyframe": "t2i_keyframe",
    "depth_estimate": "depth_estimate",
    "rife_interpolate": "rife_interpolate",
    "segment_subject": "segment_subject",
    "sparse_t2v_window": "sparse_t2v",
    "vae_encode": "vae",
    "vae_decode": "vae",
    "nsfw_classify": "nsfw_classify",
}

# One canonical T2I on disk. The other is opt-in, never prepaid.
T2I_ROLE = "t2i_keyframe"
DEFAULT_T2I_MODEL_ID = "flux-schnell-fp16"
FALLBACK_T2I_MODEL_ID = "sdxl-turbo-fp16"

# README fp16 sizes (bytes). Used for working-set predictions, not billing.
ROLE_BYTES_FP16: dict[str, int] = {
    "t2i_keyframe": 12 * 10**9,       # FLUX.1-schnell fp16
    "t2i_keyframe_fallback": 6 * 10**9,  # SDXL-Turbo; must not be added by default
    "sparse_t2v": 10 * 10**9,         # CogVideoX-2B fp16
    "plan_shots": 2 * 10**9,          # Qwen2.5-3B Q4_K_M GGUF
    "depth_estimate": 200 * 10**6,
    "segment_subject": 150 * 10**6,
    "rife_interpolate": 100 * 10**6,
    "nsfw_classify": 330 * 10**6,
    "vae": 0,  # counted inside sparse_t2v checkpoint when shared
}

# Always-on pin set: small, used on almost every job, cheap to keep.
PIN_ROLES: frozenset[str] = frozenset(
    {"plan_shots", "depth_estimate", "rife_interpolate", "nsfw_classify"}
)

# CFSV design mix (rfir-inference-engine-design.md §4). p = P(role in a job).
CFSV_ROLE_PROBABILITY: dict[str, float] = {
    "plan_shots": 1.0,
    "t2i_keyframe": 1.0,
    "depth_estimate": 0.70,   # Tier A share
    "rife_interpolate": 0.20,  # Tier B share
    "segment_subject": 0.08,   # Tier C
    "sparse_t2v": 0.10,        # Tier C + D
    "vae": 0.10,
    "nsfw_classify": 1.0,
}


@dataclass(frozen=True)
class FetchItem:
    role: str
    bytes: int
    in_current_job: bool


@dataclass
class WorkingSet:
    """Resident roles plus predicted disk."""

    hot: frozenset[str]
    expected_bytes: int
    pin: frozenset[str] = field(default_factory=lambda: PIN_ROLES)


def required_roles(graph: RfirGraph) -> frozenset[str]:
    """Roles the compiled graph will invoke. Known before fetch."""
    roles: set[str] = set()
    for node in graph.nodes:
        role = OP_TO_ROLE.get(node.op)
        if role:
            roles.add(role)
    return frozenset(roles)


def resident_probability(p_role: float, window: int) -> float:
    """P(role is hot) under independent jobs and an LRU of the last `window` jobs.

    P(missed every job in the window) = (1 − p)^W
    P(hot) = 1 − (1 − p)^W

    window → ∞ recovers today's prepaid catalog (everything always resident).
    window = 1 is "keep only what the current job needs" plus pins.
    """
    if window < 0:
        raise ValueError(f"window must be >= 0, got {window}")
    if not 0.0 <= p_role <= 1.0:
        raise ValueError(f"p_role must be in [0, 1], got {p_role}")
    if window == 0:
        return 0.0
    return 1.0 - (1.0 - p_role) ** window


def expected_disk_bytes(
    sizes: dict[str, int],
    probabilities: dict[str, float],
    window: int,
    pin: frozenset[str] = PIN_ROLES,
    include_t2i_fallback: bool = False,
) -> int:
    """E[disk] = Σ_r s_r · P(r resident).

    Pin roles contribute their full size. Dual T2I (FLUX + SDXL) is excluded
    unless include_t2i_fallback is True — that dual-ship is the 6 GB waste
    in scripts/download_rfir_models.py today.
    """
    total = 0
    for role, size in sizes.items():
        if role == "t2i_keyframe_fallback" and not include_t2i_fallback:
            continue
        if role in pin:
            total += size
            continue
        p = probabilities.get(role, 0.0)
        total += int(round(size * resident_probability(p, window)))
    return total


def miss_bytes(demand: frozenset[str], hot: frozenset[str], sizes: dict[str, int]) -> int:
    """Bytes that must be fetched before this job can run."""
    missing = demand - hot
    return sum(sizes.get(role, 0) for role in missing)


def compression_ratio(expected_bytes: int, catalog_bytes: int) -> float:
    """ρ = E[disk] / catalog. 1.0 is today's prepaid pile. Lower is better."""
    if catalog_bytes <= 0:
        raise ValueError("catalog_bytes must be positive")
    return expected_bytes / catalog_bytes


def catalog_bytes_fp16(include_t2i_fallback: bool = True) -> int:
    """Prepaid catalog size matching the current download script."""
    return expected_disk_bytes(
        ROLE_BYTES_FP16,
        {role: 1.0 for role in ROLE_BYTES_FP16},
        window=10**9,
        pin=frozenset(ROLE_BYTES_FP16),
        include_t2i_fallback=include_t2i_fallback,
    )


def fetch_priority(missing: list[FetchItem]) -> list[FetchItem]:
    """Demand-priority pop: current-job misses first, then largest first.

    This is RFIR's popcorn queue, applied to *roles on disk*, not denoising
    timesteps. A popcorn queue is a to-do list that pops the most urgent item,
    with optional weighted-random exploration for work that is *not* blocking
    the current job:

      Priority(role) = I(in current graph) * size + residual_miss_pressure
      P(pop r) ∝ exp(Priority(r) / T)   # T→0 is greedy; T>0 explores prefetch

    After a fetch, if the dir is still incomplete you re-push it with higher
    pressure (the counter-loop). Kernels that are already "cooked" (dir present
    and non-empty) leave the queue.

    Do not permute diffusion timesteps this way. The probability-flow ODE is
    dx/dt = f(x, t): time-inhomogeneous, so order is the integral, not a
    suggestion. Adaptive *step size* (DPM-Solver++) is legitimate; random
    *step order* is not. Popcorn lives here, in fetch_priority.
    """
    return sorted(
        missing,
        key=lambda item: (not item.in_current_job, -item.bytes, item.role),
    )


def refuse_cross_architecture_residual(left_arch: str, right_arch: str) -> None:
    """θ_i − θ_j is undefined when architectures differ.

    SVDQuant (Li et al., ICLR 2025) SVDs *within* one weight matrix of one
    model. CollectionLoRA / MT-DMD distill LoRAs of the *same* base. Neither
    licenses subtracting FLUX parameters from SDXL or CogVideoX.
    """
    if left_arch != right_arch:
        raise TypeError(
            f"cross-architecture residual is undefined: {left_arch!r} vs {right_arch!r}"
        )
