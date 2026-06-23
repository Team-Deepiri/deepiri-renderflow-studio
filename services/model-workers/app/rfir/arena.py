"""Tensor arena — manages intermediate tensors during graph execution.

Basic slab storage for images, depth maps, and other artifacts produced
by ops during a job. Tensors are keyed by name (matching graph tensor names).

Spec reference: rfir-inference-engine-implementation.md §1.7
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TensorArena:
    """In-memory store for intermediate tensors during graph execution."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def put(self, name: str, value: Any) -> None:
        self._store[name] = value

    def get(self, name: str) -> Any:
        if name not in self._store:
            raise KeyError(f"Tensor {name!r} not in arena")
        return self._store[name]

    def has(self, name: str) -> bool:
        return name in self._store

    def release(self, name: str) -> None:
        self._store.pop(name, None)

    def release_all(self) -> None:
        self._store.clear()

    def keys(self) -> list[str]:
        return list(self._store.keys())

    def __len__(self) -> int:
        return len(self._store)
