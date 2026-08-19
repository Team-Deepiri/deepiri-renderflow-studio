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
from app.worker_loop import (
    _apply_rfir_status,
    _build_rfir_payload,
    _process_scene_job_rfir,
    _rfir_inflight,
    enqueue_job,
)
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


# ---------------------------------------------------------------------------
# guardrail_verdict — must fail closed the same way redis_worker does
# (model-workers/tests/test_redis_worker.py::test_missing_guardrail_verdict_refuses)
# ---------------------------------------------------------------------------

def test_build_rfir_payload_missing_verdict_is_not_an_allow():
    """A record whose metadata never got stamped must not be handed to the
    worker as an implicit allow — that would run ungated GPU work."""
    rec = store.create(uuid4(), "scene", "prompt", metadata={})

    assert _build_rfir_payload(rec, Settings())["guardrail_verdict"] != "allow"


def test_build_rfir_payload_empty_verdict_is_not_an_allow():
    rec = store.create(uuid4(), "scene", "prompt", metadata={"guardrail_verdict": ""})

    assert _build_rfir_payload(rec, Settings())["guardrail_verdict"] != "allow"


def test_build_rfir_payload_passes_a_real_verdict_through():
    """Non-allow verdicts reach the worker verbatim rather than being
    normalised, so its refusal message names the actual decision."""
    rec = store.create(uuid4(), "scene", "prompt", metadata={"guardrail_verdict": "block"})

    assert _build_rfir_payload(rec, Settings())["guardrail_verdict"] == "block"


def test_in_process_rfir_path_refuses_a_missing_verdict(monkeypatch, tmp_path):
    """The in-process fallback generates real frames too, so it has to refuse
    an unstamped job instead of running it just because Redis was down."""
    called = False

    def _should_not_run(*a, **kw):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(
        "app.media.cfsv_pipeline.compile_and_run_tier_a", _should_not_run,
    )
    rec = store.create(uuid4(), "scene", "prompt", metadata={})

    _process_scene_job_rfir(rec.id, rec, Settings())

    updated = store.get(rec.id)
    assert updated.status == JobStatus.FAILED
    assert "guardrail_verdict" in updated.metadata["error"]
    assert not called, "generation ran despite an unstamped guardrail_verdict"


# ---------------------------------------------------------------------------
# nsfw_mode — the worker's Layer 3 strictness comes from the project policy
# (_no_db above stubs pool_ready False, so fetch_project returns None and the
# preset + env are what resolve the mode).
# ---------------------------------------------------------------------------

def test_build_rfir_payload_nsfw_mode_follows_dev_preset(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    monkeypatch.delenv("RENDERFLOW_GUARDRAIL_NSFW_MODE", raising=False)
    rec = store.create(uuid4(), "scene", "prompt")

    assert _build_rfir_payload(rec, Settings())["nsfw_mode"] == "off"


def test_build_rfir_payload_nsfw_mode_blocks_outside_dev(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "prod")
    monkeypatch.setenv("RENDERFLOW_GUARDRAIL_PRESET", "us_default")
    monkeypatch.delenv("RENDERFLOW_GUARDRAIL_NSFW_MODE", raising=False)
    rec = store.create(uuid4(), "scene", "prompt")

    assert _build_rfir_payload(rec, Settings())["nsfw_mode"] == "block"


def test_build_rfir_payload_nsfw_mode_carries_restricted(monkeypatch):
    """The case the hardcoded default made unreachable: a policy that is
    neither fully off nor fully blocking has to survive the trip to the
    worker, or check_keyframe silently uses the stricter threshold."""
    monkeypatch.setenv("READINESS_MODE", "prod")
    monkeypatch.setenv("RENDERFLOW_GUARDRAIL_NSFW_MODE", "restricted")
    rec = store.create(uuid4(), "scene", "prompt")

    assert _build_rfir_payload(rec, Settings())["nsfw_mode"] == "restricted"


def test_build_rfir_payload_nsfw_mode_ignores_caller_metadata(monkeypatch):
    """Job metadata is client-supplied, so it must not be able to relax the
    generation guard."""
    monkeypatch.setenv("READINESS_MODE", "prod")
    monkeypatch.setenv("RENDERFLOW_GUARDRAIL_PRESET", "us_default")
    monkeypatch.delenv("RENDERFLOW_GUARDRAIL_NSFW_MODE", raising=False)
    rec = store.create(uuid4(), "scene", "prompt", metadata={"nsfw_mode": "off"})

    assert _build_rfir_payload(rec, Settings())["nsfw_mode"] == "block"


def test_build_rfir_payload_nsfw_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")  # would otherwise resolve to "off"

    def _boom(*a, **kw):
        raise RuntimeError("policy lookup exploded")

    monkeypatch.setattr("app.worker_loop.policy_for_project", _boom)
    rec = store.create(uuid4(), "scene", "prompt")

    assert _build_rfir_payload(rec, Settings())["nsfw_mode"] == "block"


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


def test_apply_rfir_status_review_sets_output_path(tmp_path):
    mp4 = tmp_path / "out.mp4"
    mp4.write_bytes(b"fake mp4")  # a real, readable artifact
    rec = store.create(uuid4(), "scene", "prompt")
    status = RfirJobStatus(
        job_id=str(rec.id), state=RfirJobState.REVIEW,
        artifacts={"output_mp4": str(mp4)},
        metrics={"total_gpu_ms": 500.0},
    )
    _apply_rfir_status(rec.id, rec, status)

    updated = store.get(rec.id)
    assert updated.status == JobStatus.REVIEW
    assert updated.metadata["output_path"] == str(mp4.resolve())
    assert updated.metadata["rfir_metrics"]["total_gpu_ms"] == 500.0


def test_apply_rfir_status_review_missing_output_fails():
    rec = store.create(uuid4(), "scene", "prompt")
    status = RfirJobStatus(
        job_id=str(rec.id), state=RfirJobState.REVIEW,
        artifacts={"output_mp4": "/tmp/does-not-exist-abcxyz.mp4"},
    )
    _apply_rfir_status(rec.id, rec, status)

    updated = store.get(rec.id)
    assert updated.status == JobStatus.FAILED
    assert "output_path" not in updated.metadata
    assert "output" in updated.metadata["error"]


def test_apply_rfir_status_failed_records_error():
    rec = store.create(uuid4(), "scene", "prompt")
    status = RfirJobStatus(job_id=str(rec.id), state=RfirJobState.FAILED, error="model load failed")
    _apply_rfir_status(rec.id, rec, status)

    updated = store.get(rec.id)
    assert updated.status == JobStatus.FAILED
    assert updated.metadata["error"] == "model load failed"
