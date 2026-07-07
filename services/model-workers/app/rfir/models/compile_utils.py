"""torch.compile helpers — bucketed-shape compilation cache for hot ops (§5.1).

CUDA: torch.compile is mature and reliably speeds up repeated-shape inference.
MPS: torch.compile support is experimental (PyTorch 2.x); we attempt it but
     fall back to eager mode on any compile failure so MPS dev machines never
     break, they just don't get the speedup.
CPU: compilation skipped — not worth the warmup cost for dev/test runs.

Spec reference: rfir-inference-engine-implementation.md §5.1
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

_compiled_cache: dict[tuple, Any] = {}

_ENV_DISABLE = "RENDERFLOW_RFIR_DISABLE_COMPILE"


def is_compile_enabled(device: str) -> bool:
    """torch.compile is attempted on CUDA only; MPS produces silent wrong output with it."""
    if os.environ.get(_ENV_DISABLE, "").lower() in ("1", "true", "yes"):
        return False
    return device == "cuda"


def compiled_call(
    fn: Callable,
    *,
    cache_key: tuple,
    device: str,
    mode: str = "reduce-overhead",
) -> Callable:
    """Return a torch.compile'd version of `fn`, cached by `cache_key`.

    `cache_key` should bucket on (op_name, device, shape, steps, ...) so the
    same compiled graph is reused across calls with identical shapes — the
    whole point of bucketing per the design doc. New shapes trigger a fresh
    (cached) compile rather than recompiling every call.

    Falls back to the uncompiled `fn` if torch.compile is unavailable, disabled,
    or fails for this device (common on MPS with certain ops).
    """
    if not is_compile_enabled(device):
        return fn

    full_key = (device, mode, *cache_key)
    if full_key in _compiled_cache:
        return _compiled_cache[full_key]

    try:
        import torch

        compiled = torch.compile(fn, mode=mode, dynamic=False)
        _compiled_cache[full_key] = compiled
        logger.info("torch.compile: compiled %s (key=%s)", getattr(fn, "__name__", fn), cache_key)
        return compiled
    except Exception as e:
        logger.warning("torch.compile unavailable for key=%s on %s (%s) — using eager mode",
                        cache_key, device, e)
        _compiled_cache[full_key] = fn  # cache the fallback too, avoid retrying every call
        return fn


def clear_compile_cache() -> None:
    """Drop all cached compiled callables (e.g. between jobs with different shapes)."""
    _compiled_cache.clear()
