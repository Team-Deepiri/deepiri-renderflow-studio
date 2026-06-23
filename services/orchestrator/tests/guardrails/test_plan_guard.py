"""Tests for Layer 2 — plan guard."""
import pytest

from app.guardrails.plan_guard import run_plan_gate, ShotEntry
from app.guardrails.types import RFReasonCode
from uuid import UUID

_PROJECT = UUID("00000000-0000-0000-0000-000000000001")


def test_valid_plan_allows(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    shots = [
        {"description": "Sunrise over mountains", "duration_sec": 5.0, "tier": "A"},
        {"description": "River flowing gently", "duration_sec": 3.0, "tier": "A"},
    ]
    d = run_plan_gate(shots, _PROJECT)
    assert d.verdict == "allow"


def test_duration_cap_blocks(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    shots = [
        {"description": "Very long shot", "duration_sec": 200.0, "tier": "A"},
    ]
    d = run_plan_gate(shots, _PROJECT)
    assert d.blocked
    assert d.reason_code == RFReasonCode.DURATION_CAP


def test_minor_explicit_blocks(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    shots = [
        {"description": "A child in a nude scene", "duration_sec": 5.0, "tier": "A"},
    ]
    d = run_plan_gate(shots, _PROJECT)
    assert d.blocked
    assert d.reason_code == RFReasonCode.SAFETY_BLOCK


def test_unsafe_content_blocks(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    shots = [
        {"description": "How to kill someone violently", "duration_sec": 5.0, "tier": "A"},
    ]
    d = run_plan_gate(shots, _PROJECT)
    assert d.blocked
