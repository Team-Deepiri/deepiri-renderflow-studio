"""PostgreSQL persistence for studio entities (optional when DATABASE_URL set)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app import db

logger = logging.getLogger(__name__)


def insert_project(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into projects (id, owner_id, name, fps_num, fps_den, sample_rate, ai_enabled, settings_jsonb)
                    values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(row["id"]),
                        str(row["owner_id"]),
                        row["name"],
                        row["fps_num"],
                        row["fps_den"],
                        row["sample_rate"],
                        row.get("ai_enabled", True),
                        __import__("json").dumps(row.get("settings_jsonb") or {}),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_project: %s", e)


def fetch_project(project_id: UUID) -> dict[str, Any] | None:
    if not db.pool_ready():
        return None
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id, owner_id, name, fps_num, fps_den, sample_rate, ai_enabled, settings_jsonb, created_at, updated_at
                    from projects where id = %s::uuid
                    """,
                    (str(project_id),),
                )
                cols = [c.name for c in cur.description]
                r = cur.fetchone()
                if not r:
                    return None
                return dict(zip(cols, r))
    except Exception as e:
        logger.warning("fetch_project: %s", e)
        return None


def list_projects(owner_id: UUID | None = None) -> list[dict[str, Any]]:
    if not db.pool_ready():
        return []
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                if owner_id:
                    cur.execute(
                        """
                        select id, owner_id, name, fps_num, fps_den, sample_rate, ai_enabled, created_at
                        from projects where owner_id = %s::uuid order by updated_at desc
                        """,
                        (str(owner_id),),
                    )
                else:
                    cur.execute(
                        """
                        select id, owner_id, name, fps_num, fps_den, sample_rate, ai_enabled, created_at
                        from projects order by updated_at desc
                        """
                    )
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.warning("list_projects: %s", e)
        return []


def insert_asset(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into assets (id, project_id, kind, uri, sha256, duration_ms, meta_jsonb)
                    values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(row["id"]),
                        str(row["project_id"]),
                        row["kind"],
                        row["uri"],
                        row["sha256"],
                        row.get("duration_ms"),
                        __import__("json").dumps(row.get("meta_jsonb") or {}),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_asset: %s", e)


def list_assets(project_id: UUID) -> list[dict[str, Any]]:
    if not db.pool_ready():
        return []
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id, project_id, kind, uri, sha256, duration_ms, meta_jsonb, created_at
                    from assets where project_id = %s::uuid order by created_at desc
                    """,
                    (str(project_id),),
                )
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.warning("list_assets: %s", e)
        return []


def insert_sequence(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into sequences (id, project_id, name, start_tc, duration_ticks, resolution_w, resolution_h)
                    values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(row["id"]),
                        str(row["project_id"]),
                        row["name"],
                        row.get("start_tc", "00:00:00:00"),
                        row.get("duration_ticks", 0),
                        row["resolution_w"],
                        row["resolution_h"],
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_sequence: %s", e)


def fetch_sequence(sequence_id: UUID) -> dict[str, Any] | None:
    if not db.pool_ready():
        return None
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id, project_id, name, start_tc, duration_ticks, resolution_w, resolution_h, created_at
                    from sequences where id = %s::uuid
                    """,
                    (str(sequence_id),),
                )
                cols = [c.name for c in cur.description]
                row = cur.fetchone()
                if not row:
                    return None
                return dict(zip(cols, row))
    except Exception as e:
        logger.warning("fetch_sequence: %s", e)
        return None


def list_sequences(project_id: UUID) -> list[dict[str, Any]]:
    if not db.pool_ready():
        return []
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id, project_id, name, start_tc, duration_ticks, resolution_w, resolution_h, created_at
                    from sequences where project_id = %s::uuid order by created_at desc
                    """,
                    (str(project_id),),
                )
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.warning("list_sequences: %s", e)
        return []


def insert_track(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into tracks (id, sequence_id, track_type, lane_index, name, muted, solo)
                    values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(row["id"]),
                        str(row["sequence_id"]),
                        row["track_type"],
                        row["lane_index"],
                        row["name"],
                        row.get("muted", False),
                        row.get("solo", False),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_track: %s", e)


def delete_track(track_id: UUID) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from tracks where id = %s::uuid", (str(track_id),))
            conn.commit()
    except Exception as e:
        logger.warning("delete_track: %s", e)


def list_tracks(sequence_id: UUID) -> list[dict[str, Any]]:
    if not db.pool_ready():
        return []
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id, sequence_id, track_type, lane_index, name, muted, solo, created_at
                    from tracks where sequence_id = %s::uuid order by lane_index, name
                    """,
                    (str(sequence_id),),
                )
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.warning("list_tracks: %s", e)
        return []


def list_clips_for_sequence(sequence_id: UUID) -> list[dict[str, Any]]:
    if not db.pool_ready():
        return []
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select c.id, c.track_id, c.asset_id, c.in_tick, c.out_tick, c.src_in_tick, c.speed_ratio, c.transform_jsonb
                    from clips c
                    join tracks t on t.id = c.track_id
                    where t.sequence_id = %s::uuid
                    order by c.in_tick
                    """,
                    (str(sequence_id),),
                )
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.warning("list_clips_for_sequence: %s", e)
        return []


def insert_clip(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into clips (id, track_id, asset_id, in_tick, out_tick, src_in_tick, speed_ratio, transform_jsonb)
                    values (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(row["id"]),
                        str(row["track_id"]),
                        str(row["asset_id"]),
                        row["in_tick"],
                        row["out_tick"],
                        row.get("src_in_tick", 0),
                        float(row.get("speed_ratio", 1.0)),
                        __import__("json").dumps(row.get("transform_jsonb") or {}),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_clip: %s", e)


def replace_clips_for_sequence(sequence_id: UUID, rows: list[dict[str, Any]]) -> None:
    """Make `rows` the sequence's complete clip list in ONE transaction.

    Clips absent from `rows` are deleted; the rest are upserted by id so their
    clip_effects survive (a delete-then-insert would cascade them away). The
    single commit at the end means a failure anywhere leaves the previous
    clip list intact rather than a half-written one.
    """
    if not db.pool_ready():
        return
    try:
        keep = [str(r["id"]) for r in rows]
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    delete from clips
                    where track_id in (select id from tracks where sequence_id = %s::uuid)
                      and id <> all(%s::uuid[])
                    """,
                    (str(sequence_id), keep),
                )
                for r in rows:
                    cur.execute(
                        """
                        insert into clips (id, track_id, asset_id, in_tick, out_tick,
                                           src_in_tick, speed_ratio, transform_jsonb, updated_at)
                        values (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, now())
                        on conflict (id) do update set
                          track_id = excluded.track_id,
                          asset_id = excluded.asset_id,
                          in_tick = excluded.in_tick,
                          out_tick = excluded.out_tick,
                          src_in_tick = excluded.src_in_tick,
                          speed_ratio = excluded.speed_ratio,
                          transform_jsonb = excluded.transform_jsonb,
                          updated_at = now()
                        """,
                        (
                            str(r["id"]),
                            str(r["track_id"]),
                            str(r["asset_id"]),
                            r["in_tick"],
                            r["out_tick"],
                            r.get("src_in_tick", 0),
                            float(r.get("speed_ratio", 1.0)),
                            __import__("json").dumps(r.get("transform_jsonb") or {}),
                        ),
                    )
            conn.commit()
    except Exception as e:
        logger.warning("replace_clips_for_sequence: %s", e)


def insert_clip_effect(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into clip_effects (id, clip_id, effect_type, order_idx, params_jsonb)
                    values (%s::uuid, %s::uuid, %s, %s, %s::jsonb)
                    """,
                    (
                        str(row["id"]),
                        str(row["clip_id"]),
                        row["effect_type"],
                        row["order_idx"],
                        __import__("json").dumps(row.get("params_jsonb") or {}),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_clip_effect: %s", e)


def insert_scene(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into scenes (id, project_id, name, unit_scale, up_axis)
                    values (%s::uuid, %s::uuid, %s, %s, %s)
                    """,
                    (
                        str(row["id"]),
                        str(row["project_id"]),
                        row["name"],
                        float(row.get("unit_scale", 1.0)),
                        row.get("up_axis", "Y"),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_scene: %s", e)


def insert_scene_node(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into scene_nodes (id, scene_id, parent_id, node_type, transform_jsonb, payload_jsonb)
                    values (%s::uuid, %s::uuid, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        str(row["id"]),
                        str(row["scene_id"]),
                        str(row["parent_id"]) if row.get("parent_id") else None,
                        row["node_type"],
                        __import__("json").dumps(row.get("transform_jsonb") or {}),
                        __import__("json").dumps(row.get("payload_jsonb") or {}),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_scene_node: %s", e)


def insert_render_job(row: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into render_jobs (id, project_id, sequence_id, preset, status, output_uri, metrics_jsonb)
                    values (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(row["id"]),
                        str(row["project_id"]),
                        str(row["sequence_id"]) if row.get("sequence_id") else None,
                        row["preset"],
                        row.get("status", "queued"),
                        row.get("output_uri"),
                        __import__("json").dumps(row.get("metrics_jsonb") or {}),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_render_job: %s", e)


def insert_ai_job_artifact(job_id: str, asset_id: str | None, artifact_type: str, confidence: float | None) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ai_job_artifacts (job_id, asset_id, artifact_type, confidence)
                    values (%s::uuid, %s, %s, %s)
                    """,
                    (job_id, asset_id, artifact_type, confidence),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_ai_job_artifact: %s", e)


def insert_guardrail_decision(
    job_id: str | None,
    gate: str,
    verdict: str,
    reason_code: str | None = None,
    score: float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    if not db.pool_ready():
        return
    try:
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into guardrail_decisions (job_id, gate, verdict, reason_code, score, details_jsonb)
                    values (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        job_id,
                        gate,
                        verdict,
                        reason_code,
                        score,
                        __import__("json").dumps(details or {}),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("insert_guardrail_decision: %s", e)


def audit_log(project_id: UUID | None, actor_id: UUID | None, event_type: str, payload: dict[str, Any]) -> None:
    if not db.pool_ready():
        return
    try:
        import uuid

        eid = str(uuid.uuid4())
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into audit_events (id, project_id, actor_id, event_type, payload_jsonb)
                    values (%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb)
                    """,
                    (
                        eid,
                        str(project_id) if project_id else None,
                        str(actor_id) if actor_id else None,
                        event_type,
                        __import__("json").dumps(payload),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.warning("audit_log: %s", e)
