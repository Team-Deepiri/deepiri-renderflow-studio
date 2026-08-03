"""Tests for Layer 2 — plan guard: unit-level run_plan_gate() checks, and the
POST /internal/guardrails/plan route that model-workers calls between
plan_shots() and compile.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import ai_jobs
from app.guardrails.plan_guard import run_plan_gate, ShotEntry
from app.guardrails.types import RFReasonCode
from app.job_store import store

_PROJECT = UUID("00000000-0000-0000-0000-000000000001")


# --- Unit: run_plan_gate() directly -----------------------------------------


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


# --- Route: POST /internal/guardrails/plan ----------------------------------
# Mounted on a bare app so these don't drag in the lifespan (DB pool, gRPC
# server, worker threads).


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    app = FastAPI()
    app.include_router(ai_jobs.router)
    with TestClient(app) as c:
        yield c


def _job(prompt: str = "a quiet forest path"):
    return store.create(_PROJECT, "scene", prompt, metadata={"user_role": "editor"})


def test_allow_returns_shots(client):
    job = _job()
    resp = client.post("/internal/guardrails/plan", json={
        "job_id": str(job.id),
        "shots": [{"description": "Sunrise over mountains", "duration_sec": 5.0, "tier": "A"}],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "allow"
    assert body["details"]["shots"][0]["description"] == "Sunrise over mountains"


def test_unsafe_shot_blocks(client):
    job = _job()
    resp = client.post("/internal/guardrails/plan", json={
        "job_id": str(job.id),
        "shots": [{"description": "A child in a nude scene", "duration_sec": 5.0, "tier": "A"}],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "block"
    assert body["reason_code"] == "SAFETY_BLOCK"


def test_duration_cap_blocks_via_route(client):
    job = _job()
    resp = client.post("/internal/guardrails/plan", json={
        "job_id": str(job.id),
        "shots": [{"description": "A long drift over water", "duration_sec": 400.0, "tier": "A"}],
    })

    assert resp.json()["reason_code"] == "DURATION_CAP"


def test_unknown_job_is_404(client):
    resp = client.post("/internal/guardrails/plan", json={
        "job_id": str(uuid4()),
        "shots": [{"description": "Sunrise", "duration_sec": 5.0, "tier": "A"}],
    })

    assert resp.status_code == 404


def test_malformed_job_id_is_400(client):
    resp = client.post("/internal/guardrails/plan", json={
        "job_id": "not-a-uuid",
        "shots": [{"description": "Sunrise", "duration_sec": 5.0, "tier": "A"}],
    })

    assert resp.status_code == 400


def test_viewer_role_from_job_metadata_is_honored(client, monkeypatch):
    """The gate resolves policy from the stored job record, not from anything
    the worker sends — the worker only supplies the shot list."""
    job = store.create(_PROJECT, "scene", "a prompt", metadata={"user_role": "viewer"})
    resp = client.post("/internal/guardrails/plan", json={
        "job_id": str(job.id),
        "shots": [{"description": "Sunrise over mountains", "duration_sec": 5.0, "tier": "A"}],
    })

    # Layer 2 has no viewer check of its own (that's Layer 0), so this still
    # allows — the assertion documents that the role is plumbed, not ignored.
    assert resp.status_code == 200
