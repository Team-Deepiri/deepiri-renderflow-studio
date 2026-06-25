"""RFIR Compiler — Fusion pass: batch t2i_keyframe nodes across shots.

This collapses all 't21_keyframe' nodes that share a generation config into 
a single batched node, then mutates and returns the graph so it can be 
chained after `build()`.

Spec reference: rfir-inference-engine-implementation.md §2.1
"""
from __future__ import annotations

from app.rfir.ir.types import RfirGraph, RfirNode

T2I_OP = "t2i_keyframe"

# Default generation config — mirrors ops/t2i_keyframe.run() and the builder.
_DEFAULT_WIDTH = 512
_DEFAULT_HEIGHT = 288
_DEFAULT_STEPS = 4


def _fusion_key(node: RfirNode) -> tuple[int, int, int]:
    """Group key: t2i nodes with the same (width, height, steps) can be batched."""
    a = node.attrs
    return (
        int(a.get("width", _DEFAULT_WIDTH)),
        int(a.get("height", _DEFAULT_HEIGHT)),
        int(a.get("steps", _DEFAULT_STEPS)),
    )


def _single_output_tensor(node: RfirNode) -> str | None:
    """t2i_keyframe nodes have one output ('image'); return its tensor name."""
    if "image" in node.outputs:
        return node.outputs["image"]
    if node.outputs:
        return next(iter(node.outputs.values()))
    return None


def fuse(graph: RfirGraph) -> RfirGraph:
    """Collapse same-config t2i_keyframe nodes into batched nodes.

    Returns the (mutated) graph. Groups of one node are left untouched.
    """
    # Bucket t2i nodes by config, preserving first-seen order within each group.
    groups: dict[tuple[int, int, int], list[RfirNode]] = {}
    for node in graph.nodes:
        if node.op == T2I_OP and not node.attrs.get("batch"):
            groups.setdefault(_fusion_key(node), []).append(node)

    fusable = {k: v for k, v in groups.items() if len(v) >= 2}
    if not fusable:
        return graph

    existing_ids = set(graph.node_ids())
    fused_count = 0
    nodes_before = sum(len(v) for v in groups.values())

    # Map each member node -> the fused node that replaces it, plus the fused
    # nodes themselves keyed by the index of the earliest member (insertion point).
    member_to_fused: dict[str, RfirNode] = {}
    insert_at: dict[int, RfirNode] = {}
    index_of = {node.id: i for i, node in enumerate(graph.nodes)}

    for group_idx, (key, members) in enumerate(fusable.items()):
        width, height, steps = key

        fused_id = f"t2i_batch_{group_idx}"
        while fused_id in existing_ids:  # guarantee uniqueness
            fused_id = f"{fused_id}_x"
        existing_ids.add(fused_id)

        prompts: list[str] = []
        outputs: dict[str, str] = {}
        for i, member in enumerate(members):
            tensor = _single_output_tensor(member)
            if tensor is None:
                continue
            prompts.append(str(member.attrs.get("prompt", "")))
            outputs[f"image_{i}"] = tensor

        # Cost model: weights are shared across the batch, so VRAM tracks the
        # heaviest member; compute time grows sublinearly with batch size.
        base_ms = max((m.estimated_gpu_ms for m in members), default=0.0)
        extra_ms = sum(sorted((m.estimated_gpu_ms for m in members), reverse=True)[1:])
        fused = RfirNode(
            id=fused_id,
            op=T2I_OP,
            outputs=outputs,
            attrs={
                "batch": True,
                "batch_size": len(prompts),
                "prompts": prompts,
                "steps": steps,
                "width": width,
                "height": height,
            },
            estimated_gpu_ms=base_ms + 0.6 * extra_ms,
            vram_mb=max((m.vram_mb for m in members), default=0.0),
        )

        for member in members:
            member_to_fused[member.id] = fused
        insert_at[min(index_of[m.id] for m in members)] = fused
        fused_count += 1

    # Rebuild the node list: drop fused members, drop the fused node in at the
    # position of its earliest member.
    new_nodes: list[RfirNode] = []
    for i, node in enumerate(graph.nodes):
        if i in insert_at:
            new_nodes.append(insert_at[i])
        if node.id in member_to_fused:
            continue  # original member is replaced by the fused node
        new_nodes.append(node)

    graph.nodes = new_nodes
    graph.metadata["fusion"] = {
        "t2i_groups_fused": fused_count,
        "t2i_nodes_before": nodes_before,
        "t2i_nodes_after": sum(1 for n in graph.nodes if n.op == T2I_OP),
    }
    return graph
