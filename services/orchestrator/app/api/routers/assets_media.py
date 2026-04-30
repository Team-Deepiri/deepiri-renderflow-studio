from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.schemas.studio import AssetCreate, ProbeBody
from app.media import ffmpeg as ffmpeg_util
from app.services import studio

router = APIRouter()


@router.post("/v1/projects/{project_id}/assets", tags=["assets"])
def create_asset(project_id: UUID, body: AssetCreate) -> dict[str, Any]:
    if not studio.get_project(project_id):
        raise HTTPException(404, "project not found")
    return studio.create_asset(
        project_id, body.kind, body.uri, body.sha256, body.duration_ms, body.meta
    )


@router.get("/v1/projects/{project_id}/assets", tags=["assets"])
def list_assets(project_id: UUID) -> list[dict[str, Any]]:
    return studio.list_assets(project_id)


@router.post("/v1/media/probe", tags=["media"])
def media_probe(body: ProbeBody) -> dict[str, Any]:
    return ffmpeg_util.probe(body.path)
