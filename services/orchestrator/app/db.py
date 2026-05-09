from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

_pool: Any = None


def init_db(database_url: str | None) -> None:
    global _pool
    if not database_url:
        logger.info("DATABASE_URL not set; skipping PostgreSQL pool")
        return
    try:
        from psycopg_pool import ConnectionPool

        _pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=10,
            kwargs={"autocommit": False},
        )
        logger.info("PostgreSQL connection pool ready")
    except Exception as e:
        logger.warning("PostgreSQL init failed: %s", e)
        _pool = None


def pool_ready() -> bool:
    return _pool is not None


@contextmanager
def connection() -> Generator[Any, None, None]:
    if _pool is None:
        raise RuntimeError("database not configured")
    with _pool.connection() as conn:
        yield conn


def insert_ai_job(
    job_id: str,
    project_id: str,
    mode: str,
    prompt: str,
    status: str = "queued",
) -> None:
    if _pool is None:
        return
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ai_jobs (id, project_id, mode, prompt, status, updated_at)
                    values (%s::uuid, %s::uuid, %s, %s, %s, now())
                    """,
                    (job_id, project_id, mode, prompt, status),
                )
            conn.commit()
    except Exception as e:
        logger.debug("insert_ai_job failed (missing project FK?): %s", e)


def update_ai_job_status(job_id: str, status: str) -> None:
    if _pool is None:
        return
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update ai_jobs set status = %s, updated_at = now()
                    where id = %s::uuid
                    """,
                    (status, job_id),
                )
            conn.commit()
    except Exception as e:
        logger.debug("update_ai_job_status failed: %s", e)


def sync_job_stages(job_id: str, stages: list[str], completed_through: int) -> None:
    """Persist stage rows for observability; completed_through is last completed index (-1 = none)."""
    if _pool is None:
        return
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from ai_job_stages where job_id = %s::uuid", (job_id,))
                for i, name in enumerate(stages):
                    if i <= completed_through:
                        st = "done"
                    elif i == completed_through + 1:
                        st = "running"
                    else:
                        st = "pending"
                    cur.execute(
                        """
                        insert into ai_job_stages (job_id, stage_name, stage_order, status, started_at)
                        values (%s::uuid, %s, %s, %s, now())
                        """,
                        (job_id, name, i, st),
                    )
            conn.commit()
    except Exception as e:
        logger.debug("sync_job_stages failed: %s", e)


def insert_asset_placeholder(project_id: str, kind: str, uri: str, sha256: str = "pending") -> str:
    if _pool is None:
        return ""
    import uuid

    aid = str(uuid.uuid4())
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into assets (id, project_id, kind, uri, sha256, meta_jsonb)
                    values (%s::uuid, %s::uuid, %s, %s, %s, '{}'::jsonb)
                    """,
                    (aid, project_id, kind, uri, sha256),
                )
            conn.commit()
    except Exception as e:
        logger.debug("insert_asset_placeholder failed: %s", e)
        return ""
    return aid


def readiness_check() -> dict[str, object]:
    if _pool is None:
        return {
            "status": "disabled",
            "configured": False,
            "detail": "DATABASE_URL not set or PostgreSQL pool unavailable",
        }
    
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
        return {
            "status": "ok",
            "configured": True,
            "detail": "PostgreSQL reachable",
        }
    except Exception as e:
        return {
            "status": "degraded",
            "configured": True,
            "detail": f"Failed to reach Postgres with error: {e}",
        }
def get_ai_job(job_id: str) -> dict[str, Any] | None:
    if _pool is None:
        return None
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select id, project_id, mode, prompt, status, created_at, updated_at
                    from ai_jobs
                    where id = %s::uuid
                    """,
                    (job_id,),
                )
                r = cur.fetchone()
                if not r:
                    return None
                cols = [c.name for c in cur.description]
                return dict(zip(cols, r))
    except Exception as e:
        logger.debug("get_ai_job failed: %s", e)
        return None


def list_ai_jobs(project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if _pool is None:
        return []
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if project_id:
                    cur.execute(
                        """
                        select id, project_id, mode, prompt, status, created_at, updated_at
                        from ai_jobs
                        where project_id = %s::uuid
                        order by updated_at desc
                        limit %s
                        """,
                        (project_id, max(1, limit)),
                    )
                else:
                    cur.execute(
                        """
                        select id, project_id, mode, prompt, status, created_at, updated_at
                        from ai_jobs
                        order by updated_at desc
                        limit %s
                        """,
                        (max(1, limit),),
                    )
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.debug("list_ai_jobs failed: %s", e)
        return []


def get_ai_job_stages(job_id: str) -> list[str]:
    if _pool is None:
        return []
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select stage_name
                    from ai_job_stages
                    where job_id = %s::uuid
                    order by stage_order asc
                    """,
                    (job_id,),
                )
                return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.debug("get_ai_job_stages failed: %s", e)
        return []
