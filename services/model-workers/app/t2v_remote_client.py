"""Client helpers: enqueue remote sparse T2V and load latents via ArtifactStore."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def remote_t2v_available() -> bool:
    from app.cloud_probe import get_cloud_defaults

    return bool(get_cloud_defaults().cloud_allowed)


def run_remote_sparse_t2v(
    *,
    job_id: str,
    op_id: str,
    prompt: str,
    width: int,
    height: int,
    num_frames: int,
    steps: int,
    window_size: int,
    overlap: int,
    full_frame: bool,
    seed: int | None = None,
    redis_url: str | None = None,
    timeout_sec: float = 600.0,
) -> Any:
    """Enqueue a remote T2V op, wait for result, download latents, return tensor.

    Raises on failure so the caller can fall back to local inference.
    """
    import torch
    import redis
    from renderflow_queue import (
        T2VRemoteRequest,
        T2VRemoteStatus,
        enqueue_t2v_request,
        wait_t2v_result,
    )
    from app.artifact_store import download_to_temp, get_artifact_store

    url = redis_url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0")
    r = redis.Redis.from_url(url, decode_responses=True)

    req = T2VRemoteRequest(
        job_id=job_id or f"job-{uuid.uuid4().hex[:8]}",
        op_id=op_id,
        prompt=prompt,
        width=width,
        height=height,
        num_frames=num_frames,
        steps=steps,
        window_size=window_size,
        overlap=overlap,
        full_frame=full_frame,
        seed=seed,
    )
    logger.info(
        "remote T2V enqueue job_id=%s op_id=%s %dx%d frames=%d",
        req.job_id, req.op_id, width, height, num_frames,
    )
    enqueue_t2v_request(r, req)
    result = wait_t2v_result(r, req.op_id, timeout_sec=timeout_sec)
    if result.status != T2VRemoteStatus.OK or not result.latent_uri:
        raise RuntimeError(result.error or "remote T2V failed without error detail")

    store = get_artifact_store()
    local_path = download_to_temp(store, result.latent_uri)
    try:
        latents = torch.load(local_path, map_location="cpu", weights_only=True)
    finally:
        local_path.unlink(missing_ok=True)

    if not isinstance(latents, torch.Tensor):
        raise TypeError(f"expected Tensor latents, got {type(latents)}")
    return latents
