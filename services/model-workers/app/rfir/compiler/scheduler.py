"""RFIR Compiler — Schedule pass: topological sort + CUDA↔Vulkan barriers.

Takes an RfirGraph and produces an execution order (list of node IDs).
Inserts barrier markers between device transitions (e.g. CUDA → Vulkan).

Spec reference: rfir-inference-engine-implementation.md §0.5
"""
from __future__ import annotations

from app.rfir.ir.ops import OP_REGISTRY, OpDevice
from app.rfir.ir.types import RfirGraph


class CycleError(Exception):
    pass


def topological_sort(graph: RfirGraph) -> list[str]:
    """Return node IDs in dependency order. Raises CycleError on cycles."""
    tensor_to_producer: dict[str, str] = {}
    for node in graph.nodes:
        for tensor_name in node.outputs.values():
            tensor_to_producer[tensor_name] = node.id

    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}

    for node in graph.nodes:
        for tensor_name in node.inputs.values():
            producer = tensor_to_producer.get(tensor_name)
            if producer and producer != node.id:
                adj[producer].append(node.id)
                in_degree[node.id] += 1

    queue: list[str] = [nid for nid, deg in in_degree.items() if deg == 0]
    order: list[str] = []

    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for dep in adj[nid]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    if len(order) != len(graph.nodes):
        raise CycleError(f"cycle detected: scheduled {len(order)} of {len(graph.nodes)} nodes")

    return order


def schedule_with_barriers(graph: RfirGraph) -> list[str]:
    """Topological sort with barrier markers between device transitions.

    Returns a list of node IDs and "barrier:DEVICE_A→DEVICE_B" markers.
    """
    order = topological_sort(graph)

    result: list[str] = []
    prev_device: OpDevice | None = None

    for nid in order:
        node = graph.get_node(nid)
        if not node:
            continue
        op_def = OP_REGISTRY.get(node.op)
        cur_device = op_def.device if op_def else OpDevice.CPU

        if prev_device is not None and cur_device != prev_device:
            result.append(f"barrier:{prev_device.value}→{cur_device.value}")

        result.append(nid)
        prev_device = cur_device

    return result
