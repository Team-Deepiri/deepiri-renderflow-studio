from __future__ import annotations

import json
import logging
import threading
import time
from queue import Empty, Queue
from uuid import UUID

from app.config import Settings
from app.job_store import AiJobRecord, JobStatus, store
from renderflow_queue import (
    REDIS_KEY_JOBS,
    JobStatusReporter,
    RedisJobQueue,
    RfirJobState,
    RfirJobStatus,
    stage_for_op,
)
from app.stage_runner import run_audio_stages, run_scene_stages
from app.api.utils import get_event_emitter
from app.paths import data_subdir, is_persisted_output

from pathlib import Path
import subprocess, shutil

logger = logging.getLogger(__name__)

_local_pending: Queue[str] = Queue()
_stop = threading.Event()
_worker_thread: threading.Thread | None = None
_cancelled_jobs: set[str] = set()


class _JobCancelled(BaseException):
    """Raised from inside the RFIR executor callback to abort a cancelled job.

    Derives from BaseException so it can't be swallowed by the pipeline's
    `except Exception` error handling on its way back to _process_job.
    """

# Job IDs dispatched to model-workers over Redis, awaiting status mirroring.
# Separate from `_cancelled_jobs`/`_local_pending`, which are the legacy
# in-process stub's bookkeeping.
_rfir_inflight: set[str] = set()
_rfir_lock = threading.Lock()


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


def _build_rfir_payload(rec: AiJobRecord, settings: Settings) -> dict[str, object]:
    """Build the Redis job payload consumed by model-workers' redis_worker.py.

    Carries everything the worker needs to plan, compile, and execute the
    RFIR graph in its own process — the orchestrator never imports
    `app.rfir` itself (see rfir_preview.py for why that's impossible).
    """
    return {
        "prompt": rec.prompt,
        "mode": rec.mode,
        "budget": {
            "max_gpu_seconds": settings.rfir_max_gpu_sec,
            "max_tier": settings.rfir_max_tier,
        },
        "guardrail_verdict": rec.metadata.get("guardrail_verdict", "allow"),
        "guardrail_flags": rec.metadata.get("guardrail_flags", []),
        "nsfw_mode": rec.metadata.get("nsfw_mode", "block"),
        "project": {
            "fps_num": 24,
            "fps_den": 1,
            "resolution_w": 1920,
            "resolution_h": 1080,
        },
    }


def enqueue_job(job_id: str, settings: Settings) -> None:
    _cancelled_jobs.discard(job_id)

    if settings.rfir_enabled and settings.redis_url:
        try:
            import redis

            r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            uid = UUID(job_id)
            rec = store.get(uid)
            if rec is None:
                logger.error("enqueue_job: RFIR job %s not found in store", job_id)
                return
            payload = _build_rfir_payload(rec, settings)
            RedisJobQueue(r).push_job(job_id, payload)
            with _rfir_lock:
                _rfir_inflight.add(job_id)
            logger.info("dispatched RFIR job %s to model-workers", job_id)
            return
        except Exception as e:
            logger.warning("RFIR dispatch failed for %s, falling back to stub pipeline: %s", job_id, e)
    elif settings.rfir_enabled and not settings.redis_url:
        logger.warning(
            "RENDERFLOW_RFIR_ENABLED=true but REDIS_URL is not set — "
            "no channel to model-workers; falling back to the stub pipeline for job %s",
            job_id,
        )

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
    elif rec.mode == "scene" and settings.rfir_enabled:
        # RFIR is on but this job wasn't dispatched to model-workers (no
        # Redis, or dispatch failed) — run the real pipeline in-process
        # instead of the stub stages.
        _process_scene_job_rfir(uid, rec, settings)
        return
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


def _process_scene_job_rfir(uid: UUID, rec: AiJobRecord, settings: Settings) -> None:
    """Run a scene job through the real RFIR pipeline in-process (§1.14).

    Stages mirror the actual graph execution (compiling, generating_keyframe,
    estimating_depth, rendering_frames, muxing). Any failure — RFIR bridge
    unavailable, missing ML runtime/weights, no ffmpeg — lands the job in
    FAILED with metadata["error"] explaining why.
    """
    job_id = str(uid)
    pid = str(rec.project_id)
    stages: list[str] = ["preparing"]

    def _advance(stage: str) -> None:
        if job_id in _cancelled_jobs:
            raise _JobCancelled()
        if stage == stages[-1]:
            return
        stages.append(stage)
        snapshot = list(stages)
        store.update_status(uid, JobStatus.RUNNING, stages=snapshot)
        store.set_stages(uid, snapshot, completed_through=len(snapshot) - 2)
        _emit(job_id, "running", stage=stage, project_id=pid)

    def _on_node_start(node) -> None:
        _advance(stage_for_op(node.op))

    def _fail(error: str) -> None:
        logger.warning("RFIR job %s failed: %s", job_id, error)
        store.merge_meta(uid, "error", error)
        store.update_status(uid, JobStatus.FAILED, stages=stages + ["failed"])
        _emit(job_id, "failed", project_id=pid)

    try:
        from app.media.cfsv_pipeline import compile_and_run_tier_a
    except (ImportError, ModuleNotFoundError) as e:
        _fail(f"RFIR unavailable in this environment: {e}")
        return

    out_dir = data_subdir("render_outputs", settings) / job_id

    try:
        _advance("compiling")
        result = compile_and_run_tier_a(
            rec.prompt,
            str(out_dir),
            job_id=job_id,
            max_gpu_sec=settings.rfir_max_gpu_sec,
            max_tier=settings.rfir_max_tier,
            on_node_start=_on_node_start,
        )
    except _JobCancelled:
        store.update_status(uid, JobStatus.CANCELLED, stages=stages + ["cancelled"])
        _emit(job_id, "cancelled", project_id=pid)
        return
    except Exception as e:
        _fail(f"RFIR pipeline crashed: {e}")
        return

    if not result.get("ok"):
        _fail(str(result.get("error", "RFIR pipeline failed")))
        return

    store.merge_meta(uid, "output_path", result["output_path"])
    store.merge_meta(uid, "artifacts", {
        "output_mp4": result["output_path"],
        "keyframes": result.get("keyframes", []),
        "graph_uri": result.get("graph_uri"),
    })
    store.merge_meta(uid, "rfir_metrics", result.get("metrics", {}))

    stages.append("review")
    snapshot = list(stages)
    store.set_stages(uid, snapshot, completed_through=len(snapshot) - 1)
    store.update_status(uid, JobStatus.REVIEW, stages=snapshot)
    _emit(job_id, "review", project_id=pid)


def _apply_rfir_status(uid: UUID, rec: AiJobRecord, status: RfirJobStatus) -> None:
    """Mirror a model-workers status report into the orchestrator's job_store."""
    pid = str(rec.project_id)

    if status.state == RfirJobState.PREPARING:
        store.update_status(uid, JobStatus.PREPARING, stages=["preparing"])
        _emit(str(uid), "preparing", project_id=pid)
    elif status.state == RfirJobState.RUNNING:
        stage_name = status.stage or "running"
        stages = rec.stages if stage_name in rec.stages else rec.stages + [stage_name]
        store.update_status(uid, JobStatus.RUNNING, stages=stages)
        for k, v in status.metadata.items():
            store.merge_meta(uid, k, v)
        _emit(str(uid), "running", stage=stage_name, project_id=pid)
    elif status.state == RfirJobState.REVIEW:
        out = (status.artifacts or {}).get("output_mp4")
        if not is_persisted_output(out):
            store.merge_meta(uid, "error", f"worker reported no readable output (output_mp4={out!r})")
            store.update_status(uid, JobStatus.FAILED, stages=rec.stages + ["failed"])
            _emit(str(uid), "failed", project_id=pid)
            return

        store.merge_meta(uid, "artifacts", status.artifacts)
        store.merge_meta(uid, "output_path", str(Path(out).resolve()))
        if status.metrics:
            store.merge_meta(uid, "rfir_metrics", status.metrics)
        store.update_status(uid, JobStatus.REVIEW, stages=rec.stages + ["review"])
        _emit(str(uid), "review", project_id=pid)
    elif status.state == RfirJobState.FAILED:
        store.update_status(uid, JobStatus.FAILED, stages=rec.stages + ["failed"])
        if status.error:
            store.merge_meta(uid, "error", status.error)
        _emit(str(uid), "failed", project_id=pid)


def _rfir_status_loop(settings: Settings) -> None:
    """Poll Redis for status reports from model-workers and mirror them.

    The orchestrator does NOT consume REDIS_KEY_JOBS in this mode — model-
    workers' redis_worker.py is the sole consumer of RFIR jobs, avoiding two
    processes racing to blpop the same queue.
    """
    import redis

    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    reporter = JobStatusReporter(r)
    logger.info("worker in RFIR dispatch mode: mirroring status via Redis")

    while not _stop.is_set():
        with _rfir_lock:
            job_ids = list(_rfir_inflight)

        if not job_ids:
            time.sleep(0.5)
            continue

        for job_id in job_ids:
            if job_id in _cancelled_jobs:
                with _rfir_lock:
                    _rfir_inflight.discard(job_id)
                continue
            try:
                uid = UUID(job_id)
            except ValueError:
                with _rfir_lock:
                    _rfir_inflight.discard(job_id)
                continue

            rec = store.get(uid)
            if rec is None:
                with _rfir_lock:
                    _rfir_inflight.discard(job_id)
                continue

            status = reporter.get_status(job_id)
            if status is None:
                continue

            _apply_rfir_status(uid, rec, status)

            if status.is_terminal:
                with _rfir_lock:
                    _rfir_inflight.discard(job_id)
                reporter.clear_status(job_id)

        time.sleep(0.5)


def _loop(settings: Settings) -> None:
    if settings.rfir_enabled and settings.redis_url:
        try:
            _rfir_status_loop(settings)
            return
        except Exception as e:
            logger.warning("RFIR status loop failed, falling back to stub pipeline: %s", e)

    if settings.redis_url:
        try:
            import redis

            r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            logger.info("worker using Redis queue %s", REDIS_KEY_JOBS)
            while not _stop.is_set():
                try:
                    item = r.blpop(REDIS_KEY_JOBS, timeout=2)
                except redis.exceptions.TimeoutError:
                    # Socket-level read timeout — equivalent to blpop's own
                    # timeout elapsing with no item. Keep polling rather than
                    # falling all the way back to the in-process queue.
                    continue
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
