"""HTTP route modules; aggregate via `studio_router` for FastAPI."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import ai_jobs, assets_media, audio_tts, capabilities, media_generation, projects, render_jobs, rfir_preview, scenes, timeline

studio_router = APIRouter()
for _mod in (
    capabilities,
    ai_jobs,
    projects,
    assets_media,
    timeline,
    scenes,
    render_jobs,
    audio_tts,
    media_generation,
    rfir_preview,
):
    studio_router.include_router(_mod.router)

__all__ = ["studio_router"]
