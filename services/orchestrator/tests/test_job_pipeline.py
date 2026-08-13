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


def test_scene_job_reaches_review():
    from app.worker_loop import _process_job

    store = _store()
    job = store.create(uuid4(), "scene", "smoke")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), FAST)

    final = store.get(job.id)
    assert final.status == JobStatus.REVIEW
    assert "review" in final.stages


def test_audio_job_reaches_review():
    from app.worker_loop import _process_job

    store = _store()
    job = store.create(uuid4(), "audio", "narrate this")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), FAST)

    assert store.get(job.id).status == JobStatus.REVIEW


def test_voice_mode_uses_audio_stages():
    from app.worker_loop import _process_job

    store = _store()
    job = store.create(uuid4(), "voice", "dialogue test")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), FAST)

    final = store.get(job.id)
    assert final.status == JobStatus.REVIEW
    assert "voice_cast" in final.stages


# ── SSE events ────────────────────────────────────────────────────────────────


def test_job_emits_preparing_and_review_events():
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
    assert "review" in statuses


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


# ── accept → asset bin ────────────────────────────────────────────────────────


def test_accept_creates_video_asset(tmp_path, monkeypatch):
    import shutil
    import subprocess

    from app.api.routers.ai_jobs import accept_ai_job
    from app.job_store import JobStatus
    from app.services import studio

    output = tmp_path / "scene.mp4"
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)],
            check=False, capture_output=True,
        )
    if not output.exists():
        output.write_bytes(b"\x00")

    store = _store()
    pid = uuid4()
    job = store.create(pid, "scene", "sunset beach")

    store.update_status(job.id, JobStatus.REVIEW, stages=["preparing", "storyboard", "review"])
    store.merge_meta(job.id, "output_path", str(output))

    class _NoThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return None

    monkeypatch.setattr("app.api.routers.ai_jobs.store", store)
    monkeypatch.setattr(
        "app.api.routers.ai_jobs.ffmpeg_util.detect_format",
        lambda _path: {
            "ok": True,
            "duration_seconds": 1.0,
            "video": {"width": 320, "height": 240},
        },
    )

    result = accept_ai_job(job.id)

    assert result.status == JobStatus.COMMITTED
    assert result.metadata.get("asset_id")
    assets = studio.list_assets(pid)
    assert len(assets) == 1
    assert assets[0]["kind"] == "video"
    assert assets[0]["meta_jsonb"].get("source") == "ai"
    assert assets[0]["meta_jsonb"].get("proxy_status") == "ready"


class _NoThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        return None


def test_accept_asset_uses_real_path_and_hash(tmp_path, monkeypatch):
    """The created asset must reference the real resolved file with a real
    content hash"""
    from app.api.routers.ai_jobs import accept_ai_job
    from app.services import studio

    output = tmp_path / "clip.mp4"
    output.write_bytes(b"real mp4 bytes")

    store = _store()
    pid = uuid4()
    job = store.create(pid, "scene", "hash check")
    store.update_status(job.id, JobStatus.REVIEW, stages=["review"])
    store.merge_meta(job.id, "output_path", str(output))

    monkeypatch.setattr("app.api.routers.ai_jobs.store", store)
    monkeypatch.setattr("app.api.routers.ai_jobs.threading.Thread", _NoThread)
    monkeypatch.setattr(
        "app.api.routers.ai_jobs.ffmpeg_util.detect_format",
        lambda _path: {
            "ok": True,
            "duration_seconds": 1.0,
            "video": {"width": 320, "height": 240},
        },
    )

    result = accept_ai_job(job.id)
    assert result.status == JobStatus.COMMITTED

    asset = studio.list_assets(pid)[0]
    assert asset["uri"] == str(output.resolve())          
    assert asset["sha256"] != "pending"                   
    assert len(asset["sha256"]) == 64                     


def test_accept_rejects_when_output_path_unset(monkeypatch):
    """A job with no output_path can't be accepted — 409, no asset created."""
    from fastapi import HTTPException

    from app.api.routers.ai_jobs import accept_ai_job

    store = _store()
    job = store.create(uuid4(), "scene", "no output job")
    store.update_status(job.id, JobStatus.REVIEW, stages=["review"])  # output_path never set
    monkeypatch.setattr("app.api.routers.ai_jobs.store", store)

    with pytest.raises(HTTPException) as exc:
        accept_ai_job(job.id)
    assert exc.value.status_code == 409
    assert store.get(job.id).status == JobStatus.REVIEW          
    assert "asset_id" not in store.get(job.id).metadata


def test_accept_rejects_when_output_file_missing(monkeypatch, tmp_path):
    """output_path set but the file doesn't exist on disk -> 409, no asset."""
    from fastapi import HTTPException

    from app.api.routers.ai_jobs import accept_ai_job

    store = _store()
    job = store.create(uuid4(), "scene", "missing file job")
    store.update_status(job.id, JobStatus.REVIEW, stages=["review"])
    store.merge_meta(job.id, "output_path", str(tmp_path / "never-created.mp4"))
    monkeypatch.setattr("app.api.routers.ai_jobs.store", store)

    with pytest.raises(HTTPException) as exc:
        accept_ai_job(job.id)
    assert exc.value.status_code == 409
    assert store.get(job.id).status == JobStatus.REVIEW
    assert "asset_id" not in store.get(job.id).metadata


def test_accept_uses_ffprobe_duration_and_dims(tmp_path, monkeypatch):
    """Accept must ensure asset has probed duration/dimensions, not hardcoded."""
    from app.api.routers.ai_jobs import accept_ai_job
    from app.services import studio

    output = tmp_path / "probed.mp4"
    output.write_bytes(b"fake-mp4")

    store = _store()
    pid = uuid4()
    job = store.create(pid, "scene", "probe me")
    store.update_status(job.id, JobStatus.REVIEW, stages=["review"])
    store.merge_meta(job.id, "output_path", str(output))

    monkeypatch.setattr("app.api.routers.ai_jobs.store", store)
    monkeypatch.setattr("app.api.routers.ai_jobs.threading.Thread", _NoThread)
    monkeypatch.setattr(
        "app.api.routers.ai_jobs.ffmpeg_util.detect_format",
        lambda _path: {
            "ok": True,
            "duration_seconds": 3.5,
            "video": {"width": 1280, "height": 720},
        },
    )

    accept_ai_job(job.id)

    asset = studio.list_assets(pid)[0]
    assert asset["duration_ms"] == 3500
    assert asset["meta_jsonb"]["width"] == 1280
    assert asset["meta_jsonb"]["height"] == 720


def test_accept_rejects_when_ffprobe_unavailable(tmp_path, monkeypatch):
    """If ffprobe fails, accept must return error 409."""
    from fastapi import HTTPException
    from app.api.routers.ai_jobs import accept_ai_job
    from app.services import studio

    output = tmp_path / "unprobed.mp4"
    output.write_bytes(b"fake-mp4")

    store = _store()
    pid = uuid4()
    job = store.create(pid, "scene", "no probe")
    store.update_status(job.id, JobStatus.REVIEW, stages=["review"])
    store.merge_meta(job.id, "output_path", str(output))

    monkeypatch.setattr("app.api.routers.ai_jobs.store", store)
    monkeypatch.setattr("app.api.routers.ai_jobs.threading.Thread", _NoThread)
    monkeypatch.setattr(
        "app.api.routers.ai_jobs.ffmpeg_util.detect_format",
        lambda _path: {"ok": False, "error": "ffprobe not found on PATH"},
    )

    with pytest.raises(HTTPException) as exc:
        accept_ai_job(job.id)

    assert exc.value.status_code == 409
    assert store.get(job.id).status == JobStatus.REVIEW
    assert "asset_id" not in store.get(job.id).metadata
    assert studio.list_assets(pid) == []
