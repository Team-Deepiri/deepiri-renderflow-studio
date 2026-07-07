"""Memory + compute profiler for RFIR ops.

Samples process RAM (via psutil) and device VRAM (via torch CUDA/MPS APIs)
before and after each graph node. Designed to add minimal overhead — one
psutil call + one torch API call per node boundary, no sys.settrace.

Device quirks:
- CUDA: allocated + reserved both tracked; reset_peak_memory_stats() gives
  per-op peak VRAM.
- MPS: only current_allocated_memory() is available (no peak API, no reserved).
- CPU: VRAM is always 0; only RAM is tracked.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MemorySample:
    ram_mb: float = 0.0
    vram_mb: float = 0.0
    vram_reserved_mb: float = 0.0


def sample(device: str = "cpu") -> MemorySample:
    """Snapshot current process RAM and device VRAM."""
    ram_mb = _ram_mb()
    vram_mb = 0.0
    vram_reserved_mb = 0.0

    try:
        import torch
        if device == "cuda" and torch.cuda.is_available():
            vram_mb = torch.cuda.memory_allocated() / 1048576
            vram_reserved_mb = torch.cuda.memory_reserved() / 1048576
        elif device == "mps" and hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            vram_mb = torch.mps.current_allocated_memory() / 1048576
    except Exception:
        pass

    return MemorySample(ram_mb=ram_mb, vram_mb=vram_mb, vram_reserved_mb=vram_reserved_mb)


def peak_vram_mb(device: str = "cpu") -> float:
    """Return peak VRAM allocated since last reset_peak(), in MB. CUDA only."""
    try:
        import torch
        if device == "cuda" and torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / 1048576
    except Exception:
        pass
    return 0.0


def reset_peak(device: str = "cpu") -> None:
    """Reset CUDA peak stats so each op can report its own peak."""
    try:
        import torch
        if device == "cuda" and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass


def _ram_mb() -> float:
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 1048576
    except ImportError:
        return 0.0
