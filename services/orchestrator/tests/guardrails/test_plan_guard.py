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


def test_allow_returns_shots_so_downgrades_survive(monkeypatch):
    """The tier cap mutates local copies when dicts are passed in; without the
    shots coming back on the decision the downgrade is silently lost."""
    monkeypatch.setenv("READINESS_MODE", "dev")
    monkeypatch.setenv("RENDERFLOW_GUARDRAIL_PRESET", "us_default")
    shots = [{"description": "Sunrise over mountains", "duration_sec": 5.0, "tier": "D"}]

    d = run_plan_gate(shots, _PROJECT)

    assert d.verdict == "allow"
    returned = d.details["shots"]
    assert len(returned) == 1
    # policy.max_tier defaults to "C", so D must come back capped.
    assert returned[0]["tier"] == "C"
    assert returned[0]["description"] == "Sunrise over mountains"


def test_allow_returns_shots_unchanged_when_within_cap(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    shots = [
        {"description": "A quiet forest path", "duration_sec": 4.0, "tier": "A"},
        {"description": "Wind through tall grass", "duration_sec": 3.0, "tier": "B"},
    ]

    d = run_plan_gate(shots, _PROJECT)

    assert d.verdict == "allow"
    assert [s["tier"] for s in d.details["shots"]] == ["A", "B"]


def test_block_omits_shots(monkeypatch):
    """Blocks short-circuit before the shot payload is built — clients must
    read details["shots"] with a default rather than assume it's present."""
    monkeypatch.setenv("READINESS_MODE", "dev")
    shots = [{"description": "Very long shot", "duration_sec": 200.0, "tier": "A"}]

    d = run_plan_gate(shots, _PROJECT)

    assert d.blocked
    assert "shots" not in d.details
