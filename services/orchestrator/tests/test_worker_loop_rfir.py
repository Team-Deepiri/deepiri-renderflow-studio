"""Tests for worker_loop's RFIR dispatch mode (§ end-to-end pipeline wiring).

Covers: building the Redis payload sent to model-workers, and mirroring a
status report back into job_store. Uses a fake in-memory Redis client so no
real Redis server is needed.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

import app.main  # noqa: F401 -- resolves the app.api <-> app.worker_loop import cycle first
from app.config import Settings
from app.job_store import JobStatus, store
from app.worker_loop import _apply_rfir_status, _build_rfir_payload, enqueue_job, _rfir_inflight
from renderflow_queue import RfirJobState, RfirJobStatus


class FakeRedisList:
    """In-memory stand-in for the redis-py calls worker_loop/RedisJobQueue use."""

    def __init__(self) -> None:
        self.pushed: list[str] = []

    def rpush(self, key: str, value: str) -> None:
        self.pushed.append(value)


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    import app.db as db_mod

    monkeypatch.setattr(db_mod, "pool_ready", lambda: False)
    monkeypatch.setattr(db_mod, "insert_ai_job", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "update_ai_job_status", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "sync_job_stages", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "get_ai_job", lambda *a: None)


@pytest.fixture(autouse=True)
def _clear_inflight():
    _rfir_inflight.clear()
    yield
    _rfir_inflight.clear()


def test_build_rfir_payload_shape():
    rec = store.create(uuid4(), "scene", "a calm lake at sunrise",
                        metadata={"guardrail_verdict": "allow", "guardrail_flags": []})
    settings = Settings(rfir_max_gpu_sec=90, rfir_max_tier="B")

    payload = _build_rfir_payload(rec, settings)

    assert payload["prompt"] == "a calm lake at sunrise"
    assert payload["mode"] == "scene"
    assert payload["budget"] == {"max_gpu_seconds": 90, "max_tier": "B"}
    assert payload["guardrail_verdict"] == "allow"
    assert "project" in payload


def test_build_rfir_payload_carries_guardrail_flags():
    rec = store.create(uuid4(), "scene", "prompt with pii",
                        metadata={"guardrail_verdict": "allow", "guardrail_flags": ["PII_REDACTED"]})
    payload = _build_rfir_payload(rec, Settings())
    assert payload["guardrail_flags"] == ["PII_REDACTED"]


def test_enqueue_job_rfir_mode_pushes_full_payload(monkeypatch):
    rec = store.create(uuid4(), "scene", "a hero running through rain")
    settings = Settings(rfir_enabled=True, redis_url="redis://fake/0")

    fake_redis = FakeRedisList()
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **kw: fake_redis)

    enqueue_job(str(rec.id), settings)

    assert len(fake_redis.pushed) == 1
    body = json.loads(fake_redis.pushed[0])
    assert body["job_id"] == str(rec.id)
    assert body["payload"]["prompt"] == "a hero running through rain"
    assert str(rec.id) in _rfir_inflight


def test_enqueue_job_rfir_disabled_uses_legacy_path(monkeypatch):
    rec = store.create(uuid4(), "scene", "a calm lake")
    settings = Settings(rfir_enabled=False, redis_url=None)

    enqueue_job(str(rec.id), settings)

    # Falls through to the local in-process queue — no RFIR dispatch tracked.
    assert str(rec.id) not in _rfir_inflight


def test_enqueue_job_rfir_enabled_without_redis_falls_back(monkeypatch):
    rec = store.create(uuid4(), "scene", "a calm lake")
    settings = Settings(rfir_enabled=True, redis_url=None)

    enqueue_job(str(rec.id), settings)

    # No Redis URL means no channel to model-workers — must not crash,
    # and must not pretend the job was dispatched.
    assert str(rec.id) not in _rfir_inflight


# ---------------------------------------------------------------------------
# Status mirroring
# ---------------------------------------------------------------------------

def test_apply_rfir_status_preparing():
    rec = store.create(uuid4(), "scene", "prompt")
    _apply_rfir_status(rec.id, rec, RfirJobStatus(job_id=str(rec.id), state=RfirJobState.PREPARING))

    updated = store.get(rec.id)
    assert updated.status == JobStatus.PREPARING


def test_apply_rfir_status_running_merges_metadata():
    rec = store.create(uuid4(), "scene", "prompt")
    status = RfirJobStatus(
        job_id=str(rec.id), state=RfirJobState.RUNNING, stage="storyboard",
        metadata={"stage_storyboard": {"shot_count": 3}},
    )
    _apply_rfir_status(rec.id, rec, status)

    updated = store.get(rec.id)
    assert updated.status == JobStatus.RUNNING
    assert "storyboard" in updated.stages
    assert updated.metadata["stage_storyboard"] == {"shot_count": 3}


def test_apply_rfir_status_review_sets_output_path():
    rec = store.create(uuid4(), "scene", "prompt")
    status = RfirJobStatus(
        job_id=str(rec.id), state=RfirJobState.REVIEW,
        artifacts={"output_mp4": "/tmp/out.mp4"},
        metrics={"total_gpu_ms": 500.0},
    )
    _apply_rfir_status(rec.id, rec, status)

    updated = store.get(rec.id)
    assert updated.status == JobStatus.REVIEW
    assert updated.metadata["output_path"] == "/tmp/out.mp4"
    assert updated.metadata["rfir_metrics"]["total_gpu_ms"] == 500.0


def test_apply_rfir_status_failed_records_error():
    rec = store.create(uuid4(), "scene", "prompt")
    status = RfirJobStatus(job_id=str(rec.id), state=RfirJobState.FAILED, error="model load failed")
    _apply_rfir_status(rec.id, rec, status)

    updated = store.get(rec.id)
    assert updated.status == JobStatus.FAILED
    assert updated.metadata["error"] == "model load failed"
