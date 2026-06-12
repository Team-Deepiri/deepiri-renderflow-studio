from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.schemas.studio import RenderJobOut, RenderSubmit
from app.services import studio

router = APIRouter()


@router.post("/v1/projects/{project_id}/render-jobs", response_model=RenderJobOut, tags=["render"])
def submit_render(project_id: UUID, body: RenderSubmit) -> RenderJobOut:
    row = studio.submit_render_job(project_id, body.sequence_id, body.preset)
    return RenderJobOut.from_row(row)


@router.get("/v1/projects/{project_id}/render-jobs", response_model=list[RenderJobOut], tags=["render"])
def list_renders(project_id: UUID) -> list[RenderJobOut]:
    return [RenderJobOut.from_row(r) for r in studio.list_render_jobs(project_id)]


@router.get("/v1/render-jobs/{job_id}", response_model=RenderJobOut, tags=["render"])
def get_render(job_id: UUID) -> RenderJobOut:
    row = studio.get_render_job(job_id)
    if not row:
        raise HTTPException(404, "render job not found")
    return RenderJobOut.from_row(row)
