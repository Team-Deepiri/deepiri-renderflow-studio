"""Smoke client: enqueue one T2VRemoteRequest and wait for the remote worker.

Requires:
  - Redis (e.g. docker compose redis on 6380)
  - ``python -m app.t2v_remote_worker`` (or stub) listening with a healthy artifact store
  - Matching ``RENDERFLOW_ARTIFACT_*`` on this client so download works

    cd services/model-workers
    REDIS_URL=redis://127.0.0.1:6380/0 \\
    RENDERFLOW_ARTIFACT_STORE=gdrive \\
    RENDERFLOW_ARTIFACT_ROOT=<folder-id> \\
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \\
    poetry run python -m app.t2v_remote_smoke --timeout 900
"""
from __future__ import annotations

import argparse
import logging
import os
import uuid

from renderflow_queue import (
    T2VRemoteRequest,
    T2VRemoteStatus,
    enqueue_t2v_request,
    expected_latent_shape,
    wait_t2v_result,
)

from app.artifact_store import download_to_temp, get_artifact_store

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    p = argparse.ArgumentParser(description="Enqueue a smoke T2V remote request")
    p.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0"))
    p.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("RENDERFLOW_T2V_SMOKE_TIMEOUT", "900")),
        help="Seconds to wait for worker result (Wan can take several minutes)",
    )
    p.add_argument("--width", type=int, default=336)
    p.add_argument("--height", type=int, default=144)
    p.add_argument("--num-frames", type=int, default=21)
    p.add_argument("--steps", type=int, default=12)
    p.add_argument("--full-frame", action="store_true", default=True)
    p.add_argument("--no-full-frame", action="store_false", dest="full_frame")
    args = p.parse_args()

    import redis
    import torch

    store = get_artifact_store()
    if not store.healthcheck():
        raise SystemExit(
            "artifact store healthcheck failed — set RENDERFLOW_ARTIFACT_STORE/ROOT "
            "(and credentials for gdrive) so smoke can download the result URI"
        )

    r = redis.Redis.from_url(args.redis_url, decode_responses=True)
    job_id = f"smoke-{uuid.uuid4().hex[:8]}"
    op_id = "s0_t2v"

    req = T2VRemoteRequest(
        job_id=job_id,
        op_id=op_id,
        prompt="smoke test: fish leaping from water",
        width=args.width,
        height=args.height,
        num_frames=args.num_frames,
        steps=args.steps,
        full_frame=args.full_frame,
        seed=0,
    )
    expect = expected_latent_shape(req.width, req.height, req.num_frames)

    logger.info("ENQUEUE job_id=%s op_id=%s expect_shape=%s → Redis", job_id, op_id, expect)
    enqueue_t2v_request(r, req)

    result = wait_t2v_result(r, op_id, timeout_sec=args.timeout)
    logger.info(
        "GOT status=%s uri=%s shape=%s",
        result.status.value,
        result.latent_uri,
        result.latent_shape,
    )

    if result.status != T2VRemoteStatus.OK:
        raise SystemExit(f"worker returned error: {result.error}")

    local_path = download_to_temp(store, result.latent_uri or "")
    try:
        latents = torch.load(local_path, map_location="cpu", weights_only=True)
    finally:
        local_path.unlink(missing_ok=True)

    logger.info(
        "LOADED tensor shape=%s dtype=%s from %s",
        list(latents.shape),
        latents.dtype,
        result.latent_uri,
    )

    if list(latents.shape) != expect:
        raise SystemExit(f"shape mismatch: got {list(latents.shape)} expected {expect}")

    print("SMOKE OK — remote worker returned Wan latents")


if __name__ == "__main__":
    main()
