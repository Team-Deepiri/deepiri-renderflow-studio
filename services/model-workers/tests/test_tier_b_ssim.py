"""Tests for RFIR Tier B SSIM escalation decision (§2.6).

Only the pure decision logic is unit-tested; compute_ssim (in engine.py) is
GPU/dep-gated (needs numpy + skimage) and validated like the Phase 1 ops.
"""
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
