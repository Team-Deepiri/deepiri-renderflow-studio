from __future__ import annotations

import argparse
import logging
import os
import time
import traceback
from pathlib import Path

from renderflow_queue import (
    REDIS_KEY_T2V_OPS,
    T2VRemoteRequest,
    T2VRemoteResult,
    expected_latent_shape,
    publish_t2v_result,
    touch_t2v_heartbeat,
)

logger = logging.getLogger(__name__)


def _artifact_dir() -> Path:
    root = os.environ.get("RENDERFLOW_RFIR_T2V_ARTIFACT_DIR", "/tmp/rfir-t2v")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _uri_for(path: Path) -> str:
    return path.resolve().as_uri()


def handle_request(req: T2VRemoteRequest, artifact_dir: Path) -> T2VRemoteResult:
    """Create a fake latent tensor and return an ok result."""
    import torch

    shape = expected_latent_shape(req.width, req.height, req.num_frames)
    logger.info(
        "STUB generating fake latents shape=%s for op_id=%s (prompt=%r)",
        shape, req.op_id, req.prompt[:80],
    )

    # Deterministic-ish noise so re-runs are inspectable.
    gen = torch.Generator().manual_seed(req.seed if req.seed is not None else 0)
    latents = torch.randn(shape, generator=gen, dtype=torch.float16)

    out_dir = artifact_dir / req.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{req.op_id}.pt"
    torch.save(latents, out_path)

    return T2VRemoteResult.ok(
        job_id=req.job_id,
        op_id=req.op_id,
        latent_uri=_uri_for(out_path),
        latent_shape=shape,
        dtype="float16",
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    p = argparse.ArgumentParser(description="Stub remote T2V worker (fake Wan latents)")
    p.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0"),
    )
    p.add_argument(
        "--artifact-dir",
        default=os.environ.get("RENDERFLOW_RFIR_T2V_ARTIFACT_DIR", "/tmp/rfir-t2v"),
    )
    args = p.parse_args()

    import redis

    r = redis.Redis.from_url(args.redis_url, decode_responses=True)
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    logger.info("T2V STUB listening on %s key=%s", args.redis_url, REDIS_KEY_T2V_OPS)
    logger.info("artifacts → %s", artifact_dir.resolve())
    touch_t2v_heartbeat(r, worker_id="stub")

    while True:
        try:
            # Refresh liveness before blocking so local model-workers can
            # detect this process even while idle waiting for jobs.
            touch_t2v_heartbeat(r, worker_id="stub")
            item = r.blpop(REDIS_KEY_T2V_OPS, timeout=5)
        except redis.exceptions.TimeoutError:
            continue
        except redis.exceptions.ConnectionError as e:
            logger.warning("redis connection error, retrying: %s", e)
            time.sleep(1.0)
            continue

        if not item:
            continue

        _, raw = item
        try:
            req = T2VRemoteRequest.from_json(raw)
        except Exception as e:
            logger.error("malformed T2V request, skipping: %s (%s)", raw[:200], e)
            continue

        logger.info(
            "RECEIVED T2V request job_id=%s op_id=%s %dx%d frames=%d steps=%d prompt=%r",
            req.job_id, req.op_id, req.width, req.height, req.num_frames, req.steps,
            req.prompt[:80],
        )

        try:
            result = handle_request(req, artifact_dir)
            publish_t2v_result(r, result)
            logger.info(
                "PUBLISHED ok op_id=%s latent_uri=%s shape=%s",
                result.op_id, result.latent_uri, result.latent_shape,
            )
        except Exception as e:
            logger.error("stub failed for op_id=%s: %s\n%s", req.op_id, e, traceback.format_exc())
            publish_t2v_result(
                r,
                T2VRemoteResult.fail(job_id=req.job_id, op_id=req.op_id, error=str(e)),
            )


if __name__ == "__main__":
    main()
