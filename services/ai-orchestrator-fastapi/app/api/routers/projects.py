from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app import memory_store
from app.api.schemas.studio import ProjectCreate
from app.services import studio

router = APIRouter()


@router.post("/v1/projects", tags=["projects"])
def create_project(body: ProjectCreate) -> dict[str, Any]:
    studio.bootstrap()
    oid = body.owner_id or memory_store.DEMO_OWNER
    return studio.create_project(oid, body.name, body.fps_num, body.fps_den, body.sample_rate)


@router.get("/v1/projects", tags=["projects"])
def list_projects(owner_id: UUID | None = None) -> list[dict[str, Any]]:
    studio.bootstrap()
    return studio.list_projects(owner_id)


@router.get("/v1/projects/{project_id}", tags=["projects"])
def get_project(project_id: UUID) -> dict[str, Any]:
    row = studio.get_project(project_id)
    if not row:
        raise HTTPException(404, "project not found")
    return row
