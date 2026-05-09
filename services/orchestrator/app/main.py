from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI
from fastapi.responses import JSONResponse

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

def readiness_check_redis(redis_url: str | None) -> dict[str, object]:
    if not redis_url:
        return {
            "status": "disabled",
            "configured": False,
            "detail": "REDIS_URL not set",
        }
    
    try:
        import redis

        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        return {
            "status": "ok",
            "configured": True,
            "detail": "Redis reachable",
        }
    except Exception as e:
        return {
            "status": "degraded",
            "configured": True,
            "detail": f"Failed to reach redis with message: {e}; using in-process queue fallback",
        }


def evaluate_readiness(mode: str, dependencies: dict[str, dict[str, object]]) -> tuple[bool, int, str]:
    statuses = {dep["status"] for dep in dependencies.values()}

    # dev mode
    if mode == "dev":
        is_ready = "failed" not in statuses
    # production mode
    else:
        is_ready = all(s == "ok" for s in statuses)

    if is_ready:
        return True, 200, "ready"
    return False, 503, "not_ready"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/ready")
def ready() -> dict[str, object]:
    settings = load_settings()
    deps = {
        "postgres": db.readiness_check(),
        "redis": readiness_check_redis(settings.redis_url),
    }

    _is_ready, status_code, overall_status = evaluate_readiness(settings.readiness_mode, deps)

    body = {
        "status": overall_status,
        "mode": settings.readiness_mode,
        "dependencies": deps,
    }

    return JSONResponse(status_code=status_code, content=body)
