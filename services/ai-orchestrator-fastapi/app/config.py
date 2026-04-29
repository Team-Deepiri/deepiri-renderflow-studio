from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50051
    redis_url: str | None = os.environ.get("REDIS_URL")
    database_url: str | None = os.environ.get("DATABASE_URL")
    worker_poll_sec: float = 0.25
    ai_stages_simulate_ms: int = 50


def load_settings() -> Settings:
    return Settings(
        http_host=os.environ.get("RENDERFLOW_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("RENDERFLOW_HTTP_PORT", "8080")),
        grpc_host=os.environ.get("RENDERFLOW_GRPC_HOST", "0.0.0.0"),
        grpc_port=int(os.environ.get("RENDERFLOW_GRPC_PORT", "50051")),
        redis_url=os.environ.get("REDIS_URL"),
        database_url=os.environ.get("DATABASE_URL"),
        worker_poll_sec=float(os.environ.get("RENDERFLOW_WORKER_POLL_SEC", "0.25")),
        ai_stages_simulate_ms=int(os.environ.get("RENDERFLOW_AI_STAGE_MS", "50")),
    )
