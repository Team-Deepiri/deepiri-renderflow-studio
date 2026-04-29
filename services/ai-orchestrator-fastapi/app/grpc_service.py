from __future__ import annotations

import logging
import sys
from concurrent import futures
from pathlib import Path
from uuid import UUID

import grpc

logger = logging.getLogger(__name__)

_GEN = Path(__file__).resolve().parent / "gen"
if str(_GEN) not in sys.path:
    sys.path.insert(0, str(_GEN))

import renderflow_pb2  # noqa: E402
import renderflow_pb2_grpc  # noqa: E402

from app import memory_store  # noqa: E402
from app.job_store import store  # noqa: E402
from app.runtime_state import get_settings  # noqa: E402
from app.services import studio  # noqa: E402
from app.worker_loop import enqueue_job  # noqa: E402


class AiSessionServicer(renderflow_pb2_grpc.AiSessionServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def SubmitAiJob(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid project_id")
            return renderflow_pb2.SubmitAiJobResponse()
        job = store.create(pid, request.mode or "scene", request.prompt or "")
        enqueue_job(str(job.id), get_settings())
        return renderflow_pb2.SubmitAiJobResponse(job_id=str(job.id), status=job.status.value)

    def GetJobStatus(self, request, context):  # type: ignore[no-untyped-def]
        try:
            jid = UUID(request.job_id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid job_id")
            return renderflow_pb2.JobStatusResponse()
        rec = store.get(jid)
        if not rec:
            context.abort(grpc.StatusCode.NOT_FOUND, "job not found")
            return renderflow_pb2.JobStatusResponse()
        return renderflow_pb2.JobStatusResponse(
            job_id=str(rec.id),
            status=rec.status.value,
            stages=list(rec.stages),
        )


def _proj_msg(row: dict) -> renderflow_pb2.Project:
    return renderflow_pb2.Project(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]),
        name=str(row["name"]),
        fps_num=int(row.get("fps_num", 24)),
        fps_den=int(row.get("fps_den", 1)),
        sample_rate=int(row.get("sample_rate", 48_000)),
    )


class ProjectServicer(renderflow_pb2_grpc.ProjectServiceServicer):
    def Health(self, request, context):  # type: ignore[no-untyped-def]
        return renderflow_pb2.HealthResponse(status="ok")

    def CreateProject(self, request, context):  # type: ignore[no-untyped-def]
        studio.bootstrap()
        oid = UUID(request.owner_id) if request.owner_id else memory_store.DEMO_OWNER
        row = studio.create_project(
            oid,
            request.name or "Untitled",
            request.fps_num or 24,
            request.fps_den or 1,
            request.sample_rate or 48_000,
        )
        return _proj_msg(row)

    def GetProject(self, request, context):  # type: ignore[no-untyped-def]
        try:
            pid = UUID(request.project_id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid project_id")
            return renderflow_pb2.Project()
        row = studio.get_project(pid)
        if not row:
            context.abort(grpc.StatusCode.NOT_FOUND, "project not found")
            return renderflow_pb2.Project()
        return _proj_msg(row)

    def ListProjects(self, request, context):  # type: ignore[no-untyped-def]
        studio.bootstrap()
        oid = UUID(request.owner_id) if request.owner_id else None
        rows = studio.list_projects(oid)
        return renderflow_pb2.ListProjectsResponse(projects=[_proj_msg(r) for r in rows])


def start_grpc_server() -> grpc.Server:
    settings = get_settings()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    renderflow_pb2_grpc.add_AiSessionServiceServicer_to_server(AiSessionServicer(), server)
    renderflow_pb2_grpc.add_ProjectServiceServicer_to_server(ProjectServicer(), server)
    addr = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(addr)
    server.start()
    logger.info("gRPC AiSessionService listening on %s", addr)
    return server
