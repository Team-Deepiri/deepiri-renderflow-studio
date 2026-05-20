"""Unit tests proving the full AI job pipeline path.

Covers: stage_runner output, _process_job happy paths (scene + audio),
SSE event emission, cancellation, and invalid-id safety.
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.api.utils import EventEmitter
from app.config import Settings
from app.job_store import JobStatus, JobStore
from app.stage_runner import run_audio_stages, run_scene_stages

FAST = Settings(ai_stages_simulate_ms=0)


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Disable all Postgres calls so tests run without a real database."""
    import app.db as db_mod

    monkeypatch.setattr(db_mod, "pool_ready", lambda: False)
    monkeypatch.setattr(db_mod, "insert_ai_job", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "update_ai_job_status", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "sync_job_stages", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "get_ai_job", lambda *a: None)
    monkeypatch.setattr(db_mod, "get_ai_job_stages", lambda *a: [])


def _store() -> JobStore:
    return JobStore()


# ── stage_runner ──────────────────────────────────────────────────────────────


def test_scene_stages_output():
    results = run_scene_stages("test prompt")
    assert [r.stage for r in results] == ["preparing", "storyboard", "layout", "assets", "review"]
    assert all(r.status == "ok" for r in results)


def test_audio_stages_output():
    results = run_audio_stages("voice test")
    assert [r.stage for r in results] == ["preparing", "voice_cast", "mix_preview", "review"]
    assert all(r.status == "ok" for r in results)


# ── full job path ─────────────────────────────────────────────────────────────


def test_scene_job_reaches_committed():
    from app.worker_loop import _process_job

    store = _store()
    job = store.create(uuid4(), "scene", "smoke")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), FAST)

    final = store.get(job.id)
    assert final.status == JobStatus.COMMITTED
    assert "committed" in final.stages


def test_audio_job_reaches_committed():
    from app.worker_loop import _process_job

    store = _store()
    job = store.create(uuid4(), "audio", "narrate this")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), FAST)

    assert store.get(job.id).status == JobStatus.COMMITTED


def test_voice_mode_uses_audio_stages():
    from app.worker_loop import _process_job

    store = _store()
    job = store.create(uuid4(), "voice", "dialogue test")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), FAST)

    final = store.get(job.id)
    assert final.status == JobStatus.COMMITTED
    assert "voice_cast" in final.stages


# ── SSE events ────────────────────────────────────────────────────────────────


def test_job_emits_preparing_and_committed_events():
    from app.worker_loop import _process_job

    store = _store()
    job = store.create(uuid4(), "scene", "smoke")

    emitted: list[dict] = []
    emitter = EventEmitter()
    emitter.subscribe("job_update", emitted.append)

    with patch("app.worker_loop.store", store), \
         patch("app.worker_loop.get_event_emitter", return_value=emitter):
        _process_job(str(job.id), FAST)

    statuses = {e["status"] for e in emitted if e.get("job_id") == str(job.id)}
    assert "preparing" in statuses
    assert "running" in statuses
    assert "committed" in statuses


def test_job_emits_all_scene_stage_names():
    from app.worker_loop import _process_job

    store = _store()
    job = store.create(uuid4(), "scene", "smoke")

    emitted: list[dict] = []
    emitter = EventEmitter()
    emitter.subscribe("job_update", emitted.append)

    with patch("app.worker_loop.store", store), \
         patch("app.worker_loop.get_event_emitter", return_value=emitter):
        _process_job(str(job.id), FAST)

    running_stages = {
        e["stage"]
        for e in emitted
        if e.get("status") == "running" and e.get("job_id") == str(job.id)
    }
    assert running_stages == {"preparing", "storyboard", "layout", "assets", "review"}


def test_sse_events_carry_project_id():
    from app.worker_loop import _process_job

    store = _store()
    pid = uuid4()
    job = store.create(pid, "scene", "smoke")

    emitted: list[dict] = []
    emitter = EventEmitter()
    emitter.subscribe("job_update", emitted.append)

    with patch("app.worker_loop.store", store), \
         patch("app.worker_loop.get_event_emitter", return_value=emitter):
        _process_job(str(job.id), FAST)

    assert all(e.get("project_id") == str(pid) for e in emitted if e.get("job_id") == str(job.id))


# ── cancellation ──────────────────────────────────────────────────────────────


def test_job_cancelled_before_start():
    from app.worker_loop import _cancelled_jobs, _process_job

    store = _store()
    job = store.create(uuid4(), "scene", "cancel me")
    _cancelled_jobs.add(str(job.id))

    try:
        with patch("app.worker_loop.store", store):
            _process_job(str(job.id), FAST)
    finally:
        _cancelled_jobs.discard(str(job.id))

    assert store.get(job.id).status == JobStatus.CANCELLED


# ── error safety ──────────────────────────────────────────────────────────────


def test_invalid_job_id_does_not_raise():
    from app.worker_loop import _process_job

    _process_job("not-a-uuid", FAST)


def test_unknown_job_id_does_not_raise():
    from app.worker_loop import _process_job

    _process_job(str(uuid4()), FAST)
