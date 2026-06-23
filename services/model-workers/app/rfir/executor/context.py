"""Executor context — tracks job state, metrics, and timing during execution."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeMetric:
    node_id: str
    op: str
    gpu_ms: float = 0.0
    wall_ms: float = 0.0


@dataclass
class ExecutionContext:
    job_id: str
    device: str = "cpu"
    start_time: float = field(default_factory=time.monotonic)
    node_metrics: list[NodeMetric] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def total_gpu_ms(self) -> float:
        return sum(m.gpu_ms for m in self.node_metrics)

    def record_node(self, node_id: str, op: str, wall_ms: float, gpu_ms: float = 0.0) -> None:
        self.node_metrics.append(NodeMetric(node_id=node_id, op=op, gpu_ms=gpu_ms, wall_ms=wall_ms))

    def to_metrics_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "device": self.device,
            "total_wall_seconds": self.elapsed_seconds,
            "total_gpu_ms": self.total_gpu_ms,
            "nodes": [
                {"id": m.node_id, "op": m.op, "gpu_ms": m.gpu_ms, "wall_ms": m.wall_ms}
                for m in self.node_metrics
            ],
            "artifacts": self.artifacts,
        }
