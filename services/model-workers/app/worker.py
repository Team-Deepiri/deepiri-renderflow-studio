from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any


@dataclass
class StageResult:
    stage: str
    status: str
    payload: dict[str, Any]


def run_scene_job(prompt: str) -> list[StageResult]:
    # Non-blocking orchestration will call this worker in a process pool / queue consumer.
    now = datetime.now(UTC).isoformat()
    return [
        StageResult("storyboard", "ok", {"prompt": prompt, "created_at": now}),
        StageResult("layout", "ok", {"shots": 4}),
        StageResult("assets", "ok", {"generated_assets": 6}),
    ]


if __name__ == "__main__":
    sample = run_scene_job("Create a rainy neon alley intro shot")
    for stage in sample:
        print(stage)
