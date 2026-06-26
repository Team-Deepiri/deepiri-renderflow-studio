"""RFIR Planner — prompt → ShotList via Qwen2.5-3B (§2.4).

Spec reference: rfir-inference-engine-implementation.md §2.4
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from app.rfir.ir.types import CameraMotion, CameraPath, Shot, ShotList
from app.rfir.router import assign_tiers
from app.rfir.ir.types import Tier

logger = logging.getLogger(__name__)

QWEN_MODEL_ID = "qwen2.5-3b-instruct-gguf"

_MIN_SHOTS = 1
_MAX_SHOTS = 6
_MIN_DUR_SEC = 1.5
_MAX_DUR_SEC = 8.0
_VALID_MOTIONS = {m.value for m in CameraMotion}

# JSON schema used to constrain Qwen's output (llama-cpp grammar) and to
# document the contract. Tier is deliberately absent — the router decides it.
SHOTLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "minItems": _MIN_SHOTS,
            "maxItems": _MAX_SHOTS,
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "duration_sec": {"type": "number"},
                    "camera_motion": {"type": "string", "enum": sorted(_VALID_MOTIONS)},
                    "subject": {"type": "string"},
                    "style": {"type": "string"},
                },
                "required": ["description", "camera_motion"],
            },
        },
        "style_guidance": {"type": "string"},
    },
    "required": ["shots"],
}

_SYSTEM_PROMPT = (
    "You are a film shot planner. Given a creative prompt, break it into a short "
    "sequence of distinct camera shots. Respond with ONLY a JSON object matching "
    "the required schema. For each shot provide: a vivid one-sentence description, "
    "a duration in seconds (1.5 to 8), a camera_motion from "
    f"{sorted(_VALID_MOTIONS)}, the main subject (or empty string), and an "
    "optional style. Use 1 to 6 shots. Do not include any prose outside the JSON."
)


class PlannerBlocked(Exception):
    """Raised when the guardrail rejects the prompt."""


class PlannerError(Exception):
    """Raised when generation or parsing fails."""


def _user_message(prompt: str, num_shots: int | None) -> str:
    hint = f" Plan exactly {num_shots} shots." if num_shots else ""
    return f"Prompt: {prompt}{hint}"


def _generate_with_qwen(prompt: str, num_shots: int | None) -> str:
    """Run Qwen via llama-cpp; return the raw JSON string."""
    from app.rfir.models.loader import load_model

    llm = load_model(QWEN_MODEL_ID)
    result = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_message(prompt, num_shots)},
        ],
        response_format={"type": "json_object", "schema": SHOTLIST_SCHEMA},
        temperature=0.4,
        max_tokens=1024,
    )
    return result["choices"][0]["message"]["content"]


def _coerce_motion(value: object) -> CameraMotion:
    if isinstance(value, str) and value.lower() in _VALID_MOTIONS:
        return CameraMotion(value.lower())
    return CameraMotion.STATIC


def _clamp_duration(value: object) -> float:
    try:
        d = float(value)
    except (TypeError, ValueError):
        return _MIN_DUR_SEC
    return max(_MIN_DUR_SEC, min(_MAX_DUR_SEC, d))


def _parse_shotlist(raw: str, prompt: str) -> ShotList:
    """Validate Qwen's JSON and map it to a ShotList (no tiers yet)."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise PlannerError(f"planner returned invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise PlannerError("planner output is not a JSON object")

    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise PlannerError("planner output has no shots")

    shots: list[Shot] = []
    for i, item in enumerate(raw_shots[:_MAX_SHOTS]):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if not description:
            continue
        shots.append(Shot(
            index=len(shots),
            description=description,
            duration_sec=_clamp_duration(item.get("duration_sec")),
            camera=CameraPath(motion=_coerce_motion(item.get("camera_motion"))),
            subject=str(item.get("subject", "")).strip(),
            style=str(item.get("style", "")).strip(),
        ))

    if not shots:
        raise PlannerError("planner produced no usable shots")

    return ShotList(
        prompt=prompt,
        shots=shots,
        style_guidance=str(data.get("style_guidance", "")).strip(),
    )


def plan(
    prompt: str,
    *,
    guardrail: Callable[[str], bool],
    num_shots: int | None = None,
    max_tier: Tier = Tier.C,
    generate_fn: Callable[[str], str] | None = None,
) -> ShotList:
    """Produce a tier-assigned ShotList from a prompt using Qwen."""
    # 🛡️ Mandatory guardrail, fail-closed: any error blocks rather than bypasses.
    try:
        allowed = guardrail(prompt)
    except Exception as e:
        raise PlannerBlocked(f"guardrail check failed (fail-closed): {e}") from e
    if not allowed:
        raise PlannerBlocked(f"prompt rejected by guardrail: {prompt[:60]!r}")

    if num_shots is not None:
        num_shots = max(_MIN_SHOTS, min(num_shots, _MAX_SHOTS))

    raw = generate_fn(prompt) if generate_fn else _generate_with_qwen(prompt, num_shots)
    shot_list = _parse_shotlist(raw, prompt)

    # Tier assignment is the router's deterministic job, applied to Qwen's shots.
    assign_tiers(shot_list, max_tier=max_tier)
    return shot_list
