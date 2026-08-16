from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.schemas.studio import (
    ClipCreate,
    ClipEffectCreate,
    ClipUpsert,
    SequenceCreate,
    TrackCreate,
)
from app.services import studio

router = APIRouter()


@router.post("/v1/projects/{project_id}/sequences", tags=["timeline"])
def create_sequence(project_id: UUID, body: SequenceCreate) -> dict[str, Any]:
    if not studio.get_project(project_id):
        raise HTTPException(404, "project not found")
    return studio.create_sequence(
        project_id, body.name, body.resolution_w, body.resolution_h, body.start_tc
    )


@router.get("/v1/projects/{project_id}/sequences", tags=["timeline"])
def list_sequences(project_id: UUID) -> list[dict[str, Any]]:
    return studio.list_sequences(project_id)


@router.get("/v1/sequences/{sequence_id}", tags=["timeline"])
def get_sequence(sequence_id: UUID) -> dict[str, Any]:
    row = studio.get_sequence(sequence_id)
    if not row:
        raise HTTPException(404, "sequence not found")
    return row


@router.post("/v1/sequences/{sequence_id}/tracks", tags=["timeline"])
def create_track(sequence_id: UUID, body: TrackCreate) -> dict[str, Any]:
    return studio.create_track(sequence_id, body.track_type, body.lane_index, body.name)


@router.get("/v1/sequences/{sequence_id}/tracks", tags=["timeline"])
def list_tracks(sequence_id: UUID) -> list[dict[str, Any]]:
    return studio.list_tracks(sequence_id)


@router.delete("/v1/sequences/{sequence_id}/tracks/{track_id}", tags=["timeline"])
def delete_track(sequence_id: UUID, track_id: UUID) -> dict[str, str]:
    found = studio.delete_track(track_id)
    if not found:
        raise HTTPException(404, "track not found")
    return {"status": "deleted", "track_id": str(track_id)}


@router.post("/v1/sequences/{sequence_id}/clips", tags=["timeline"])
def create_clip(sequence_id: UUID, body: ClipCreate) -> dict[str, Any]:
    return studio.create_clip(
        body.track_id,
        body.asset_id,
        body.in_tick,
        body.out_tick,
        body.src_in_tick,
        body.speed_ratio,
        body.transform,
    )


@router.put("/v1/sequences/{sequence_id}/clips", tags=["timeline"])
def replace_clips(sequence_id: UUID, body: list[ClipUpsert]) -> list[dict[str, Any]]:
    """Atomic replace: `body` becomes the sequence's complete clip list.

    Rows are matched by the client-minted clip id, so a save updates existing
    clips instead of recreating them and any clip_effects survive. Clips
    naming a track outside this sequence are dropped.
    """
    if not studio.get_sequence(sequence_id):
        raise HTTPException(404, "sequence not found")
    return studio.replace_clips_for_sequence(
        sequence_id, [c.model_dump() for c in body]
    )


@router.get("/v1/sequences/{sequence_id}/clips", tags=["timeline"])
def list_clips(sequence_id: UUID) -> list[dict[str, Any]]:
    return studio.list_clips_for_sequence(sequence_id)


@router.post("/v1/clips/{clip_id}/effects", tags=["timeline"])
def create_clip_effect(clip_id: UUID, body: ClipEffectCreate) -> dict[str, Any]:
    return studio.add_clip_effect(clip_id, body.effect_type, body.order_idx, body.params)


@router.get("/v1/clips/{clip_id}/effects", tags=["timeline"])
def list_effects(clip_id: UUID) -> list[dict[str, Any]]:
    return studio.list_clip_effects(clip_id)
