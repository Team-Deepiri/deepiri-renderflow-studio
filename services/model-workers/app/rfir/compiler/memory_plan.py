"""RFIR Compiler — Memory planning pass: liveness analysis + peak VRAM (§2.2).

Walks the scheduled execution order and estimates peak VRAM as:

    per_step_vram = sum(size of tensors live at this step)
                    + working VRAM of the node running at this step

Note: tensor shapes in the IR are config-nominal (e.g. [1,3,288,512]); the
estimate is intended for relative planning, not exact runtime accounting.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.rfir.compiler.scheduler import topological_sort
from app.rfir.ir.types import RfirGraph

_BYTES_PER_MB = 1024 * 1024
# 8 GB consumer GPU with headroom for driver/runtime.
DEFAULT_VRAM_LIMIT_MB = 7500.0

@dataclass
class MemoryPlan:
    peak_vram_mb: float
    peak_step: int
    per_step_mb: list[float] = field(default_factory=list)
    downgrade_hints: list[str] = field(default_factory=list)
    over_budget: bool = False

def _tensor_mb(graph: RfirGraph, tensor_name: str) -> float:
    spec = graph.tensors.get(tensor_name)
    return (spec.nbytes() / _BYTES_PER_MB) if spec else 0.0

def plan(
    graph: RfirGraph,
    order: list[str] | None = None,
    vram_limit_mb: float = DEFAULT_VRAM_LIMIT_MB,
) -> MemoryPlan:
    """Estimate peak VRAM over the schedule and emit downgrade hints if over budget."""
    if order is None:
        order = topological_sort(graph)
    if not order:
        return MemoryPlan(peak_vram_mb=0.0, peak_step=0)

    step_of = {nid: i for i, nid in enumerate(order)}
    node_at = {step_of[n.id]: n for n in graph.nodes if n.id in step_of}

    # Liveness: producer step and last-use step per tensor.
    produced_at: dict[str, int] = {}
    last_use: dict[str, int] = {}
    for node in graph.nodes:
        if node.id not in step_of:
            continue
        s = step_of[node.id]
        for tensor in node.outputs.values():
            produced_at[tensor] = s
            last_use[tensor] = max(last_use.get(tensor, s), s)
    for node in graph.nodes:
        if node.id not in step_of:
            continue
        s = step_of[node.id]
        for tensor in node.inputs.values():
            if tensor in produced_at:
                last_use[tensor] = max(last_use.get(tensor, s), s)

    n_steps = len(order)
    per_step: list[float] = [0.0] * n_steps
    for step in range(n_steps):
        live_mb = 0.0
        for tensor, p in produced_at.items():
            if p <= step <= last_use.get(tensor, p):
                live_mb += _tensor_mb(graph, tensor)
        node = node_at.get(step)
        working_mb = node.vram_mb if node else 0.0
        per_step[step] = live_mb + working_mb

    peak_vram_mb = max(per_step)
    peak_step = per_step.index(peak_vram_mb)
    over_budget = peak_vram_mb > vram_limit_mb

    downgrade_hints: list[str] = []
    if over_budget:
        over_steps = {i for i, v in enumerate(per_step) if v > vram_limit_mb}
        candidates = [
            node_at[i] for i in sorted(over_steps)
            if i in node_at and node_at[i].vram_mb > 0
        ]
        candidates.sort(key=lambda nd: nd.vram_mb, reverse=True)
        seen: set[str] = set()
        for nd in candidates:
            if nd.id not in seen:
                seen.add(nd.id)
                downgrade_hints.append(nd.id)

    return MemoryPlan(
        peak_vram_mb=peak_vram_mb,
        peak_step=peak_step,
        per_step_mb=per_step,
        downgrade_hints=downgrade_hints,
        over_budget=over_budget,
    )
