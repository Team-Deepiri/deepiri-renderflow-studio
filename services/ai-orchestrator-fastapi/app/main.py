from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI

from app import db
from app.api import studio_router
from app.config import load_settings
from app.grpc_service import start_grpc_server
from app.runtime_state import set_settings
from app.services.studio import bootstrap
from app.worker_loop import start_worker, stop_worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_grpc_server: grpc.Server | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _grpc_server
    settings = load_settings()
    set_settings(settings)
    db.init_db(settings.database_url)
    bootstrap()
    start_worker(settings)
    _grpc_server = start_grpc_server()
    yield
    stop_worker()
    if _grpc_server:
        _grpc_server.stop(grace=2.0)


app = FastAPI(
    title="Deepiri Renderflow Studio API",
    version="0.3.0",
    lifespan=lifespan,
    description="HTTP + gRPC orchestrator, timeline, scenes, render jobs, AI pipeline.",
)

app.include_router(studio_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
