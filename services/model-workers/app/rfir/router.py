"""RFIR Router — assign a rendering Tier to each shot (§2.3).

Spec reference: rfir-inference-engine-implementation.md §2.3
"""
from __future__ import annotations

from app.rfir.ir.types import CameraMotion, Shot, ShotList, Tier

# Verbs that imply real subject motion → favor video synthesis over parallax.
ACTION_VERBS: frozenset[str] = frozenset({
    "run", "running", "runs",
    "jump", "jumping", "jumps",
    "fight", "fighting", "fights",
    "dance", "dancing", "dances",
    "explode", "exploding", "explosion",
    "fly", "flying", "flies", "soaring", "soar",
    "fall", "falling", "falls",
    "spin", "spinning", "crash", "crashing",
    "walk", "walking", "walks",
    "swim", "swimming", "ride", "riding",
})

# How much each camera motion contributes to the tier score.
_CAMERA_WEIGHT: dict[CameraMotion, int] = {
    CameraMotion.STATIC: 0,
    CameraMotion.ZOOM: 0,
    CameraMotion.PAN: 1,
    CameraMotion.DOLLY: 1,
    CameraMotion.TRACKING: 1,
    CameraMotion.ORBIT: 2,
}

_LONG_SHOT_SEC = 8.0
_TIER_ORDER = [Tier.A, Tier.B, Tier.C, Tier.D]


def _has_action_verb(text: str) -> bool:
    words = {w.strip(".,!?:;\"'").lower() for w in text.split()}
    return bool(words & ACTION_VERBS)


def _score_to_tier(score: int) -> Tier:
    if score <= 0:
        return Tier.A
    if score == 1:
        return Tier.B
    if score == 2:
        return Tier.C
    return Tier.D


def cap_tier(tier: Tier, max_tier: Tier) -> Tier:
    """Clamp `tier` so it never exceeds `max_tier`."""
    return tier if _TIER_ORDER.index(tier) <= _TIER_ORDER.index(max_tier) else max_tier


def assign_tier(shot: Shot, max_tier: Tier = Tier.D) -> Tier:
    """Compute the tier for a single shot from its metadata."""
    score = _CAMERA_WEIGHT.get(shot.camera.motion, 0)
    score += int(round(max(0.0, shot.camera.speed - 1.0)))  # fast camera adds pressure
    if _has_action_verb(shot.description):
        score += 1
    if shot.subject.strip():
        score += 1
    if shot.duration_sec > _LONG_SHOT_SEC:
        score += 1
    return cap_tier(_score_to_tier(score), max_tier)


def assign_tiers(shot_list: ShotList, max_tier: Tier = Tier.D) -> ShotList:
    """Assign a tier to every shot in place; returns the same ShotList."""
    for shot in shot_list.shots:
        shot.tier = assign_tier(shot, max_tier=max_tier)
    return shot_list
