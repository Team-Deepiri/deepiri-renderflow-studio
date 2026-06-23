"""RFIR graph validation — structural checks before execution.

Checks:
  1. No unknown ops (every node.op must be in OP_REGISTRY)
  2. No duplicate node IDs
  3. All input tensors exist (referenced tensor names must be in graph.tensors or produced by another node)
  4. Port dtype compatibility (input tensor dtype matches op's expected port dtype)
  5. Acyclicity (no cycles in the dependency graph)

Spec reference: rfir-inference-engine-implementation.md §0.3
"""
from __future__ import annotations

from dataclasses import dataclass

from app.rfir.ir.ops import OP_REGISTRY
from app.rfir.ir.types import RfirGraph


@dataclass
class ValidationError:
    node_id: str
    message: str


def validate(graph: RfirGraph) -> list[ValidationError]:
    """Validate an RfirGraph. Returns empty list if valid."""
    errors: list[ValidationError] = []
    errors.extend(_check_unknown_ops(graph))
    errors.extend(_check_duplicate_ids(graph))
    errors.extend(_check_tensor_refs(graph))
    errors.extend(_check_port_dtypes(graph))
    errors.extend(_check_acyclicity(graph))
    return errors


def _check_unknown_ops(graph: RfirGraph) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for node in graph.nodes:
        if node.op not in OP_REGISTRY:
            errors.append(ValidationError(node.id, f"unknown op: {node.op!r}"))
    return errors


def _check_duplicate_ids(graph: RfirGraph) -> list[ValidationError]:
    errors: list[ValidationError] = []
    seen: set[str] = set()
    for node in graph.nodes:
        if node.id in seen:
            errors.append(ValidationError(node.id, "duplicate node id"))
        seen.add(node.id)
    return errors


def _check_tensor_refs(graph: RfirGraph) -> list[ValidationError]:
    """Every input tensor must exist in graph.tensors or be produced by another node."""
    errors: list[ValidationError] = []
    produced: set[str] = set(graph.tensors.keys())
    for node in graph.nodes:
        for tensor_name in node.outputs.values():
            produced.add(tensor_name)

    for node in graph.nodes:
        for port_name, tensor_name in node.inputs.items():
            if tensor_name not in produced:
                errors.append(
                    ValidationError(node.id, f"input port {port_name!r} references unknown tensor {tensor_name!r}")
                )
    return errors


def _check_port_dtypes(graph: RfirGraph) -> list[ValidationError]:
    """Input tensor dtype must match the op's port spec."""
    errors: list[ValidationError] = []
    for node in graph.nodes:
        op_def = OP_REGISTRY.get(node.op)
        if op_def is None:
            continue
        port_specs = {p.name: p for p in op_def.inputs}
        for port_name, tensor_name in node.inputs.items():
            spec = port_specs.get(port_name)
            tensor = graph.tensors.get(tensor_name)
            if spec and tensor and tensor.dtype != spec.dtype:
                errors.append(
                    ValidationError(
                        node.id,
                        f"port {port_name!r} expects {spec.dtype.value} but tensor {tensor_name!r} is {tensor.dtype.value}",
                    )
                )
    return errors


def _check_acyclicity(graph: RfirGraph) -> list[ValidationError]:
    """Detect cycles via DFS on the node dependency graph."""
    tensor_to_producer: dict[str, str] = {}
    for node in graph.nodes:
        for tensor_name in node.outputs.values():
            tensor_to_producer[tensor_name] = node.id

    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for node in graph.nodes:
        for tensor_name in node.inputs.values():
            producer = tensor_to_producer.get(tensor_name)
            if producer and producer != node.id:
                adj[producer].append(node.id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n.id: WHITE for n in graph.nodes}
    errors: list[ValidationError] = []

    def dfs(nid: str) -> bool:
        color[nid] = GRAY
        for dep in adj.get(nid, []):
            if color[dep] == GRAY:
                errors.append(ValidationError(nid, f"cycle detected involving {nid!r} → {dep!r}"))
                return True
            if color[dep] == WHITE and dfs(dep):
                return True
        color[nid] = BLACK
        return False

    for nid in adj:
        if color[nid] == WHITE:
            dfs(nid)

    return errors
