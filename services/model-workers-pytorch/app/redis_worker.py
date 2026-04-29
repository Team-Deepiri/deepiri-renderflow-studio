"""
Consume AI job IDs from Redis (same queue as orchestrator worker) for heavy PyTorch work.

Run from services/model-workers-pytorch after: poetry install && poetry run python -m app.redis_worker
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

from renderflow_queue import REDIS_KEY_JOBS

_wpath = Path(__file__).resolve().parent / "worker.py"
_spec = importlib.util.spec_from_file_location("renderflow_model_worker", _wpath)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
run_scene_job = _mod.run_scene_job


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0"))
    args = p.parse_args()
    import redis

    r = redis.Redis.from_url(args.redis_url, decode_responses=True)
    print(f"listening {REDIS_KEY_JOBS} on {args.redis_url}", flush=True)
    while True:
        item = r.blpop(REDIS_KEY_JOBS, timeout=5)
        if not item:
            continue
        _, raw = item
        try:
            data = json.loads(raw)
            job_id = data.get("job_id", "")
            prompt = (data.get("payload") or {}).get("prompt", "redis job")
        except json.JSONDecodeError:
            job_id = str(raw)
            prompt = "redis job"
        print(f"job {job_id}: running local scene stages (stub)", flush=True)
        for stage in run_scene_job(prompt):
            print(stage, flush=True)
            time.sleep(0.05)


if __name__ == "__main__":
    main()
