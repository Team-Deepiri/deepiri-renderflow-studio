"""CUDA graph capture for steady-state Tier A batches (§5.2).

CUDA graphs record a fixed sequence of GPU kernels once, then replay them
with near-zero CPU launch overhead — a meaningful win for Tier A's repeated
t2i_keyframe + depth_estimate pattern across many shots of the same shape.

This is a CUDA-only PyTorch API (`torch.cuda.graph`); there is no MPS or CPU
equivalent. On non-CUDA devices, `capture()` returns a sentinel that callers
treat as "not captured" and they fall through to eager execution — this is
the documented, intentional behavior for local (MPS) development machines.
Real benchmarking of this path requires CUDA hardware (deferred per the
Phase 5 task list).

Spec reference: rfir-inference-engine-implementation.md §5.2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

_graph_cache: dict[tuple, "CapturedGraph"] = {}


@dataclass
class CapturedGraph:
    """A captured CUDA graph plus its static input/output tensors."""
    graph: Any
    static_inputs: dict[str, Any]
    static_output: Any

    def replay(self, **inputs) -> Any:
        """Copy fresh inputs into the static buffers and replay the graph."""
        import torch

        for name, tensor in inputs.items():
            self.static_inputs[name].copy_(tensor)
        self.graph.replay()
        return self.static_output


def is_available(device: str) -> bool:
    """CUDA graphs only exist on CUDA; MPS/CPU always report unavailable."""
    if device != "cuda":
        return False
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def capture_or_get(
    cache_key: tuple,
    device: str,
    fn: Callable,
    example_inputs: dict[str, Any],
    warmup_iters: int = 3,
) -> CapturedGraph | None:
    """Capture (or fetch a cached) CUDA graph for `fn` with the given example inputs.

    Returns None on non-CUDA devices or if capture fails — callers must check
    for None and fall back to calling `fn` directly (eager mode).
    """
    if not is_available(device):
        logger.debug("CUDA graph capture skipped on device=%s (CUDA-only feature)", device)
        return None

    if cache_key in _graph_cache:
        return _graph_cache[cache_key]

    try:
        import torch

        # Warm up on a side stream so capture doesn't record one-time alloc/JIT work.
        side_stream = torch.cuda.Stream()
        side_stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(side_stream):
            for _ in range(warmup_iters):
                fn(**example_inputs)
        torch.cuda.current_stream().wait_stream(side_stream)

        static_inputs = {k: v.clone() for k, v in example_inputs.items()}
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            static_output = fn(**static_inputs)

        captured = CapturedGraph(graph=graph, static_inputs=static_inputs, static_output=static_output)
        _graph_cache[cache_key] = captured
        logger.info("CUDA graph captured for key=%s", cache_key)
        return captured
    except Exception as e:
        logger.warning("CUDA graph capture failed for key=%s (%s) — falling back to eager", cache_key, e)
        return None


def clear_graph_cache() -> None:
    _graph_cache.clear()
