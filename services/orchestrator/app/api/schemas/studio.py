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


class PlanShotIn(BaseModel):
    """One shot from the worker's ShotList, as sent to the Layer 2 plan gate."""

    description: str
    duration_sec: float = 5.0
    tier: str = "B"


class PlanCheckRequest(BaseModel):
    job_id: str
    shots: list[PlanShotIn] = Field(default_factory=list)


class GuardrailSummary(BaseModel):
    verdict: str = "allow"
    warnings: list[str] = Field(default_factory=list)
    blocked_shots: list[int] = Field(default_factory=list)


class AiJobOut(BaseModel):
    id: UUID
    project_id: UUID
    mode: str
    prompt: str
    status: str
    stages: list[str]
    metadata: dict[str, Any]
    result_asset_id: str | None = None
    guardrail_summary: GuardrailSummary | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, r: AiJobRecord) -> AiJobOut:
        meta = dict(r.metadata)
        gs = None
        if "guardrail_verdict" in meta:
            gs = GuardrailSummary(
                verdict=meta.get("guardrail_verdict", "allow"),
                warnings=meta.get("guardrail_flags", []),
            )
        return cls(
            id=r.id,
            project_id=r.project_id,
            mode=r.mode,
            prompt=r.prompt,
            status=r.status.value,
            stages=list(r.stages),
            metadata=meta,
            result_asset_id=meta.get("asset_id"),
            guardrail_summary=gs,
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


class RenderJobOut(BaseModel):
    id: UUID
    project_id: UUID
    sequence_id: UUID | None = None
    preset: str
    status: str
    output_uri: str | None = None
    progress: float = 0.0
    error: str | None = None
    created_at: datetime | None = None
    ended_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RenderJobOut:
        metrics = row.get("metrics_jsonb") or {}
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            sequence_id=row.get("sequence_id"),
            preset=row.get("preset", "h264_1080p"),
            status=row.get("status", "queued"),
            output_uri=row.get("output_uri") or None,
            progress=float(metrics.get("progress", 0.0)),
            error=metrics.get("error"),
            created_at=row.get("created_at"),
            ended_at=row.get("ended_at"),
        )


class FrameBody(BaseModel):
    path: str
    time_seconds: float = 0.0
