"""Executor context — tracks job state, metrics, and timing during execution."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Escalation is log-only today (§9 — the executor cannot re-run a shot at a
# different tier), so this default is unvalidated: §7c found it escalates
# 10/10 measured Tier B shots. Calibrating it needs labeled shots, not a
# percentile off the observed distribution — see docs/specs/
# rfir-mp4-output-pipeline.md §7a. Left unset until that calibration exists.
_DEFAULT_SSIM_THRESHOLD = 0.85

@dataclass
class NodeMetric:
    node_id: str
    op: str
    gpu_ms: float = 0.0
    wall_ms: float = 0.0


@dataclass
class EscalationDecision:
    escalate: bool
    reason: str
    ssim: float


def decide_escalation(
    ssim_score: float,
    *,
    threshold: float | None = None,
    escalations_remaining: int = 0,
) -> EscalationDecision:
    """Decide whether a Tier B segment should escalate to Tier C.

    threshold defaults to RENDERFLOW_RFIR_SSIM_THRESHOLD (Step 6's config
    var) rather than a hardcoded default argument, so calibration has
    somewhere to plug in. Falls back to _DEFAULT_SSIM_THRESHOLD when unset.
    """
    if threshold is None:
        threshold = float(os.environ.get("RENDERFLOW_RFIR_SSIM_THRESHOLD", _DEFAULT_SSIM_THRESHOLD))
    if ssim_score >= threshold:
        return EscalationDecision(False, "quality_ok", ssim_score)
    if escalations_remaining <= 0:
        return EscalationDecision(False, "no_escalations_left", ssim_score)
    return EscalationDecision(True, "low_ssim", ssim_score)


@dataclass
class ExecutionContext:
    job_id: str
    device: str = "cpu"
    nsfw_mode: str = "block"
    keyframe_check: Callable[..., Any] | None = None
    start_time: float = field(default_factory=time.monotonic)
    node_metrics: list[NodeMetric] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    escalations: list[dict[str, Any]] = field(default_factory=list)
    tier_distribution: dict[str, int] = field(default_factory=dict)
    downgrades: list[dict[str, Any]] = field(default_factory=list)

    def record_escalation(self, node_id: str, decision: EscalationDecision) -> None:
        """Record a Tier B SSIM gate outcome for the review UI / metrics."""
        self.escalations.append({
            "node_id": node_id,
            "escalate": decision.escalate,
            "reason": decision.reason,
            "ssim": decision.ssim,
        })

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def total_gpu_ms(self) -> float:
        return sum(m.gpu_ms for m in self.node_metrics)

    def record_node(self, node_id: str, op: str, wall_ms: float, gpu_ms: float = 0.0) -> None:
        self.node_metrics.append(NodeMetric(node_id=node_id, op=op, gpu_ms=gpu_ms, wall_ms=wall_ms))

    def cost_estimate_usd(self, rate_per_gpu_second: float = 0.0001) -> float:
        """Estimate job cost: total GPU seconds * rate card (§4.7)."""
        return (self.total_gpu_ms / 1000.0) * rate_per_gpu_second

    def to_metrics_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "device": self.device,
            "total_wall_seconds": self.elapsed_seconds,
            "total_gpu_ms": self.total_gpu_ms,
            "cost_estimate_usd": self.cost_estimate_usd(),
            "nodes": [
                {"id": m.node_id, "op": m.op, "gpu_ms": m.gpu_ms, "wall_ms": m.wall_ms}
                for m in self.node_metrics
            ],
            "artifacts": self.artifacts,
            "escalations": self.escalations,
            "tier_distribution": self.tier_distribution,
            "downgrades": self.downgrades,
        }
