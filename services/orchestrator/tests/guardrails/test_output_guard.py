"""Tests for Layer 4 — output guard."""
import pytest

from app.guardrails.output_guard import run_output_gate
from app.guardrails.types import RFReasonCode
from uuid import UUID

_PROJECT = UUID("00000000-0000-0000-0000-000000000001")


def test_allow_baseline(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    d, prov = run_output_gate("job-1", _PROJECT)
    assert d.verdict == "allow"


def test_provenance_sidecar_included(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    monkeypatch.setenv("RENDERFLOW_GUARDRAIL_PROVENANCE", "json")
    d, prov = run_output_gate("job-1", _PROJECT, model_ids=["flux-schnell"])
    assert prov.get("ai_generated") is True
    assert prov.get("job_id") == "job-1"
    assert "flux-schnell" in prov.get("model_ids", [])


def test_likeness_strict_blocks(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "prod")
    monkeypatch.setenv("RENDERFLOW_GUARDRAIL_PRESET", "us_default")
    d, _ = run_output_gate("job-1", _PROJECT, has_likeness_match=True)
    assert d.blocked
    assert d.reason_code == RFReasonCode.LIKENESS_BLOCK


def test_copyright_high_blocks(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "prod")
    monkeypatch.setenv("RENDERFLOW_GUARDRAIL_PRESET", "eu")
    d, _ = run_output_gate("job-1", _PROJECT, copyright_similarity_score=0.85)
    assert d.blocked
    assert d.reason_code == RFReasonCode.OUTPUT_BLOCK


def test_copyright_medium_escalates(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "prod")
    monkeypatch.setenv("RENDERFLOW_GUARDRAIL_PRESET", "us_default")
    d, prov = run_output_gate("job-1", _PROJECT, copyright_similarity_score=0.65)
    assert d.verdict == "escalate"
    assert d.reason_code == RFReasonCode.COPYRIGHT_WARN
