from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.api.schemas.studio import RenderSubmit
from app.services import studio

router = APIRouter()


@router.post("/v1/projects/{project_id}/render-jobs", tags=["render"])
def submit_render(project_id: UUID, body: RenderSubmit) -> dict[str, Any]:
    return studio.submit_render_job(project_id, body.sequence_id, body.preset)


@router.get("/v1/projects/{project_id}/render-jobs", tags=["render"])
def list_renders(project_id: UUID) -> list[dict[str, Any]]:
    return studio.list_render_jobs(project_id)
