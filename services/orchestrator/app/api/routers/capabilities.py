"""Orchestrator capability introspection (GPU via installed deepiri-gpu-utils)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.utils import EventEmitter, get_event_emitter

try:
    from deepiri_gpu_utils.detect import detect as detect_gpu
except ModuleNotFoundError:
    detect_gpu = None

router = APIRouter(tags=["system"])


def _gpu_capabilities() -> dict[str, Any]:
    if detect_gpu is None:
        return {
            "backend": "unavailable",
            "confidence": 0.0,
            "details": {"reason": "deepiri_gpu_utils is not installed"},
            "warnings": ["GPU detection dependency is unavailable in this environment."],
        }

    r = detect_gpu()
    return {
        "backend": r.backend,
        "confidence": r.confidence,
        "details": r.details,
        "warnings": r.warnings,
    }


@router.get("/v1/capabilities")
def get_capabilities() -> dict[str, Any]:
    return {
        "gpu": _gpu_capabilities(),
        "service": "deepiri-renderflow-orchestrator",
    }


async def _sse_stream():
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    emitter = get_event_emitter()
    loop = asyncio.get_running_loop()

    def listener(data: dict[str, Any]) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, data)
        except Exception:
            pass

    event_types = ("job_update", "render_update", "project_update")
    for et in event_types:
        emitter.subscribe(et, listener)

    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {data!s}\n\n".encode()
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
    finally:
        for et in event_types:
            emitter.unsubscribe(et, listener)


@router.get("/v1/events")
def events_stream():
    return StreamingResponse(_sse_stream())


@router.post("/v1/events/test")
def emit_test_event(event_type: str = "job_update", job_id: UUID | None = None):
    emitter = get_event_emitter()
    emitter.emit(event_type, {"job_id": str(job_id) if job_id else "test", "status": "test"})
    return {"status": "emitted", "event_type": event_type}
