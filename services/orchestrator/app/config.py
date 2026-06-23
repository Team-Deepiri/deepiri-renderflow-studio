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
    max_concurrent_jobs: int = 4
    job_timeout_minutes: int = 60
    enable_sse: bool = True
    readiness_mode: str = "dev"
    data_dir: str | None = None
    rfir_enabled: bool = False
    rfir_max_gpu_sec: int = 120
    rfir_max_tier: str = "C"
    rfir_gen_res: str = "512x288"
    rfir_models_dir: str | None = None


def load_settings() -> Settings:
    allowed = {"dev", "prod"}
    mode = os.environ.get("READINESS_MODE", "dev").strip().lower()
    if mode not in allowed:
        raise ValueError(f"Invalid READINESS_MODE={mode!r}. Allowed: {sorted(allowed)}")

    return Settings(
        http_host=os.environ.get("RENDERFLOW_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.environ.get("RENDERFLOW_HTTP_PORT", "8080")),
        grpc_host=os.environ.get("RENDERFLOW_GRPC_HOST", "0.0.0.0"),
        grpc_port=int(os.environ.get("RENDERFLOW_GRPC_PORT", "50051")),
        redis_url=os.environ.get("REDIS_URL"),
        database_url=os.environ.get("DATABASE_URL"),
        worker_poll_sec=float(os.environ.get("RENDERFLOW_WORKER_POLL_SEC", "0.25")),
        ai_stages_simulate_ms=int(os.environ.get("RENDERFLOW_AI_STAGE_MS", "50")),
        data_dir=os.environ.get("RENDERFLOW_DATA_DIR"),
        readiness_mode=mode,
        rfir_enabled=os.environ.get("RENDERFLOW_RFIR_ENABLED", "false").lower() == "true",
        rfir_max_gpu_sec=int(os.environ.get("RENDERFLOW_RFIR_MAX_GPU_SEC", "120")),
        rfir_max_tier=os.environ.get("RENDERFLOW_RFIR_MAX_TIER", "C"),
        rfir_gen_res=os.environ.get("RENDERFLOW_RFIR_GEN_RES", "512x288"),
        rfir_models_dir=os.environ.get("RENDERFLOW_MODELS_DIR"),
    )
