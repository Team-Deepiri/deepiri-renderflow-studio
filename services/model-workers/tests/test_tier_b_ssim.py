"""Tests for the RFIR Tier B SSIM quality gate (§2.6).

Covers the pure decision logic, the compiler wiring that feeds it a
verification keyframe, and the executor gate that scores RIFE's midpoint
against that keyframe.
"""
import pytest

from app.rfir.executor.context import decide_escalation

DEFAULT_SSIM_THRESHOLD = 0.85  # mirror the inlined default in decide_escalation


def test_high_ssim_no_escalation():
    d = decide_escalation(0.95, escalations_remaining=2)
    assert d.escalate is False
    assert d.reason == "quality_ok"


def test_low_ssim_escalates_when_budget_allows():
    d = decide_escalation(0.50, escalations_remaining=2)
    assert d.escalate is True
    assert d.reason == "low_ssim"
    assert d.ssim == 0.50


def test_low_ssim_blocked_when_no_escalations_left():
    d = decide_escalation(0.50, escalations_remaining=0)
    assert d.escalate is False
    assert d.reason == "no_escalations_left"


def test_threshold_boundary_is_inclusive():
    # Exactly at threshold counts as OK (>=).
    d = decide_escalation(DEFAULT_SSIM_THRESHOLD, escalations_remaining=1)
    assert d.escalate is False


def test_custom_threshold():
    d = decide_escalation(0.80, threshold=0.75, escalations_remaining=1)
    assert d.escalate is False  # 0.80 >= 0.75
    d2 = decide_escalation(0.70, threshold=0.75, escalations_remaining=1)
    assert d2.escalate is True


# ---------------------------------------------------------------------------
# Compiler wiring — the gate is inert unless the builder supplies a
# verification keyframe, which it did not until this was wired up.
# ---------------------------------------------------------------------------

def _tier_b_graph():
    from app.rfir.compiler.builder import build
    from app.rfir.ir.types import CameraMotion, CameraPath, Shot, ShotList, Tier

    return build(ShotList(prompt="p", shots=[
        Shot(index=0, description="a dancer spinning", tier=Tier.B, duration_sec=4.0,
             camera=CameraPath(motion=CameraMotion.PAN, speed=1.0)),
    ]))


def test_tier_b_has_exactly_two_keyframes():
    """The gate scores the endpoints against each other, so there is no third
    'verification' keyframe. See the plan doc §7c for why that was dropped."""
    graph = _tier_b_graph()
    t2i = [n for n in graph.nodes if n.op == "t2i_keyframe"]
    assert len(t2i) == 2, "start and end only"
    assert graph.get_node("s0_t2i_verify") is None
    assert "s0_kf_verify" not in graph.tensors


def test_rife_node_carries_the_escalation_budget():
    rife = _tier_b_graph().get_node("s0_rife")
    assert rife.inputs == {"frame_start": "s0_kf_start", "frame_end": "s0_kf_end"}
    assert rife.attrs["escalations_remaining"] >= 1
    assert "verify_keyframe" not in rife.attrs


def test_tier_b_graph_still_validates():
    from app.rfir.ir.validate import validate

    assert validate(_tier_b_graph()) == []


def test_both_keyframes_are_scheduled_before_rife():
    from app.rfir.compiler.scheduler import topological_sort

    order = topological_sort(_tier_b_graph())
    assert order.index("s0_t2i_start") < order.index("s0_rife")
    assert order.index("s0_t2i_end") < order.index("s0_rife")


def test_escalation_budget_is_overridable_per_shot():
    from app.rfir.compiler.builder import build
    from app.rfir.ir.types import Shot, ShotList, Tier

    graph = build(ShotList(prompt="p", shots=[
        Shot(index=0, description="d", tier=Tier.B, attrs={"escalations_remaining": 0}),
    ]))
    assert graph.get_node("s0_rife").attrs["escalations_remaining"] == 0


# ---------------------------------------------------------------------------
# compute_ssim + the executor gate
# ---------------------------------------------------------------------------

def _img(color, size=(64, 64)):
    Image = pytest.importorskip("PIL.Image")
    return Image.new("RGB", size, color)


def test_compute_ssim_identical_images_score_1():
    from app.rfir.executor.engine import compute_ssim

    img = _img((120, 30, 200))
    assert compute_ssim(img, img) == pytest.approx(1.0, abs=1e-6)


def test_compute_ssim_dissimilar_images_score_low():
    from app.rfir.executor.engine import compute_ssim

    assert compute_ssim(_img((0, 0, 0)), _img((255, 255, 255))) < 0.5


def test_compute_ssim_resizes_mismatched_inputs():
    from app.rfir.executor.engine import compute_ssim

    # Must not raise on a size mismatch — the verification keyframe is
    # generated at gen-res while frames may have been upscaled.
    score = compute_ssim(_img((10, 10, 10), (64, 64)), _img((10, 10, 10), (32, 32)))
    assert 0.0 <= score <= 1.0


def _gate(start_img, end_img, *, escalations=1):
    """Run the executor's SSIM gate over a keyframe pair; return the context."""
    from app.rfir.executor import engine
    from app.rfir.executor.context import ExecutionContext
    from app.rfir.ir.types import RfirNode

    node = RfirNode(id="s0_rife", op="rife_interpolate",
                    attrs={"escalations_remaining": escalations})
    ctx = ExecutionContext(job_id="t")
    engine._run_ssim_gate(node, ctx, start_img, end_img)
    return ctx


def test_gate_passes_when_endpoints_are_close():

    img = _img((90, 140, 60))
    ctx = _gate(img, img)

    assert len(ctx.escalations) == 1
    assert ctx.escalations[0]["escalate"] is False
    assert ctx.escalations[0]["reason"] == "quality_ok"
    assert ctx.escalations[0]["ssim"] == pytest.approx(1.0, abs=1e-6)


def test_gate_escalates_when_endpoints_diverge():

    ctx = _gate(_img((0, 0, 0)), _img((255, 255, 255)))

    assert ctx.escalations[0]["escalate"] is True
    assert ctx.escalations[0]["reason"] == "low_ssim"


def test_gate_respects_an_exhausted_escalation_budget():

    ctx = _gate(_img((0, 0, 0)), _img((255, 255, 255)), escalations=0)

    assert ctx.escalations[0]["escalate"] is False
    assert ctx.escalations[0]["reason"] == "no_escalations_left"


def test_gate_survives_a_scoring_failure():
    """A quality gate must never fail the render — notably, compute_ssim
    raises ImportError whenever scikit-image is missing from the venv."""
    from app.rfir.executor import engine

    img = _img((5, 5, 5))
    original = engine.compute_ssim
    engine.compute_ssim = lambda a, b: (_ for _ in ()).throw(ImportError("no skimage"))
    try:
        ctx = _gate(img, img)
    finally:
        engine.compute_ssim = original

    assert ctx.escalations == []


def test_gate_runs_before_interpolation(monkeypatch, tmp_path):
    """The gate scores the pair, so it must not depend on RIFE's output —
    and once escalation exists it is the hook for skipping a doomed shot."""
    from app.rfir.arena import TensorArena
    from app.rfir.executor import engine
    from app.rfir.executor.context import ExecutionContext
    from app.rfir.ir.types import RfirNode

    order = []
    monkeypatch.setattr(engine, "_run_ssim_gate",
                        lambda *a, **k: order.append("gate"))
    monkeypatch.setattr(engine.rife_interpolate, "run",
                        lambda s, e, factor=4: order.append("rife") or [s, s, e])

    arena = TensorArena()
    arena.put("a", _img((1, 1, 1)))
    arena.put("b", _img((2, 2, 2)))
    node = RfirNode(id="s0_rife", op="rife_interpolate",
                    inputs={"frame_start": "a", "frame_end": "b"},
                    outputs={"frames": "out"})
    engine._run_rife_interpolate(node, arena, ExecutionContext(job_id="t"), tmp_path)

    assert order == ["gate", "rife"]
