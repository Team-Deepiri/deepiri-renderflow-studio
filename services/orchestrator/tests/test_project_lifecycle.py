"""Project delete/update lifecycle and the memory-store → Postgres fallback.

The conftest `_no_db` fixture pins `pool_ready()` to False, so the db_repos
calls here no-op; the SQL added for (1) needs a live Postgres to exercise.
"""
from __future__ import annotations

import pytest

from app import db_repos, memory_store
from app.api.routers import projects as projects_router
from app.api.utils import BatchOperationRequest
from app.services import studio


@pytest.fixture
def project():
    """A project with a sequence, track, clip and asset hanging off it."""
    proj = studio.create_project(memory_store.DEMO_OWNER, "Lifecycle Test")
    seq = studio.create_sequence(proj["id"], "Main Sequence")
    track = studio.create_track(seq["id"], "video", 0, "V1")
    asset = studio.create_asset(proj["id"], "video", "/tmp/clip.mp4")
    clip = studio.create_clip(track["id"], asset["id"], 0, 480)
    return {
        "project": proj,
        "sequence": seq,
        "track": track,
        "asset": asset,
        "clip": clip,
    }


# ── 1. the routes no longer crash ──


def test_delete_project_route_succeeds(project):
    """Regression: this raised AttributeError on db_repos.delete_project."""
    result = projects_router.delete_project(project["project"]["id"])

    assert result == {"status": "deleted"}
    assert studio.get_project(project["project"]["id"]) is None


def test_update_project_route_returns_updated_row(project):
    """Regression: this raised AttributeError on db_repos.update_project."""
    row = projects_router.update_project(
        project["project"]["id"], name="Renamed", fps_num=30, fps_den=1
    )

    assert row["name"] == "Renamed"
    assert row["fps_num"] == 30


def test_batch_delete_reports_success(project):
    """The batch route caught the AttributeError and reported a false failure."""
    pid = str(project["project"]["id"])

    resp = projects_router.batch_projects(
        BatchOperationRequest(ids=[pid], action="delete")
    )

    assert resp.succeeded == [pid]
    assert resp.failed == {}


# ── 2. delete cascades through the memory store ──


def test_delete_project_cascades_to_children(project):
    studio.delete_project(project["project"]["id"])

    assert project["sequence"]["id"] not in memory_store._sequences
    assert project["track"]["id"] not in memory_store._tracks
    assert project["clip"]["id"] not in memory_store._clips
    assert project["asset"]["id"] not in memory_store._assets


def test_deleted_project_sequence_is_no_longer_readable(project):
    """The sequence-scoped routes address rows by sequence id and never check
    the project, so an uncascaded delete left a writable orphan timeline."""
    seq_id = project["sequence"]["id"]
    assert studio.list_clips_for_sequence(seq_id)  # sanity: populated first

    studio.delete_project(project["project"]["id"])

    assert studio.get_sequence(seq_id) is None
    assert studio.list_clips_for_sequence(seq_id) == []
    assert studio.list_tracks(seq_id) == []


def test_delete_project_leaves_other_projects_intact(project):
    other = studio.create_project(memory_store.DEMO_OWNER, "Untouched")
    other_seq = studio.create_sequence(other["id"], "Main Sequence")

    studio.delete_project(project["project"]["id"])

    assert studio.get_project(other["id"]) is not None
    assert studio.get_sequence(other_seq["id"]) is not None


def test_delete_track_cascades_to_its_clips(project):
    clip_id = project["clip"]["id"]

    assert studio.delete_track(project["track"]["id"]) is True

    assert clip_id not in memory_store._clips
    assert studio.list_clips_for_sequence(project["sequence"]["id"]) == []


# ── 3. delete stops the project's AI jobs and reclaims its files ──


def test_delete_project_cancels_its_jobs(project):
    from app.job_store import JobStatus, store

    job = store.create(project["project"]["id"], "scene", "sunset beach")
    assert job.status is JobStatus.QUEUED

    studio.delete_project(project["project"]["id"])

    assert store.get(job.id).status is JobStatus.CANCELLED


def test_accept_refuses_a_job_whose_project_is_gone(project, tmp_path):
    """The one guard that has to hold: no orphan asset, ever."""
    from fastapi import HTTPException

    from app.api.routers.ai_jobs import accept_ai_job
    from app.job_store import JobStatus, store

    output = tmp_path / "scene.mp4"
    output.write_bytes(b"\x00")
    pid = project["project"]["id"]
    job = store.create(pid, "scene", "sunset beach")
    store.update_status(job.id, JobStatus.REVIEW, stages=["review"])
    store.merge_meta(job.id, "output_path", str(output))

    studio.delete_project(pid)

    with pytest.raises(HTTPException) as excinfo:
        accept_ai_job(job.id)
    assert excinfo.value.status_code == 409
    assert studio.list_assets(pid) == []


def test_delete_project_removes_generated_files(project, tmp_path, monkeypatch):
    from app.job_store import store

    monkeypatch.setenv("RENDERFLOW_DATA_DIR", str(tmp_path))
    pid = project["project"]["id"]

    job = store.create(pid, "scene", "sunset beach")
    out_dir = tmp_path / "render_outputs" / str(job.id)
    out_dir.mkdir(parents=True)
    generated = out_dir / "scene.mp4"
    generated.write_bytes(b"\x00")

    proxy = tmp_path / "proxies" / "clip_proxy.mp4"
    proxy.parent.mkdir(parents=True)
    proxy.write_bytes(b"\x00")
    studio.create_asset(
        pid, "video", str(generated), meta={"proxy_path": str(proxy)}
    )

    studio.delete_project(pid)

    assert not generated.exists()
    assert not out_dir.exists()
    assert not proxy.exists()


def test_delete_project_never_touches_imported_source_media(
    project, tmp_path, monkeypatch
):
    """Imported assets point at the user's own footage, outside the data dir.
    Deleting a project must not delete the file they imported from."""
    monkeypatch.setenv("RENDERFLOW_DATA_DIR", str(tmp_path / "data"))

    source = tmp_path / "Movies" / "holiday.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"\x00")
    pid = project["project"]["id"]
    studio.create_asset(pid, "video", str(source))

    studio.delete_project(pid)

    assert source.exists()


# ── 4. empty is not the same as absent ──


@pytest.fixture
def db_must_not_be_called(monkeypatch):
    """Make every fallback read explode, so reaching one fails the test."""

    def _boom(*args, **kwargs):
        raise AssertionError("fell through to db_repos for a known project")

    for name in (
        "list_assets",
        "list_sequences",
        "list_tracks",
        "list_clips_for_sequence",
    ):
        monkeypatch.setattr(db_repos, name, _boom)


def test_known_project_with_no_children_returns_empty(db_must_not_be_called):
    proj = studio.create_project(memory_store.DEMO_OWNER, "Empty")
    seq = studio.create_sequence(proj["id"], "Main Sequence")

    assert studio.list_assets(proj["id"]) == []
    assert studio.list_tracks(seq["id"]) == []
    assert studio.list_clips_for_sequence(seq["id"]) == []


def test_emptied_timeline_reads_back_empty(project, db_must_not_be_called):
    """PUT [] must not resurrect the old clips from the mirror."""
    seq_id = project["sequence"]["id"]

    studio.replace_clips_for_sequence(seq_id, [])

    assert studio.list_clips_for_sequence(seq_id) == []


def test_rows_without_a_known_parent_are_still_returned(db_must_not_be_called):
    """`asset_create` doesn't require the project to exist — an AI job can mint
    an asset for a project the memory store never saw. Those rows must stay
    visible rather than being hidden by the parent guard."""
    from uuid import uuid4

    orphan_project = uuid4()
    memory_store.asset_create(orphan_project, "video", "/tmp/ai.mp4")

    assert len(studio.list_assets(orphan_project)) == 1


def test_unknown_ids_still_consult_the_mirror(monkeypatch):
    """The fallback is intact for rows the memory store has never seen."""
    from uuid import uuid4

    called: list[str] = []
    monkeypatch.setattr(
        db_repos, "list_clips_for_sequence", lambda sid: called.append("hit") or []
    )

    assert studio.list_clips_for_sequence(uuid4()) == []
    assert called == ["hit"]
