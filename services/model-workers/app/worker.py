from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any
import os
import signal
import sys
import threading
import time
import logging
from concurrent.futures import ProcessPoolExecutor, Future
from queue import Queue
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    IDLE = "idle"
    BUSY = "busy"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class StageResult:
    stage: str
    status: str
    payload: dict[str, Any]


@dataclass
class WorkerMetrics:
    jobs_processed: int = 0
    jobs_failed: int = 0
    total_processing_time_ms: int = 0
    avg_processing_time_ms: float = 0.0


@dataclass
class WorkerConfig:
    max_workers: int = 4
    job_timeout_seconds: int = 300
    graceful_shutdown_timeout: int = 30


class WorkerPool:
    def __init__(self, config: WorkerConfig | None = None):
        self.config = config or WorkerConfig()
        self._executor = ProcessPoolExecutor(max_workers=self.config.max_workers)
        self._pending_jobs: Queue[tuple[str, str, Future]] = Queue()
        self._state = WorkerState.IDLE
        self._metrics = WorkerMetrics()
        self._stop_event = threading.Event()
        self._stats_lock = threading.Lock()
        
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown")
        self._state = WorkerState.SHUTTING_DOWN
        self._stop_event.set()

    def submit_job(self, job_id: str, prompt: str) -> str:
        future = self._executor.submit(run_scene_job, prompt)
        self._pending_jobs.put((job_id, prompt, future))
        self._state = WorkerState.BUSY
        return job_id

    def get_job_result(self, job_id: str, timeout: float = 1.0) -> list[StageResult] | None:
        for jid, prompt, future in list(self._pending_jobs.queue):
            if jid == job_id:
                try:
                    result = future.result(timeout=timeout)
                    self._update_metrics_success(timeout * 1000)
                    return result
                except Exception as e:
                    logger.error(f"Job {job_id} failed: {e}")
                    self._update_metrics_failure()
                    return None
        return None

    def _update_metrics_success(self, processing_time_ms: float):
        with self._stats_lock:
            self._metrics.jobs_processed += 1
            self._metrics.total_processing_time_ms += int(processing_time_ms)
            self._metrics.avg_processing_time_ms = (
                self._metrics.total_processing_time_ms / self._metrics.jobs_processed
            )

    def _update_metrics_failure(self):
        with self._stats_lock:
            self._metrics.jobs_failed += 1

    def get_metrics(self) -> WorkerMetrics:
        with self._stats_lock:
            return WorkerMetrics(
                jobs_processed=self._metrics.jobs_processed,
                jobs_failed=self._metrics.jobs_failed,
                total_processing_time_ms=self._metrics.total_processing_time_ms,
                avg_processing_time_ms=self._metrics.avg_processing_time_ms,
            )

    def shutdown(self, wait: bool = True):
        self._executor.shutdown(wait=wait)
        logger.info("Worker pool shutdown complete")


_global_pool: WorkerPool | None = None


def get_worker_pool() -> WorkerPool:
    global _global_pool
    if _global_pool is None:
        _global_pool = WorkerPool()
    return _global_pool


def run_scene_job(prompt: str) -> list[StageResult]:
    now = datetime.now(UTC).isoformat()
    return [
        StageResult("storyboard", "ok", {"prompt": prompt, "created_at": now}),
        StageResult("layout", "ok", {"shots": 4}),
        StageResult("assets", "ok", {"generated_assets": 6}),
    ]


def run_animation_job(prompt: str, duration_frames: int = 120) -> list[StageResult]:
    now = datetime.now(UTC).isoformat()
    return [
        StageResult("keyframes", "ok", {"prompt": prompt, "duration_frames": duration_frames, "created_at": now}),
        StageResult("inbetween", "ok", {"frames_generated": duration_frames - 1}),
        StageResult("render", "ok", {"output_frames": duration_frames}),
    ]


def run_voiceover_job(text: str, voice: str = "default") -> list[StageResult]:
    now = datetime.now(UTC).isoformat()
    return [
        StageResult("tts", "ok", {"text": text, "voice": voice, "created_at": now}),
        StageResult("audio", "ok", {"duration_seconds": len(text) * 0.3}),
    ]


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Renderflow Model Worker")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--job-timeout", type=int, default=300)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    pool = WorkerPool(WorkerConfig(
        max_workers=args.max_workers,
        job_timeout_seconds=args.job_timeout,
    ))

    job_id = pool.submit_job("test-job-001", "Create a rainy neon alley intro shot")
    print(f"Submitted job: {job_id}")

    result = pool.get_job_result(job_id, timeout=30.0)
    if result:
        print(f"Job result: {result}")
    
    print(f"Metrics: {pool.get_metrics()}")
    pool.shutdown()
