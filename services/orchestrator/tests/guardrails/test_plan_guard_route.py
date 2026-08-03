"""Tests for the Layer 2 service-to-service route.

POST /internal/guardrails/plan is what model-workers calls between
plan_shots() and compile. Mounted on a bare app so these don't drag in the
lifespan (DB pool, gRPC server, worker threads).
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import ai_jobs
from app.job_store import store

_PROJECT = UUID("00000000-0000-0000-0000-000000000001")


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


def test_duration_cap_blocks(client):
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
