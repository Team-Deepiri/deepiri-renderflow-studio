"""RFIR Budget Governor — keep a job within its GPU-second budget (§2.7).

Spec reference: rfir-inference-engine-implementation.md §2.7
"""
from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass

from app.rfir.ir.types import InferenceBudget, RfirNode


@dataclass
class DowngradeRecord:
    node_id: str
    op: str
    trigger: str  # "gpu_time" | "vram" | "gpu_time+vram" — why it was downgraded
    reason: str   # "downgraded_to_fit" | "over_budget" — GPU-time fit outcome
    before_ms: float
    after_ms: float


def _downgrade_t2i(node: RfirNode) -> None:
    node.attrs["steps"] = max(1, int(node.attrs.get("steps", 4)) // 2)
    node.estimated_gpu_ms *= 0.5 # assume time halves with halve steps


def _downgrade_rife(node: RfirNode) -> None:
    node.attrs["factor"] = max(2, int(node.attrs.get("factor", 4)) // 2)
    node.estimated_gpu_ms *= 0.7


_DEPTH_MIN_SCALE = 0.5
def _downgrade_depth(node: RfirNode) -> None:
    scale = float(node.attrs.get("infer_scale", 1.0))
    if scale <= _DEPTH_MIN_SCALE:
        return  # at floor; no real lever left → loop records over_budget honestly
    new_scale = max(_DEPTH_MIN_SCALE, scale * 0.5)
    node.attrs["infer_scale"] = new_scale
    node.estimated_gpu_ms *= (new_scale / scale) ** 2  # compute ~ pixel area


_TEMPLATES = {
    "t2i_keyframe": _downgrade_t2i,
    "rife_interpolate": _downgrade_rife,
    "depth_estimate": _downgrade_depth,
}

_MAX_DOWNGRADE_STEPS = 4  # bound the loop so we never spin forever


class BudgetGovernor:
    """Tracks GPU-second spend and downgrades nodes that don't fit."""

    def __init__(self, budget: InferenceBudget, vram_hints: Iterable[str] | None = None) -> None:
        self.budget = budget
        # Node ids the memory planner (§2.2) flagged as VRAM-heavy.
        self.vram_hints: set[str] = set(vram_hints or ())
        self.downgrades: list[DowngradeRecord] = []

    def set_vram_hints(self, hints: Iterable[str]) -> None:
        """Set the VRAM downgrade hints (e.g. from MemoryPlan.downgrade_hints)."""
        self.vram_hints = set(hints)

    def before_node(self, node: RfirNode) -> RfirNode:
        """Return a node (copy) that fits time + VRAM budgets (downgraded if needed)."""
        est_s = node.estimated_gpu_ms / 1000.0
        over_time = not self.budget.can_afford(est_s)
        over_vram = node.id in self.vram_hints
        if not over_time and not over_vram:
            return node

        triggers = []
        if over_time:
            triggers.append("gpu_time")
        if over_vram:
            triggers.append("vram")
        trigger = "+".join(triggers)

        template = _TEMPLATES.get(node.op)
        if template is None:
            self.downgrades.append(DowngradeRecord(
                node_id=node.id, op=node.op, trigger=trigger, reason="over_budget",
                before_ms=node.estimated_gpu_ms, after_ms=node.estimated_gpu_ms,
            ))
            return node

        candidate = copy.deepcopy(node)
        before_ms = node.estimated_gpu_ms

        for _ in range(_MAX_DOWNGRADE_STEPS):
            template(candidate)
            if self.budget.can_afford(candidate.estimated_gpu_ms / 1000.0):
                break

        fits_time = self.budget.can_afford(candidate.estimated_gpu_ms / 1000.0)
        self.downgrades.append(DowngradeRecord(
            node_id=node.id,
            op=node.op,
            trigger=trigger,
            reason="downgraded_to_fit" if fits_time else "over_budget",
            before_ms=before_ms,
            after_ms=candidate.estimated_gpu_ms,
        ))
        return candidate

    def after_node(self, actual_gpu_seconds: float) -> None:
        """Record actual spend after a node executes."""
        self.budget.spend(actual_gpu_seconds)

    def metrics(self) -> dict:
        return {
            "max_gpu_seconds": self.budget.max_gpu_seconds,
            "spent_gpu_seconds": self.budget.spent_gpu_seconds,
            "remaining_gpu_seconds": self.budget.remaining_gpu_seconds,
            "downgrade_count": len(self.downgrades),
            "downgrades": [
                {"node_id": d.node_id, "op": d.op, "trigger": d.trigger, "reason": d.reason,
                 "before_ms": d.before_ms, "after_ms": d.after_ms}
                for d in self.downgrades
            ],
        }
