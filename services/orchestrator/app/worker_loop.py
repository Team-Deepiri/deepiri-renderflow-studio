from __future__ import annotations

import json
import logging
import threading
import time
from queue import Empty, Queue
from uuid import UUID

from app.config import Settings
from app.job_store import JobStatus, store
from renderflow_queue import REDIS_KEY_JOBS, RedisJobQueue
from app.stage_runner import run_audio_stages, run_scene_stages

logger = logging.getLogger(__name__)

_local_pending: Queue[str] = Queue()
_stop = threading.Event()
_worker_thread: threading.Thread | None = None
_cancelled_jobs: set[str] = set()


def enqueue_job(job_id: str, settings: Settings) -> None:
    _cancelled_jobs.discard(job_id)
    if settings.redis_url:
        try:
            import redis

            r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            RedisJobQueue(r).push_job(job_id, {})
            return
        except Exception as e:
            logger.warning("Redis enqueue failed, falling back to local: %s", e)
    _local_pending.put(job_id)


def cancel_job(job_id: str) -> None:
    _cancelled_jobs.add(job_id)


def worker_stats() -> dict[str, object]:
    return {
        "worker_running": bool(_worker_thread and _worker_thread.is_alive()),
        "local_pending_count": _local_pending.qsize(),
        "cancelled_jobs_count": len(_cancelled_jobs),
    }


def _process_job(job_id: str, settings: Settings) -> None:
    try:
        uid = UUID(job_id)
    except ValueError:
        logger.error("invalid job id %s", job_id)
        return
    rec = store.get(uid)
    if not rec:
        logger.warning("job not in store: %s", job_id)
        return
    if job_id in _cancelled_jobs:
        store.update_status(uid, JobStatus.CANCELLED, stages=["cancelled"])
        return

    store.update_status(uid, JobStatus.PREPARING, stages=["preparing"])
    time.sleep(settings.ai_stages_simulate_ms / 1000.0)

    if rec.mode in ("audio", "voice", "dialogue"):
        results = run_audio_stages(rec.prompt)
    else:
        results = run_scene_stages(rec.prompt)

    names = [r.stage for r in results]

    for i, res in enumerate(results):
        if job_id in _cancelled_jobs:
            store.update_status(uid, JobStatus.CANCELLED, stages=names[:i] + ["cancelled"])
            return
        partial = names[: i + 1]
        store.update_status(uid, JobStatus.RUNNING, stages=partial)
        store.merge_meta(uid, f"stage_{res.stage}", res.payload)
        store.set_stages(uid, names, completed_through=i)
        time.sleep(settings.ai_stages_simulate_ms / 1000.0)

    store.set_stages(uid, names, completed_through=len(names) - 1)
    store.update_status(uid, JobStatus.REVIEW, stages=names)

    try:
        from app import db_repos, memory_store

        uri = f"renderflow://jobs/{job_id}/bundle.json"
        arow = memory_store.asset_create(rec.project_id, "ai_bundle", uri, sha256="pending")
        db_repos.insert_asset(arow)
        aid = str(arow["id"])
        store.merge_meta(uid, "asset_id", aid)
        db_repos.insert_ai_job_artifact(str(uid), aid, "ai_bundle", None)
    except Exception as e:
        logger.debug("asset commit: %s", e)

    final_stages = names + ["committed"]
    store.update_status(uid, JobStatus.COMMITTED, stages=final_stages)


def _loop(settings: Settings) -> None:
    if settings.redis_url:
        try:
            import redis

            r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            logger.info("worker using Redis queue %s", REDIS_KEY_JOBS)
            while not _stop.is_set():
                item = r.blpop(REDIS_KEY_JOBS, timeout=2)
                if not item:
                    continue
                _, raw = item
                try:
                    data = json.loads(raw)
                    jid = data.get("job_id", "")
                except json.JSONDecodeError:
                    jid = raw
                if jid:
                    _process_job(jid, settings)
            return
        except Exception as e:
            logger.warning("Redis worker failed, using in-process queue: %s", e)

    logger.info("worker using in-process queue")
    while not _stop.is_set():
        try:
            jid = _local_pending.get(timeout=0.5)
        except Empty:
            continue
        _process_job(jid, settings)


def start_worker(settings: Settings) -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return

    def run() -> None:
        try:
            _loop(settings)
        except Exception:
            logger.exception("worker crashed")

    _worker_thread = threading.Thread(target=run, name="renderflow-ai-worker", daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    _stop.set()
