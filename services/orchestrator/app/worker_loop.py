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
from app.api.utils import get_event_emitter
from app.paths import data_subdir

from pathlib import Path
import subprocess, shutil

logger = logging.getLogger(__name__)

_local_pending: Queue[str] = Queue()
_stop = threading.Event()
_worker_thread: threading.Thread | None = None
_cancelled_jobs: set[str] = set()


def _emit(job_id: str, status: str, stage: str | None = None, project_id: str | None = None) -> None:
    payload: dict[str, object] = {"job_id": job_id, "status": status}
    if stage:
        payload["stage"] = stage
    if project_id:
        payload["project_id"] = project_id
    try:
        get_event_emitter().emit("job_update", payload)
    except Exception:
        pass


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
    pid = str(rec.project_id)

    if job_id in _cancelled_jobs:
        store.update_status(uid, JobStatus.CANCELLED, stages=["cancelled"])
        _emit(job_id, "cancelled", project_id=pid)
        return

    store.update_status(uid, JobStatus.PREPARING, stages=["preparing"])
    _emit(job_id, "preparing", project_id=pid)
    time.sleep(settings.ai_stages_simulate_ms / 1000.0)

    if rec.mode in ("audio", "voice", "dialogue"):
        results = run_audio_stages(rec.prompt)
    else:
        results = run_scene_stages(rec.prompt)

    names = [r.stage for r in results]

    for i, res in enumerate(results):
        if job_id in _cancelled_jobs:
            store.update_status(uid, JobStatus.CANCELLED, stages=names[:i] + ["cancelled"])
            _emit(job_id, "cancelled", stage=res.stage, project_id=pid)
            return
        partial = names[: i + 1]
        store.update_status(uid, JobStatus.RUNNING, stages=partial)
        store.merge_meta(uid, f"stage_{res.stage}", res.payload)
        store.set_stages(uid, names, completed_through=i)
        _emit(job_id, "running", stage=res.stage, project_id=pid)
        time.sleep(settings.ai_stages_simulate_ms / 1000.0)

    store.set_stages(uid, names, completed_through=len(names) - 1)
    store.update_status(uid, JobStatus.REVIEW, stages=names)
    _emit(job_id, "review", project_id=pid)

    out_dir = data_subdir("ai_outputs", settings) / str(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / "scene.mp4")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        store.merge_meta(uid, "artifact_error", "ffmpeg not found")
        store.merge_meta(uid, "output_path", None)
    else:
        proc = subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=5",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path],
            check=False, capture_output=True, text=True,
        )
        if Path(output_path).exists():
            store.merge_meta(uid, "output_path", output_path)
            store.merge_meta(uid, "artifact_error", None)
        else:
            err = (proc.stderr or proc.stdout or "ffmpeg did not produce scene.mp4")[:500]
            store.merge_meta(uid, "artifact_error", err)
            store.merge_meta(uid, "output_path", None)
            logger.warning("AI artifact generation failed for job %s: %s", job_id, err)

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
