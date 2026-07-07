"""Precision policy — resolve dtype and quantization per device.

CUDA: can use INT4 (autoawq) or fp16
MPS: fp16 only (no autoawq/bitsandbytes support)
CPU: fp32

Spec reference: rfir-inference-engine-implementation.md §1.3
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PrecisionConfig:
    torch_dtype: str  # "float16" | "float32" | "bfloat16"
    quantization: str | None  # "awq_int4" | "nf4" | None
    device_map: str | None  # "auto" | None


def resolve(device: str, vram_mb: int = 0, prefer_quantized: bool = True) -> PrecisionConfig:
    """Pick the best precision for the given device and available VRAM."""
    if device == "cuda":
        if prefer_quantized and vram_mb <= 8192:
            try:
                import autoawq  # noqa: F401
                logger.info("Using AWQ INT4 quantization (CUDA, %d MB VRAM)", vram_mb)
                return PrecisionConfig(
                    torch_dtype="float16",
                    quantization="awq_int4",
                    device_map="auto",
                )
            except ImportError:
                logger.info("autoawq not available, using fp16")

        return PrecisionConfig(
            torch_dtype="float16",
            quantization=None,
            device_map="auto",
        )

    if device == "mps":
        # fp16 halves memory and is ~1.5x faster than fp32 on MPS. Older
        # torch builds produced garbage SDXL output in fp16 on Apple Silicon;
        # torch >= 2.4 is reliable. Set RENDERFLOW_RFIR_MPS_FP32=1 to fall
        # back if a host still shows black/noise frames.
        if os.environ.get("RENDERFLOW_RFIR_MPS_FP32", "0") == "1":
            return PrecisionConfig(
                torch_dtype="float32",
                quantization=None,
                device_map=None,
            )
        return PrecisionConfig(
            torch_dtype="float16",
            quantization=None,
            device_map=None,
        )

    # CPU fallback
    return PrecisionConfig(
        torch_dtype="float32",
        quantization=None,
        device_map=None,
    )
