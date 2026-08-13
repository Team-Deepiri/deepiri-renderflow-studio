"""Deleting a project has to actually delete it.

The home page's Delete button calls DELETE /v1/projects/{id}. If that route
raises, the UI silently leaves the card on screen, so the button looks dead.
These tests pin the route's contract: it succeeds, and the project is gone
from the list afterwards.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create_project(name: str = "Doomed") -> str:
    res = client.post("/v1/projects", json={"name": name, "fps_num": 24, "fps_den": 1})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _list_project_ids() -> list[str]:
    res = client.get("/v1/projects", params={"page": 1, "page_size": 100})
    assert res.status_code == 200, res.text
    return [p["id"] for p in res.json()["items"]]


def test_delete_project_succeeds():
    project_id = _create_project()

    res = client.delete(f"/v1/projects/{project_id}")

    assert res.status_code == 200, res.text
    assert res.json() == {"status": "deleted"}


def test_deleted_project_disappears_from_the_list():
    project_id = _create_project()
    assert project_id in _list_project_ids()

    client.delete(f"/v1/projects/{project_id}")

    assert project_id not in _list_project_ids()


def test_deleting_the_last_project_leaves_the_list_empty():
    """The list falls back to Postgres when memory is empty, so a delete that
    only clears memory would resurrect the project here."""
    for pid in _list_project_ids():
        client.delete(f"/v1/projects/{pid}")

    assert _list_project_ids() == []
