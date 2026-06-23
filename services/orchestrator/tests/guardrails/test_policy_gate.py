"""Tests for Layer 0 — policy gate."""
import pytest

from app.guardrails.presets import RenderFlowPolicy
from app.guardrails.policy_gate import run_policy_gate, _get_rate_checker
from app.guardrails.types import RFReasonCode
from uuid import UUID

_PROJECT = UUID("00000000-0000-0000-0000-000000000001")


def _gate(mode="scene", user_role="editor", **kwargs):
    return run_policy_gate(_PROJECT, mode, user_id="u1", user_role=user_role)


def test_allow_baseline(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    d = _gate()
    assert d.verdict == "allow"


def test_block_viewer_role(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    d = _gate(user_role="viewer")
    assert d.blocked
    assert d.reason_code == RFReasonCode.VIEWER_ROLE


def test_block_ai_disabled(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    monkeypatch.setenv("RENDERFLOW_GUARDRAILS_ENABLED", "false")
    d = _gate()
    assert d.blocked
    assert d.reason_code == RFReasonCode.AI_DISABLED
