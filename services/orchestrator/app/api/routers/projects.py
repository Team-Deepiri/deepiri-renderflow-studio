from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app import memory_store
from app.api.schemas.studio import ProjectCreate
from app.api.utils import (
    PaginationParams,
    PaginatedResponse,
    FilterParams,
    BatchOperationRequest,
    BatchOperationResponse,
    paginate,
    apply_filters,
)
from app.services import studio

router = APIRouter()


@router.post("/v1/projects", tags=["projects"])
def create_project(body: ProjectCreate) -> dict[str, Any]:
    studio.bootstrap()
    oid = body.owner_id or memory_store.DEMO_OWNER
    return studio.create_project(oid, body.name, body.fps_num, body.fps_den, body.sample_rate)


@router.get("/v1/projects", tags=["projects"])
def list_projects(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    owner_id: UUID | None = None,
    search: str | None = Query(None, description="Search projects by name"),
    sort_by: str | None = Query(None, description="Sort field"),
    sort_order: str = Query("asc", regex="^(asc|desc)$", description="Sort direction"),
) -> PaginatedResponse[dict[str, Any]]:
    studio.bootstrap()
    projects = studio.list_projects(owner_id)
    projects = apply_filters(
        projects,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    items, total = paginate(projects, page, page_size)
    return PaginatedResponse.create(items, total, page, page_size)


@router.get("/v1/projects/{project_id}", tags=["projects"])
def get_project(project_id: UUID) -> dict[str, Any]:
    row = studio.get_project(project_id)
    if not row:
        raise HTTPException(404, "project not found")
    return row


@router.patch("/v1/projects/{project_id}", tags=["projects"])
def update_project(project_id: UUID, name: str | None = None, fps_num: int | None = None, fps_den: int | None = None) -> dict[str, Any]:
    row = studio.update_project(project_id, name, fps_num, fps_den)
    if not row:
        raise HTTPException(404, "project not found")
    return row


@router.delete("/v1/projects/{project_id}", tags=["projects"])
def delete_project(project_id: UUID) -> dict[str, str]:
    studio.delete_project(project_id)
    return {"status": "deleted"}


@router.post("/v1/projects/batch", tags=["projects"])
def batch_projects(req: BatchOperationRequest) -> BatchOperationResponse:
    studio.bootstrap()
    succeeded = []
    failed = {}
    
    for pid in req.ids:
        try:
            uuid = UUID(pid)
            if req.action == "delete":
                studio.delete_project(uuid)
                succeeded.append(pid)
            elif req.action == "archive":
                succeeded.append(pid)
            else:
                failed[pid] = f"unknown action: {req.action}"
        except Exception as e:
            failed[pid] = str(e)
    
    return BatchOperationResponse(
        succeeded=succeeded,
        failed=failed,
        total=len(req.ids),
    )
