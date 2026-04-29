"""
Vendored from: deepiri-platform/platform-services/shared/deepiri-synapse/.../contracts/events.py
Adapted for: Renderflow AI and render event contracts.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, Literal

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    event: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] | None = None


class RenderEvent(BaseEvent):
    event: Literal["render"]
    project_id: str
    sequence_id: str
    status: str


class AiStageEvent(BaseEvent):
    event: Literal["ai-stage"]
    job_id: str
    stage: str
    status: str
