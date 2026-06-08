"""Unit tests for the render/export job pipeline."""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.api.schemas.studio import RenderJobOut
from app.api.utils import EventEmitter
from app.config import Settings
from app.memory_store import DEMO_OWNER, ensure_demo_user
from app.services import studio

FAST = Settings()


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Disable Postgres calls so tests run without a real database."""
    import app.db as db_mod
    import app.db_repos as db_repos_mod

    monkeypatch.setattr(db_mod, "pool_ready", lambda: False)
    monkeypatch.setattr(db_repos_mod, "insert_render_job", lambda *a, **kw: None)
    monkeypatch.setattr(db_repos_mod, "insert_project", lambda *a, **kw: None)
    monkeypatch.setattr(db_repos_mod, "insert_sequence", lambda *a, **kw: None)
    monkeypatch.setattr(db_repos_mod, "insert_track", lambda *a, **kw: None)
    monkeypatch.setattr(db_repos_mod, "insert_clip", lambda *a, **kw: None)
    monkeypatch.setattr(db_repos_mod, "insert_asset", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _no_enqueue(monkeypatch):
    monkeypatch.setattr("app.render_worker.enqueue_render_job", lambda _jid: None)


def _seed_timeline_with_clip(source_path: str) -> tuple:
    ensure_demo_user()
    project = studio.create_project(DEMO_OWNER, "Render Test")
    sequence = studio.create_sequence(project["id"], "Seq 1")
    track = studio.create_track(sequence["id"], "video", 0, "V1")
    asset = studio.create_asset(
        project["id"],
        "video",
        source_path,
        meta={"proxy_status": "ready", "proxy_path": source_path},
    )
    studio.create_clip(track["id"], asset["id"], 0, 120)
    return project, sequence


def test_submit_render_job_queued():
    ensure_demo_user()
    project = studio.create_project(DEMO_OWNER, "Submit Test")
    sequence = studio.create_sequence(project["id"], "Seq 1")

    job = studio.submit_render_job(project["id"], sequence["id"], "h264_1080p")

    assert job["status"] == "queued"
    listed = studio.list_render_jobs(project["id"])
    assert any(r["id"] == job["id"] for r in listed)


def test_render_job_out_from_row():
    ensure_demo_user()
    project = studio.create_project(DEMO_OWNER, "Schema Test")
    sequence = studio.create_sequence(project["id"], "Seq 1")
    job = studio.submit_render_job(project["id"], sequence["id"], "h264_1080p")

    out = RenderJobOut.from_row(job)
    assert out.id == job["id"]
    assert out.status == "queued"
    assert out.progress == 0.0


def test_empty_sequence_produces_placeholder(tmp_path):
    from app.render_worker import _process_render_job

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")

    ensure_demo_user()
    project = studio.create_project(DEMO_OWNER, "Empty Seq")
    sequence = studio.create_sequence(project["id"], "Seq 1")
    job = studio.submit_render_job(project["id"], sequence["id"], "h264_1080p")

    with patch("app.render_worker.data_subdir", lambda *a, **k: tmp_path):
        _process_render_job(str(job["id"]), FAST)

    final = studio.get_render_job(job["id"])
    assert final is not None
    assert final["status"] == "completed"
    assert final["output_uri"]
    assert Path(final["output_uri"]).exists()


def test_render_job_with_clip_completes(tmp_path):
    from app.render_worker import _process_render_job

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")

    fixture = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "ai_outputs"
        / "0693a56e-192d-4f61-822c-148a2893a43e"
        / "scene.mp4"
    )
    if not fixture.exists():
        pytest.skip("fixture video not available")

    project, sequence = _seed_timeline_with_clip(str(fixture))
    job = studio.submit_render_job(project["id"], sequence["id"], "h264_1080p")

    with patch("app.render_worker.data_subdir", lambda *a, **k: tmp_path):
        _process_render_job(str(job["id"]), FAST)

    final = studio.get_render_job(job["id"])
    assert final is not None
    assert final["status"] == "completed"
    assert final["output_uri"]
    assert Path(final["output_uri"]).exists()
    metrics = final.get("metrics_jsonb") or {}
    assert metrics.get("progress") == 1.0


def test_render_job_fails_without_sequence_id():
    from app.render_worker import _process_render_job

    ensure_demo_user()
    project = studio.create_project(DEMO_OWNER, "No Seq")
    job = studio.submit_render_job(project["id"], None, "h264_1080p")

    _process_render_job(str(job["id"]), FAST)

    final = studio.get_render_job(job["id"])
    assert final is not None
    assert final["status"] == "failed"
    assert (final.get("metrics_jsonb") or {}).get("error") == "sequence_id required"


def test_render_emits_events():
    from app.render_worker import _process_render_job

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")

    ensure_demo_user()
    project = studio.create_project(DEMO_OWNER, "Events")
    sequence = studio.create_sequence(project["id"], "Seq 1")
    job = studio.submit_render_job(project["id"], sequence["id"], "h264_1080p")

    emitted: list[dict] = []
    emitter = EventEmitter()
    emitter.subscribe("render_update", emitted.append)

    with patch("app.render_worker.get_event_emitter", return_value=emitter):
        _process_render_job(str(job["id"]), FAST)

    statuses = {e["status"] for e in emitted if e.get("job_id") == str(job["id"])}
    assert "rendering" in statuses
    assert "completed" in statuses


def test_get_render_endpoint():
    from app.api.routers.render_jobs import get_render

    ensure_demo_user()
    project = studio.create_project(DEMO_OWNER, "HTTP Test")
    sequence = studio.create_sequence(project["id"], "Seq 1")
    job = studio.submit_render_job(project["id"], sequence["id"], "h264_1080p")

    out = get_render(job["id"])
    assert out.id == job["id"]
    assert out.status == "queued"
    assert out.progress == 0.0
