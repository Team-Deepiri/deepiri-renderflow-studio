"""In-memory project studio state when PostgreSQL is unavailable or for tests."""

from __future__ import annotations

import threading
from datetime import datetime, UTC
from typing import Any
from uuid import UUID, uuid4

_lock = threading.RLock()

DEMO_OWNER = UUID("00000000-0000-4000-8000-000000000001")

_users: dict[UUID, dict[str, Any]] = {}
_projects: dict[UUID, dict[str, Any]] = {}
_assets: dict[UUID, dict[str, Any]] = {}
_sequences: dict[UUID, dict[str, Any]] = {}
_tracks: dict[UUID, dict[str, Any]] = {}
_clips: dict[UUID, dict[str, Any]] = {}
_clip_effects: dict[UUID, dict[str, Any]] = {}
_scenes: dict[UUID, dict[str, Any]] = {}
_scene_nodes: dict[UUID, dict[str, Any]] = {}
_render_jobs: dict[UUID, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def ensure_demo_user() -> UUID:
    with _lock:
        if DEMO_OWNER not in _users:
            _users[DEMO_OWNER] = {
                "id": DEMO_OWNER,
                "email": "studio@renderflow.local",
                "display_name": "Renderflow Studio",
                "role": "admin",
                "created_at": _now(),
            }
        return DEMO_OWNER


def user_get(user_id: UUID) -> dict[str, Any] | None:
    with _lock:
        return _users.get(user_id)


def project_create(owner_id: UUID, name: str, fps_num: int, fps_den: int, sample_rate: int) -> dict[str, Any]:
    ensure_demo_user()
    pid = uuid4()
    row = {
        "id": pid,
        "owner_id": owner_id,
        "name": name,
        "fps_num": fps_num,
        "fps_den": fps_den,
        "sample_rate": sample_rate,
        "ai_enabled": True,
        "settings_jsonb": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _lock:
        _projects[pid] = row
    return row


def project_get(project_id: UUID) -> dict[str, Any] | None:
    with _lock:
        return _projects.get(project_id)


def project_list(owner_id: UUID | None = None) -> list[dict[str, Any]]:
    with _lock:
        rows = list(_projects.values())
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


def asset_create(
    project_id: UUID,
    kind: str,
    uri: str,
    sha256: str = "pending",
    duration_ms: int | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aid = uuid4()
    row = {
        "id": aid,
        "project_id": project_id,
        "kind": kind,
        "uri": uri,
        "sha256": sha256,
        "duration_ms": duration_ms,
        "meta_jsonb": dict(meta or {}),
        "created_at": _now(),
    }
    with _lock:
        _assets[aid] = row
    return row


def asset_list(project_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        return [a for a in _assets.values() if a["project_id"] == project_id]


def sequence_create(
    project_id: UUID,
    name: str,
    resolution_w: int,
    resolution_h: int,
    start_tc: str = "00:00:00:00",
) -> dict[str, Any]:
    sid = uuid4()
    row = {
        "id": sid,
        "project_id": project_id,
        "name": name,
        "start_tc": start_tc,
        "duration_ticks": 0,
        "resolution_w": resolution_w,
        "resolution_h": resolution_h,
        "created_at": _now(),
    }
    with _lock:
        _sequences[sid] = row
    return row


def sequence_list(project_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        return [s for s in _sequences.values() if s["project_id"] == project_id]


def sequence_get(sequence_id: UUID) -> dict[str, Any] | None:
    with _lock:
        return _sequences.get(sequence_id)


def track_create(sequence_id: UUID, track_type: str, lane_index: int, name: str) -> dict[str, Any]:
    tid = uuid4()
    row = {
        "id": tid,
        "sequence_id": sequence_id,
        "track_type": track_type,
        "lane_index": lane_index,
        "name": name,
        "muted": False,
        "solo": False,
        "created_at": _now(),
    }
    with _lock:
        _tracks[tid] = row
    return row


def track_list(sequence_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        rows = [t for t in _tracks.values() if t["sequence_id"] == sequence_id]
    return sorted(rows, key=lambda t: (t["lane_index"], t["name"]))


def clip_create(
    track_id: UUID,
    asset_id: UUID,
    in_tick: int,
    out_tick: int,
    src_in_tick: int = 0,
    speed_ratio: float = 1.0,
    transform: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cid = uuid4()
    row = {
        "id": cid,
        "track_id": track_id,
        "asset_id": asset_id,
        "in_tick": in_tick,
        "out_tick": out_tick,
        "src_in_tick": src_in_tick,
        "speed_ratio": speed_ratio,
        "transform_jsonb": dict(transform or {}),
        "created_at": _now(),
    }
    with _lock:
        _clips[cid] = row
    return row


def clip_list_for_sequence(sequence_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        track_ids = {t["id"] for t in _tracks.values() if t["sequence_id"] == sequence_id}
        return [c for c in _clips.values() if c["track_id"] in track_ids]


def clip_effect_create(clip_id: UUID, effect_type: str, order_idx: int, params: dict[str, Any]) -> dict[str, Any]:
    eid = uuid4()
    row = {
        "id": eid,
        "clip_id": clip_id,
        "effect_type": effect_type,
        "order_idx": order_idx,
        "params_jsonb": dict(params),
        "created_at": _now(),
    }
    with _lock:
        _clip_effects[eid] = row
    return row


def clip_effects_list(clip_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        rows = [e for e in _clip_effects.values() if e["clip_id"] == clip_id]
    return sorted(rows, key=lambda e: e["order_idx"])


def scene_create(project_id: UUID, name: str, unit_scale: float = 1.0, up_axis: str = "Y") -> dict[str, Any]:
    sid = uuid4()
    row = {
        "id": sid,
        "project_id": project_id,
        "name": name,
        "unit_scale": unit_scale,
        "up_axis": up_axis,
        "created_at": _now(),
    }
    with _lock:
        _scenes[sid] = row
    return row


def scene_list(project_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        return [s for s in _scenes.values() if s["project_id"] == project_id]


def scene_node_create(
    scene_id: UUID,
    parent_id: UUID | None,
    node_type: str,
    transform: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    nid = uuid4()
    row = {
        "id": nid,
        "scene_id": scene_id,
        "parent_id": parent_id,
        "node_type": node_type,
        "transform_jsonb": dict(transform),
        "payload_jsonb": dict(payload),
    }
    with _lock:
        _scene_nodes[nid] = row
    return row


def scene_nodes_list(scene_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        return [n for n in _scene_nodes.values() if n["scene_id"] == scene_id]


def render_job_create(
    project_id: UUID,
    sequence_id: UUID | None,
    preset: str,
    output_uri: str = "",
) -> dict[str, Any]:
    rid = uuid4()
    row = {
        "id": rid,
        "project_id": project_id,
        "sequence_id": sequence_id,
        "preset": preset,
        "status": "queued",
        "output_uri": output_uri,
        "metrics_jsonb": {},
        "created_at": _now(),
        "ended_at": None,
    }
    with _lock:
        _render_jobs[rid] = row
    return row


def render_job_get(job_id: UUID) -> dict[str, Any] | None:
    with _lock:
        return _render_jobs.get(job_id)


def render_job_list(project_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        return [r for r in _render_jobs.values() if r["project_id"] == project_id]


def project_update(
    project_id: UUID,
    name: str | None = None,
    fps_num: int | None = None,
    fps_den: int | None = None,
) -> dict[str, Any] | None:
    with _lock:
        row = _projects.get(project_id)
        if not row:
            return None
        if name is not None:
            row["name"] = name
        if fps_num is not None:
            row["fps_num"] = fps_num
        if fps_den is not None:
            row["fps_den"] = fps_den
        row["updated_at"] = _now()
        return row


def project_delete(project_id: UUID) -> None:
    with _lock:
        _projects.pop(project_id, None)


def asset_get(asset_id: UUID) -> dict[str, Any] | None:
    with _lock:
        return _assets.get(asset_id)
