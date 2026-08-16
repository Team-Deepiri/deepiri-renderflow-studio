"""In-memory project studio state when PostgreSQL is unavailable or for tests."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

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

_STORE_PATH = Path(__file__).parent.parent / "data" / "store.json"

_UUID_FIELDS = {
    "id", "owner_id", "project_id", "sequence_id", "track_id",
    "asset_id", "clip_id", "scene_id", "parent_id", "job_id",
}
_DT_FIELDS = {"created_at", "updated_at", "ended_at", "started_at"}

_ALL_STORES = [
    ("users", "_users"),
    ("projects", "_projects"),
    ("assets", "_assets"),
    ("sequences", "_sequences"),
    ("tracks", "_tracks"),
    ("clips", "_clips"),
    ("clip_effects", "_clip_effects"),
    ("scenes", "_scenes"),
    ("scene_nodes", "_scene_nodes"),
    ("render_jobs", "_render_jobs"),
]


def _record_to_json(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in record.items():
        if isinstance(v, UUID):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _record_from_json(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in record.items():
        if k in _UUID_FIELDS and v is not None:
            out[k] = UUID(v)
        elif k in _DT_FIELDS and v is not None:
            out[k] = datetime.fromisoformat(v)
        else:
            out[k] = v
    return out


def _save() -> None:
    try:
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        import sys
        this = sys.modules[__name__]
        data: dict[str, Any] = {}
        for json_key, attr in _ALL_STORES:
            store: dict[UUID, dict] = getattr(this, attr)
            data[json_key] = {str(k): _record_to_json(v) for k, v in store.items()}
        tmp = _STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(_STORE_PATH)
    except Exception as e:
        logger.warning("Failed to persist store: %s", e)


def _load() -> None:
    if not _STORE_PATH.exists():
        return
    try:
        import sys
        this = sys.modules[__name__]
        data = json.loads(_STORE_PATH.read_text())
        for json_key, attr in _ALL_STORES:
            store: dict[UUID, dict] = getattr(this, attr)
            store.clear()
            for k_str, v in data.get(json_key, {}).items():
                store[UUID(k_str)] = _record_from_json(v)
        logger.info("Loaded store from %s", _STORE_PATH)
    except Exception as e:
        logger.warning("Failed to load store: %s", e)


_load()


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
            _save()
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
    _save()
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
    _save()
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
    _save()
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
    _save()
    return row


def track_list(sequence_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        rows = [t for t in _tracks.values() if t["sequence_id"] == sequence_id]
    return sorted(rows, key=lambda t: (t["lane_index"], t["name"]))


def track_delete(track_id: UUID) -> bool:
    with _lock:
        existed = _tracks.pop(track_id, None)
    if existed:
        _save()
    return existed is not None


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
    _save()
    return row


def clip_list_for_sequence(sequence_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        track_ids = {t["id"] for t in _tracks.values() if t["sequence_id"] == sequence_id}
        return [c for c in _clips.values() if c["track_id"] in track_ids]


def clip_replace_for_sequence(
    sequence_id: UUID, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Make `rows` this sequence's complete clip list, under one lock + save.

    Clips carrying an id already present are updated in place (created_at is
    preserved); clips in the sequence but absent from `rows` are dropped. Rows
    pointing at a track outside this sequence are ignored.
    """
    with _lock:
        track_ids = {t["id"] for t in _tracks.values() if t["sequence_id"] == sequence_id}
        keep = {r["id"] for r in rows}
        for cid in [
            c["id"]
            for c in _clips.values()
            if c["track_id"] in track_ids and c["id"] not in keep
        ]:
            _clips.pop(cid, None)

        created: list[dict[str, Any]] = []
        for r in rows:
            if r["track_id"] not in track_ids:
                continue
            existing = _clips.get(r["id"])
            row = {
                "id": r["id"],
                "track_id": r["track_id"],
                "asset_id": r["asset_id"],
                "in_tick": r["in_tick"],
                "out_tick": r["out_tick"],
                "src_in_tick": r.get("src_in_tick", 0),
                "speed_ratio": r.get("speed_ratio", 1.0),
                "transform_jsonb": dict(r.get("transform") or {}),
                "created_at": existing["created_at"] if existing else _now(),
            }
            _clips[r["id"]] = row
            created.append(row)
    _save()
    return created


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
    _save()
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
    _save()
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
    _save()
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
    _save()
    return row


def render_job_get(job_id: UUID) -> dict[str, Any] | None:
    with _lock:
        return _render_jobs.get(job_id)


def render_job_list(project_id: UUID) -> list[dict[str, Any]]:
    with _lock:
        return [r for r in _render_jobs.values() if r["project_id"] == project_id]


def render_job_update(
    job_id: UUID,
    *,
    status: str | None = None,
    output_uri: str | None = None,
    progress: float | None = None,
    error: str | None = None,
    ended: bool = False,
) -> dict[str, Any] | None:
    with _lock:
        row = _render_jobs.get(job_id)
        if not row:
            return None
        if status is not None:
            row["status"] = status
        if output_uri is not None:
            row["output_uri"] = output_uri
        if progress is not None:
            row.setdefault("metrics_jsonb", {})["progress"] = progress
        if error is not None:
            row.setdefault("metrics_jsonb", {})["error"] = error
        if ended:
            row["ended_at"] = _now()
    _save()
    return row


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
    _save()
    return row


def project_delete(project_id: UUID) -> None:
    with _lock:
        _projects.pop(project_id, None)
    _save()


def asset_get(asset_id: UUID) -> dict[str, Any] | None:
    with _lock:
        return _assets.get(asset_id)


def asset_update_meta(asset_id: UUID, meta_updates: dict[str, Any]) -> dict[str, Any] | None:
    with _lock:
        row = _assets.get(asset_id)
        if not row:
            return None
        row["meta_jsonb"].update(meta_updates)
    _save()
    return row
