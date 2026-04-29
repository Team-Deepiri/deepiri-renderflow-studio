from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any


@dataclass
class StageResult:
    stage: str
    status: str
    payload: dict[str, Any]


def run_scene_stages(prompt: str) -> list[StageResult]:
    """Mirrors model-workers scene pipeline; expand with real PyTorch later."""
    now = datetime.now(UTC).isoformat()
    return [
        StageResult("preparing", "ok", {"prompt": prompt}),
        StageResult("storyboard", "ok", {"prompt": prompt, "created_at": now}),
        StageResult("layout", "ok", {"shots": 4}),
        StageResult("assets", "ok", {"generated_assets": 6}),
        StageResult("review", "ok", {"ready": True}),
    ]


def run_audio_stages(prompt: str) -> list[StageResult]:
    now = datetime.now(UTC).isoformat()
    return [
        StageResult("preparing", "ok", {"prompt": prompt}),
        StageResult("voice_cast", "ok", {"voices": 2}),
        StageResult("mix_preview", "ok", {"created_at": now}),
        StageResult("review", "ok", {"ready": True}),
    ]
