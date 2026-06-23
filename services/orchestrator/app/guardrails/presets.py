"""Dynamic policy presets for different deployment contexts."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RenderFlowPolicy:
    enabled: bool = True
    ai_enabled: bool = True
    user_role: str = "editor"
    allowed_modes: list[str] = field(default_factory=lambda: ["scene", "audio", "video"])
    max_tier: str = "C"
    max_duration_sec: int = 120
    cloud_allowed: bool = True
    local_only: bool = False
    require_review: bool = True
    nsfw_mode: str = "block"
    likeness_mode: str = "strict"
    copyright_mode: str = "warn"
    region_policy: str = "default"
    rate_limit_per_hour: int = 20
    user_id: str | None = None
    project_id: str | None = None
    max_gpu_seconds: int | None = None
    max_prompt_length: int = 4000
    csam_hash_check: bool = False
    provenance_mode: str = "json"


_PRESETS: dict[str, dict] = {
    "dev": {
        "nsfw_mode": "off",
        "likeness_mode": "off",
        "copyright_mode": "off",
        "rate_limit_per_hour": 1000,
        "require_review": False,
    },
    "us_default": {
        "nsfw_mode": "block",
        "likeness_mode": "strict",
        "copyright_mode": "warn",
        "rate_limit_per_hour": 20,
        "require_review": True,
        "region_policy": "us_default",
    },
    "eu": {
        "nsfw_mode": "block",
        "likeness_mode": "strict",
        "copyright_mode": "block",
        "rate_limit_per_hour": 20,
        "require_review": True,
        "region_policy": "eu",
        "provenance_mode": "c2pa",
    },
    "strict": {
        "nsfw_mode": "block",
        "likeness_mode": "consent",
        "copyright_mode": "block",
        "rate_limit_per_hour": 10,
        "require_review": True,
        "cloud_allowed": False,
        "max_duration_sec": 60,
        "provenance_mode": "c2pa",
    },
}


def build_policy(preset: str = "us_default", **overrides: object) -> RenderFlowPolicy:
    base = _PRESETS.get(preset, _PRESETS["us_default"])
    merged = {**base, **overrides}
    return RenderFlowPolicy(**{k: v for k, v in merged.items() if hasattr(RenderFlowPolicy, k)})
