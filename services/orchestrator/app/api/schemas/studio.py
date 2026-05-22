from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.job_store import AiJobRecord


class AiJobCreate(BaseModel):
    project_id: UUID
    mode: str = Field(description="scene|audio|vfx|assist")
    prompt: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AiJobOut(BaseModel):
    id: UUID
    project_id: UUID
    mode: str
    prompt: str
    status: str
    stages: list[str]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, r: AiJobRecord) -> AiJobOut:
        return cls(
            id=r.id,
            project_id=r.project_id,
            mode=r.mode,
            prompt=r.prompt,
            status=r.status.value,
            stages=list(r.stages),
            metadata=dict(r.metadata),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )


class ProjectCreate(BaseModel):
    owner_id: UUID | None = None
    name: str = "Untitled"
    fps_num: int = 24
    fps_den: int = 1
    sample_rate: int = 48_000


class AssetCreate(BaseModel):
    kind: str
    uri: str
    sha256: str = "pending"
    duration_ms: int | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ProbeBody(BaseModel):
    path: str


class AssetImportBody(BaseModel):
    path: str


class SequenceCreate(BaseModel):
    name: str = "Sequence 1"
    resolution_w: int = 1920
    resolution_h: int = 1080
    start_tc: str = "00:00:00:00"


class TrackCreate(BaseModel):
    track_type: str = "video"
    lane_index: int = 0
    name: str = "V1"


class ClipCreate(BaseModel):
    track_id: UUID
    asset_id: UUID
    in_tick: int
    out_tick: int
    src_in_tick: int = 0
    speed_ratio: float = 1.0
    transform: dict[str, Any] = Field(default_factory=dict)


class ClipEffectCreate(BaseModel):
    effect_type: str
    order_idx: int = 0
    params: dict[str, Any] = Field(default_factory=dict)


class SceneCreate(BaseModel):
    name: str = "Scene"
    unit_scale: float = 1.0
    up_axis: str = "Y"


class SceneNodeCreate(BaseModel):
    parent_id: UUID | None = None
    node_type: str = "group"
    transform: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class RenderSubmit(BaseModel):
    sequence_id: UUID | None = None
    preset: str = "h264_1080p"
