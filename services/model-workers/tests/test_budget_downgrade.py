"""Tests for RFIR budget governor — downgrade-to-fit (§2.7)."""
import pytest

from app.rfir.budget import BudgetGovernor
from app.rfir.ir.types import InferenceBudget, RfirNode


def _node(op="t2i_keyframe", ms=800.0, **attrs) -> RfirNode:
    return RfirNode(id=f"{op}_0", op=op, attrs=dict(attrs), estimated_gpu_ms=ms)


def test_affordable_node_passes_through_unchanged():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=120))
    node = _node(ms=800.0, steps=4)  # 0.8s
    out = gov.before_node(node)
    assert out is node
    assert out.attrs["steps"] == 4
    assert gov.downgrades == []


def test_over_budget_node_is_downgraded():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=1.0))
    node = _node(ms=1600.0, steps=4)  # 1.6s > 1.0s budget
    out = gov.before_node(node)
    assert out is not node                 # copy returned
    assert node.attrs["steps"] == 4        # original untouched
    assert out.estimated_gpu_ms < 1600.0
    assert len(gov.downgrades) == 1


def test_downgrade_reduces_steps():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=0.5))
    out = gov.before_node(_node(ms=1600.0, steps=8))
    assert out.attrs["steps"] < 8



def test_spend_reduces_remaining_budget():
    budget = InferenceBudget(max_gpu_seconds=10.0)
    gov = BudgetGovernor(budget)
    gov.after_node(3.0)
    assert budget.remaining_gpu_seconds == 7.0
    # An 8s node no longer fits in the remaining 7s → gets downgraded.
    out = gov.before_node(_node(ms=8000.0, steps=4))
    assert out.estimated_gpu_ms < 8000.0
    assert len(gov.downgrades) == 1


def test_metrics_report():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=1.0))
    gov.before_node(_node(ms=1600.0, steps=4))
    m = gov.metrics()
    assert m["downgrade_count"] == 1
    assert m["downgrades"][0]["op"] == "t2i_keyframe"
    assert m["downgrades"][0]["after_ms"] < m["downgrades"][0]["before_ms"]


def test_unfittable_node_still_returns_best_effort():
    # Budget so small nothing fits; governor returns a downgraded best-effort node.
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=0.001))
    out = gov.before_node(_node(ms=10000.0, steps=4))
    assert out.estimated_gpu_ms < 10000.0
    assert gov.downgrades[0].reason == "over_budget"
    assert gov.downgrades[0].trigger == "gpu_time"


# ---------------------------------------------------------------------------
# VRAM hints (from memory_plan §2.2) drive downgrades
# ---------------------------------------------------------------------------

def test_vram_flagged_node_downgraded_even_when_time_affordable():
    # Node fits the GPU-time budget, but the memory planner flagged it as a hog.
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=120), vram_hints=["t2i_keyframe_0"])
    node = _node(ms=800.0, steps=4)  # 0.8s — well within budget
    out = gov.before_node(node)
    assert out is not node                          # downgraded despite fitting on time
    assert out.attrs["steps"] < 4
    assert gov.downgrades[0].trigger == "vram"
    assert gov.downgrades[0].reason == "downgraded_to_fit"


def test_unflagged_affordable_node_passes_through():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=120), vram_hints=["some_other_node"])
    node = _node(ms=800.0, steps=4)
    assert gov.before_node(node) is node            # not flagged, fits time → unchanged
    assert gov.downgrades == []


def test_both_triggers_recorded():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=1.0), vram_hints=["t2i_keyframe_0"])
    gov.before_node(_node(ms=1600.0, steps=4))      # over time AND flagged
    assert gov.downgrades[0].trigger == "gpu_time+vram"


def test_set_vram_hints_after_construction():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=120))
    gov.set_vram_hints(["t2i_keyframe_0"])          # e.g. from MemoryPlan.downgrade_hints
    out = gov.before_node(_node(ms=500.0, steps=4))
    assert out is not gov  # sanity
    assert gov.downgrades[0].trigger == "vram"


def test_trigger_in_metrics():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=120), vram_hints=["t2i_keyframe_0"])
    gov.before_node(_node(ms=500.0))
    assert gov.metrics()["downgrades"][0]["trigger"] == "vram"


# ---------------------------------------------------------------------------
# depth_estimate template (TIME + VRAM lever: infer_scale)
# ---------------------------------------------------------------------------

def test_depth_downgrade_halves_infer_scale():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=0.1))
    # 0.2s over the 0.1s budget; one halving (scale 1.0→0.5) gives 0.2 * 0.5^2 = 0.05s → fits.
    out = gov.before_node(_node(op="depth_estimate", ms=200.0))
    assert out.attrs["infer_scale"] == 0.5
    assert out.estimated_gpu_ms == pytest.approx(50.0)   # 200 * (0.5/1.0)**2
    assert gov.downgrades[0].reason == "downgraded_to_fit"


def test_depth_downgrade_stops_at_scale_floor():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=0.001))  # nothing fits
    out = gov.before_node(_node(op="depth_estimate", ms=200.0))
    assert out.attrs["infer_scale"] == 0.5               # floored, never below 0.5
    assert out.estimated_gpu_ms == pytest.approx(50.0)   # one halving applied, then no-ops
    assert gov.downgrades[0].reason == "over_budget"


def test_depth_default_scale_is_noop_baseline():
    # A depth node with no infer_scale that already fits is returned untouched.
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=120))
    node = _node(op="depth_estimate", ms=50.0)
    assert gov.before_node(node) is node
    assert "infer_scale" not in node.attrs               # default behavior unchanged


# ---------------------------------------------------------------------------
# Ops with NO template: left unchanged, recorded over_budget (no fake lever)
# ---------------------------------------------------------------------------

def test_no_template_op_over_time_unchanged():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=0.5))
    node = _node(op="segment_subject", ms=5000.0)        # no template (stub op)
    out = gov.before_node(node)
    assert out is node                                   # unchanged
    rec = gov.downgrades[0]
    assert rec.reason == "over_budget"
    assert rec.trigger == "gpu_time"
    assert rec.before_ms == rec.after_ms == 5000.0


def test_no_template_op_vram_only_unchanged():
    gov = BudgetGovernor(InferenceBudget(max_gpu_seconds=120), vram_hints=["vae_encode_0"])
    node = _node(op="vae_encode", ms=100.0)              # fits time, flagged for VRAM
    out = gov.before_node(node)
    assert out is node                                   # no honest lever → unchanged
    rec = gov.downgrades[0]
    assert rec.reason == "over_budget"
    assert rec.trigger == "vram"
    assert rec.before_ms == rec.after_ms == 100.0
