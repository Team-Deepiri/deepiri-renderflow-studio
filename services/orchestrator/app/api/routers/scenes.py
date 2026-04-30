from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.api.schemas.studio import SceneCreate, SceneNodeCreate
from app.services import studio

router = APIRouter()


@router.post("/v1/projects/{project_id}/scenes", tags=["scenes"])
def create_scene_route(project_id: UUID, body: SceneCreate) -> dict[str, Any]:
    return studio.create_scene(project_id, body.name, body.unit_scale, body.up_axis)


@router.get("/v1/projects/{project_id}/scenes", tags=["scenes"])
def list_scenes(project_id: UUID) -> list[dict[str, Any]]:
    return studio.list_scenes(project_id)


@router.post("/v1/scenes/{scene_id}/nodes", tags=["scenes"])
def create_scene_node(scene_id: UUID, body: SceneNodeCreate) -> dict[str, Any]:
    return studio.create_scene_node(
        scene_id, body.parent_id, body.node_type, body.transform, body.payload
    )


@router.get("/v1/scenes/{scene_id}/nodes", tags=["scenes"])
def list_nodes(scene_id: UUID) -> list[dict[str, Any]]:
    return studio.list_scene_nodes(scene_id)
