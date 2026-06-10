"""Unified studio operations: memory store + optional PostgreSQL mirror."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app import db_repos, memory_store


def bootstrap() -> None:
    memory_store.ensure_demo_user()


def create_project(
    owner_id: UUID,
    name: str,
    fps_num: int = 24,
    fps_den: int = 1,
    sample_rate: int = 48_000,
) -> dict[str, Any]:
    row = memory_store.project_create(owner_id, name, fps_num, fps_den, sample_rate)
    db_repos.insert_project(row)
    db_repos.audit_log(UUID(str(row["id"])), owner_id, "project.create", {"name": name})
    return row


def get_project(project_id: UUID) -> dict[str, Any] | None:
    r = memory_store.project_get(project_id)
    if r:
        return r
    pg = db_repos.fetch_project(project_id)
    return pg


def list_projects(owner_id: UUID | None = None) -> list[dict[str, Any]]:
    mem = memory_store.project_list(owner_id)
    if mem:
        return mem
    return db_repos.list_projects(owner_id)


def create_asset(
    project_id: UUID,
    kind: str,
    uri: str,
    sha256: str = "pending",
    duration_ms: int | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = memory_store.asset_create(project_id, kind, uri, sha256, duration_ms, meta)
    db_repos.insert_asset(row)
    return row


def list_assets(project_id: UUID) -> list[dict[str, Any]]:
    mem = memory_store.asset_list(project_id)
    if mem:
        return mem
    return db_repos.list_assets(project_id)


def create_sequence(
    project_id: UUID,
    name: str,
    resolution_w: int = 1920,
    resolution_h: int = 1080,
    start_tc: str = "00:00:00:00",
) -> dict[str, Any]:
    row = memory_store.sequence_create(project_id, name, resolution_w, resolution_h, start_tc)
    db_repos.insert_sequence(row)
    return row


def list_sequences(project_id: UUID) -> list[dict[str, Any]]:
    mem = memory_store.sequence_list(project_id)
    if mem:
        return mem
    return db_repos.list_sequences(project_id)


def get_sequence(sequence_id: UUID) -> dict[str, Any] | None:
    row = memory_store.sequence_get(sequence_id)
    if row:
        return row
    return db_repos.fetch_sequence(sequence_id)


def create_track(sequence_id: UUID, track_type: str, lane_index: int, name: str) -> dict[str, Any]:
    row = memory_store.track_create(sequence_id, track_type, lane_index, name)
    db_repos.insert_track(row)
    return row


def list_tracks(sequence_id: UUID) -> list[dict[str, Any]]:
    mem = memory_store.track_list(sequence_id)
    if mem:
        return mem
    return db_repos.list_tracks(sequence_id)


def delete_track(track_id: UUID) -> bool:
    found = memory_store.track_delete(track_id)
    db_repos.delete_track(track_id)
    return found


def create_clip(
    track_id: UUID,
    asset_id: UUID,
    in_tick: int,
    out_tick: int,
    src_in_tick: int = 0,
    speed_ratio: float = 1.0,
    transform: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = memory_store.clip_create(
        track_id, asset_id, in_tick, out_tick, src_in_tick, speed_ratio, transform
    )
    db_repos.insert_clip(row)
    return row


def list_clips_for_sequence(sequence_id: UUID) -> list[dict[str, Any]]:
    mem = memory_store.clip_list_for_sequence(sequence_id)
    if mem:
        return mem
    return db_repos.list_clips_for_sequence(sequence_id)


def add_clip_effect(
    clip_id: UUID, effect_type: str, order_idx: int, params: dict[str, Any]
) -> dict[str, Any]:
    row = memory_store.clip_effect_create(clip_id, effect_type, order_idx, params)
    db_repos.insert_clip_effect(row)
    return row


def list_clip_effects(clip_id: UUID) -> list[dict[str, Any]]:
    return memory_store.clip_effects_list(clip_id)


def create_scene(project_id: UUID, name: str, unit_scale: float = 1.0, up_axis: str = "Y") -> dict[str, Any]:
    row = memory_store.scene_create(project_id, name, unit_scale, up_axis)
    db_repos.insert_scene(row)
    return row


def list_scenes(project_id: UUID) -> list[dict[str, Any]]:
    return memory_store.scene_list(project_id)


def create_scene_node(
    scene_id: UUID,
    parent_id: UUID | None,
    node_type: str,
    transform: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = memory_store.scene_node_create(scene_id, parent_id, node_type, transform, payload)
    db_repos.insert_scene_node(row)
    return row


def list_scene_nodes(scene_id: UUID) -> list[dict[str, Any]]:
    return memory_store.scene_nodes_list(scene_id)


def update_project(
    project_id: UUID,
    name: str | None = None,
    fps_num: int | None = None,
    fps_den: int | None = None,
) -> dict[str, Any] | None:
    row = memory_store.project_update(project_id, name, fps_num, fps_den)
    if row:
        db_repos.update_project(row)
    return row


def delete_project(project_id: UUID) -> None:
    memory_store.project_delete(project_id)
    db_repos.delete_project(project_id)


def get_asset(asset_id: UUID) -> dict[str, Any] | None:
    return memory_store.asset_get(asset_id)


def update_asset_meta(asset_id: UUID, meta_updates: dict[str, Any]) -> dict[str, Any] | None:
    return memory_store.asset_update_meta(asset_id, meta_updates)


def get_tracks(sequence_id: UUID) -> list[dict[str, Any]]:
    return list_tracks(sequence_id)


def get_active_clips(sequence_id: UUID, playhead_tick: int) -> list[dict[str, Any]]:
    clips = list_clips_for_sequence(sequence_id)
    return [c for c in clips if c.get("in_tick", 0) <= playhead_tick < c.get("out_tick", 0)]


def create_render_job(
    project_id: UUID,
    sequence_id: UUID | None,
    preset: str,
    output_uri: str = "",
) -> dict[str, Any]:
    row = memory_store.render_job_create(project_id, sequence_id, preset, output_uri)
    db_repos.insert_render_job(row)
    return row


def get_render_job(job_id: UUID) -> dict[str, Any] | None:
    return memory_store.render_job_get(job_id)


def list_render_jobs(project_id: UUID) -> list[dict[str, Any]]:
    return memory_store.render_job_list(project_id)


def submit_render_job(project_id: UUID, sequence_id: UUID | None, preset: str) -> dict[str, Any]:
    row = memory_store.render_job_create(project_id, sequence_id, preset)
    db_repos.insert_render_job(row)
    return row
