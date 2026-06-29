"""RFIR core data types — static graph IR compiled once per job.

Spec reference: rfir-inference-engine-design.md §3 (Graph IR)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Tensor descriptors
# ---------------------------------------------------------------------------

class TensorDtype(str, Enum):
    LATENT_F16 = "latent_f16"
    RGB_U8 = "rgb_u8"
    DEPTH_F32 = "depth_f32"
    FLOW_F32 = "flow_f32"
    MASK_U8 = "mask_u8"


class TensorLifetime(str, Enum):
    SHOT = "shot"
    JOB = "job"
    SCRATCH = "scratch"


class TensorDevice(str, Enum):
    CUDA_0 = "cuda:0"
    CPU = "cpu"
    VULKAN = "vulkan"


@dataclass
class TensorSpec:
    name: str
    dtype: TensorDtype
    shape: list[int]
    lifetime: TensorLifetime = TensorLifetime.SCRATCH
    device: TensorDevice = TensorDevice.CUDA_0

    def nbytes(self) -> int:
        elements = 1
        for dim in self.shape:
            elements *= dim
        bytes_per = {
            TensorDtype.LATENT_F16: 2,
            TensorDtype.RGB_U8: 1,
            TensorDtype.DEPTH_F32: 4,
            TensorDtype.FLOW_F32: 4,
            TensorDtype.MASK_U8: 1,
        }
        return elements * bytes_per[self.dtype]


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

@dataclass
class RfirNode:
    id: str
    op: str
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    attrs: dict[str, Any] = field(default_factory=dict)
    estimated_gpu_ms: float = 0.0
    vram_mb: float = 0.0


@dataclass
class RfirGraph:
    nodes: list[RfirNode] = field(default_factory=list)
    tensors: dict[str, TensorSpec] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def node_ids(self) -> list[str]:
        return [n.id for n in self.nodes]

    def get_node(self, node_id: str) -> RfirNode | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None


# ---------------------------------------------------------------------------
# Shot planning types (output of plan_shots op)
# ---------------------------------------------------------------------------

class Tier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class CameraMotion(str, Enum):
    STATIC = "static"
    PAN = "pan"
    DOLLY = "dolly"
    ORBIT = "orbit"
    ZOOM = "zoom"
    TRACKING = "tracking"


@dataclass
class CameraPath:
    motion: CameraMotion = CameraMotion.STATIC
    speed: float = 1.0
    direction: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Shot:
    index: int
    description: str
    tier: Tier = Tier.A
    duration_sec: float = 5.0
    camera: CameraPath = field(default_factory=CameraPath)
    subject: str = ""
    style: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShotList:
    shots: list[Shot] = field(default_factory=list)
    prompt: str = ""
    style_guidance: str = ""

    def total_duration_sec(self) -> float:
        return sum(s.duration_sec for s in self.shots)

    def tier_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for s in self.shots:
            dist[s.tier.value] = dist.get(s.tier.value, 0) + 1
        return dist


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@dataclass
class InferenceBudget:
    max_gpu_seconds: float = 120.0
    max_tier: Tier = Tier.C
    spent_gpu_seconds: float = 0.0
    escalations_allowed: int = 2

    @property
    def remaining_gpu_seconds(self) -> float:
        return max(0.0, self.max_gpu_seconds - self.spent_gpu_seconds)

    def can_afford(self, estimated_seconds: float) -> bool:
        return self.spent_gpu_seconds + estimated_seconds <= self.max_gpu_seconds

    def spend(self, seconds: float) -> None:
        self.spent_gpu_seconds += seconds


# ---------------------------------------------------------------------------
# Routing policy
# ---------------------------------------------------------------------------

@dataclass
class RoutingPolicy:
    """Controls where inference work runs (§10 hybrid routing)."""
    local_only: bool = False
    cloud_allowed: bool = True

    def effective_max_tier(self, requested: Tier) -> Tier:
        """Cap tier based on routing policy. local_only caps at B."""
        if self.local_only:
            order = [Tier.A, Tier.B, Tier.C, Tier.D]
            max_local = Tier.B
            req_idx = order.index(requested)
            cap_idx = order.index(max_local)
            if req_idx > cap_idx:
                return max_local
        return requested
