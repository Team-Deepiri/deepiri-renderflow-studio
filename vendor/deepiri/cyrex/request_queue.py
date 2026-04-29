"""
Vendored from: deepiri-platform/diri-cyrex/app/core/request_queue_manager.py
Adapted for: Renderflow AI stage queueing and backpressure control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RequestPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class QueuedRequest:
    request_id: str
    payload: dict[str, Any]
    priority: RequestPriority = RequestPriority.NORMAL
    metadata: dict[str, Any] = field(default_factory=dict)


class RequestQueueManager:
    def __init__(self, max_parallel: int = 4):
        self.max_parallel = max_parallel
        self._pending: list[QueuedRequest] = []

    def enqueue(self, request: QueuedRequest) -> int:
        self._pending.append(request)
        return len(self._pending)

    def dequeue_batch(self, n: int) -> list[QueuedRequest]:
        take = min(n, len(self._pending))
        batch = self._pending[:take]
        self._pending = self._pending[take:]
        return batch

    def size(self) -> int:
        return len(self._pending)
