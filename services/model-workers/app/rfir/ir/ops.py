"""RFIR op catalog — every operation the graph can reference.

Each op declares its required input/output port names and their tensor dtypes.
The validator uses this to verify port wiring.

Spec reference: rfir-inference-engine-design.md §3.2 (Op Catalog)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.rfir.ir.types import TensorDtype


class OpDevice(str, Enum):
    CPU = "cpu"
    CUDA = "cuda"
    VULKAN = "vulkan"


@dataclass(frozen=True)
class PortSpec:
    name: str
    dtype: TensorDtype


@dataclass(frozen=True)
class OpDef:
    name: str
    device: OpDevice
    inputs: tuple[PortSpec, ...] = ()
    outputs: tuple[PortSpec, ...] = ()


OP_REGISTRY: dict[str, OpDef] = {}


def _register(*ops: OpDef) -> None:
    for op in ops:
        OP_REGISTRY[op.name] = op


# CPU ops
_register(
    OpDef(
        name="plan_shots",
        device=OpDevice.CPU,
        inputs=(),
        outputs=(PortSpec("shot_list", TensorDtype.RGB_U8),),
    ),
)

# CUDA ops
_register(
    OpDef(
        name="t2i_keyframe",
        device=OpDevice.CUDA,
        inputs=(),
        outputs=(PortSpec("image", TensorDtype.RGB_U8),),
    ),
    OpDef(
        name="depth_estimate",
        device=OpDevice.CUDA,
        inputs=(PortSpec("image", TensorDtype.RGB_U8),),
        outputs=(PortSpec("depth", TensorDtype.DEPTH_F32),),
    ),
    OpDef(
        name="segment_subject",
        device=OpDevice.CUDA,
        inputs=(PortSpec("image", TensorDtype.RGB_U8),),
        outputs=(PortSpec("mask", TensorDtype.MASK_U8),),
    ),
    OpDef(
        name="vae_encode",
        device=OpDevice.CUDA,
        inputs=(PortSpec("image", TensorDtype.RGB_U8),),
        outputs=(PortSpec("latent", TensorDtype.LATENT_F16),),
    ),
    OpDef(
        name="vae_decode",
        device=OpDevice.CUDA,
        inputs=(PortSpec("latent", TensorDtype.LATENT_F16),),
        outputs=(PortSpec("image", TensorDtype.RGB_U8),),
    ),
    OpDef(
        name="sparse_t2v_window",
        device=OpDevice.CUDA,
        inputs=(
            PortSpec("latent", TensorDtype.LATENT_F16),
            PortSpec("mask", TensorDtype.MASK_U8),
        ),
        outputs=(PortSpec("latent_out", TensorDtype.LATENT_F16),),
    ),
    OpDef(
        name="rife_interpolate",
        device=OpDevice.CUDA,
        inputs=(
            PortSpec("frame_start", TensorDtype.RGB_U8),
            PortSpec("frame_end", TensorDtype.RGB_U8),
        ),
        outputs=(PortSpec("frames", TensorDtype.RGB_U8),),
    ),
)

# Vulkan ops
_register(
    OpDef(
        name="vulkan_parallax",
        device=OpDevice.VULKAN,
        inputs=(
            PortSpec("image", TensorDtype.RGB_U8),
            PortSpec("depth", TensorDtype.DEPTH_F32),
        ),
        outputs=(PortSpec("frames", TensorDtype.RGB_U8),),
    ),
    OpDef(
        name="vulkan_upscale",
        device=OpDevice.VULKAN,
        inputs=(PortSpec("image", TensorDtype.RGB_U8),),
        outputs=(PortSpec("image_out", TensorDtype.RGB_U8),),
    ),
    OpDef(
        name="vulkan_composite",
        device=OpDevice.VULKAN,
        inputs=(
            PortSpec("foreground", TensorDtype.RGB_U8),
            PortSpec("background", TensorDtype.RGB_U8),
            PortSpec("mask", TensorDtype.MASK_U8),
        ),
        outputs=(PortSpec("image", TensorDtype.RGB_U8),),
    ),
    OpDef(
        name="vulkan_motion_blur",
        device=OpDevice.VULKAN,
        inputs=(PortSpec("frames", TensorDtype.RGB_U8),),
        outputs=(PortSpec("frames_out", TensorDtype.RGB_U8),),
    ),
)

# CPU post-processing
_register(
    OpDef(
        name="ffmpeg_mux",
        device=OpDevice.CPU,
        inputs=(PortSpec("frames", TensorDtype.RGB_U8),),
        outputs=(),
    ),
)
