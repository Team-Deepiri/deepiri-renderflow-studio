"""Smoke client: enqueue one T2VRemoteRequest and wait for the stub worker.

Requires:
  - Redis (e.g. docker compose redis on 6380)
  - ``python -m app.t2v_remote_stub_worker`` running in another terminal

    cd services/model-workers
    REDIS_URL=redis://127.0.0.1:6380/0 poetry run python -m app.t2v_remote_smoke
"""
from __future__ import annotations

import argparse
import logging
import os
import uuid
from urllib.parse import urlparse
from urllib.request import url2pathname

from renderflow_queue import (
    T2VRemoteRequest,
    T2VRemoteStatus,
    enqueue_t2v_request,
    expected_latent_shape,
    wait_t2v_result,
)

logger = logging.getLogger(__name__)


def _path_from_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return url2pathname(parsed.path)
    return uri


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    p = argparse.ArgumentParser(description="Enqueue a smoke T2V remote request")
    p.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0"))
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--width", type=int, default=336)
    p.add_argument("--height", type=int, default=144)
    p.add_argument("--num-frames", type=int, default=21)
    args = p.parse_args()

    import redis
    import torch

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
        steps=12,
        seed=0,
    )
    expect = expected_latent_shape(req.width, req.height, req.num_frames)

    logger.info("ENQUEUE job_id=%s op_id=%s expect_shape=%s → Redis", job_id, op_id, expect)
    enqueue_t2v_request(r, req)

    result = wait_t2v_result(r, op_id, timeout_sec=args.timeout)
    logger.info("GOT status=%s uri=%s shape=%s", result.status.value, result.latent_uri, result.latent_shape)

    if result.status != T2VRemoteStatus.OK:
        raise SystemExit(f"stub returned error: {result.error}")

    path = _path_from_uri(result.latent_uri or "")
    latents = torch.load(path, map_location="cpu", weights_only=True)
    logger.info("LOADED tensor shape=%s dtype=%s from %s", list(latents.shape), latents.dtype, path)

    if list(latents.shape) != expect:
        raise SystemExit(f"shape mismatch: got {list(latents.shape)} expected {expect}")

    print("SMOKE OK — stub received request and returned latents")


if __name__ == "__main__":
    main()
