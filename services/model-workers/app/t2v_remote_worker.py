"""Remote T2V worker: Redis ops queue → Wan sparse T2V → ArtifactStore → result key.

Run on a CUDA host (e.g. Colab) with shared Redis + artifact store:

    REDIS_URL=redis://... \\
    RENDERFLOW_ARTIFACT_STORE=r2 \\
    RENDERFLOW_ARTIFACT_ROOT=<bucket-name> \\
    RENDERFLOW_R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com \\
    RENDERFLOW_R2_ACCESS_KEY_ID=<access-key> \\
    RENDERFLOW_R2_SECRET_ACCESS_KEY=<secret-key> \\
    poetry run python -m app.t2v_remote_worker

Local model-workers enqueue via ``t2v_remote_client`` when cloud probe succeeds.
"""
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
    publish_t2v_result,
    touch_t2v_heartbeat,
)

from app.artifact_store import get_artifact_store

logger = logging.getLogger(__name__)

WORKER_ID = "wan"


def _scratch_dir() -> Path:
    """Local scratch before put() into the configured artifact store."""
    explicit = os.environ.get("RENDERFLOW_RFIR_T2V_ARTIFACT_DIR")
    if explicit:
        path = Path(explicit)
    elif (os.environ.get("RENDERFLOW_ARTIFACT_STORE") or "").strip().lower() == "local":
        root = os.environ.get("RENDERFLOW_ARTIFACT_ROOT") or "/tmp/rfir-t2v"
        path = Path(root) / ".scratch"
    else:
        path = Path("/tmp/rfir-t2v")
    path.mkdir(parents=True, exist_ok=True)
    return path


def handle_request(req: T2VRemoteRequest, scratch_dir: Path) -> T2VRemoteResult:
    """Run Wan sparse T2V, put latents via ArtifactStore, return ok result."""
    import torch
    from PIL import Image

    from app.rfir.ops import sparse_t2v_window

    # Size cue for sparse_t2v_window.run (uses image.width/height when no ROI mask).
    image = Image.new("RGB", (req.width, req.height), color=(0, 0, 0))
    shot_id = req.op_id.split("_")[0] if "_" in req.op_id else req.op_id

    logger.info(
        "Wan T2V op_id=%s %dx%d frames=%d steps=%d full_frame=%s prompt=%r",
        req.op_id,
        req.width,
        req.height,
        req.num_frames,
        req.steps,
        req.full_frame,
        req.prompt[:80],
    )

    result = sparse_t2v_window.run(
        prompt=req.prompt,
        image=image,
        full_frame=req.full_frame,
        steps=req.steps,
        window_size=req.window_size,
        overlap=req.overlap,
        num_frames=req.num_frames,
        shot_id=shot_id,
    )

    if result is None or result.latents is None:
        raise RuntimeError(
            f"sparse_t2v_window produced no latents for op_id={req.op_id!r} "
            "(model missing or all windows failed)"
        )

    latents = result.latents.detach().cpu()
    shape = list(latents.shape)
    dtype_name = str(latents.dtype).replace("torch.", "")

    out_dir = scratch_dir / req.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{req.op_id}.pt"
    torch.save(latents, out_path)

    key = f"{req.job_id}/{req.op_id}.pt"
    store = get_artifact_store()
    latent_uri = store.put(key, out_path)
    logger.info("put key=%s → %s shape=%s dtype=%s", key, latent_uri, shape, dtype_name)

    return T2VRemoteResult.ok(
        job_id=req.job_id,
        op_id=req.op_id,
        latent_uri=latent_uri,
        latent_shape=shape,
        dtype=dtype_name,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    p = argparse.ArgumentParser(description="Remote T2V worker (Wan sparse latents)")
    p.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0"),
    )
    p.add_argument(
        "--artifact-dir",
        default=os.environ.get("RENDERFLOW_RFIR_T2V_ARTIFACT_DIR", "/tmp/rfir-t2v"),
    )
    p.add_argument(
        "--worker-id",
        default=os.environ.get("RENDERFLOW_T2V_WORKER_ID", WORKER_ID),
        help="Value written to the T2V heartbeat key",
    )
    args = p.parse_args()

    import redis

    r = redis.Redis.from_url(args.redis_url, decode_responses=True)
    if args.artifact_dir:
        os.environ.setdefault("RENDERFLOW_RFIR_T2V_ARTIFACT_DIR", args.artifact_dir)
    scratch_dir = _scratch_dir()
    worker_id = args.worker_id

    store = get_artifact_store()
    if not store.healthcheck():
        logger.warning(
            "artifact store healthcheck failed — worker will still listen, "
            "but put() may fail until RENDERFLOW_ARTIFACT_* is set"
        )

    logger.info("T2V worker listening on %s key=%s id=%s", args.redis_url, REDIS_KEY_T2V_OPS, worker_id)
    logger.info("scratch → %s", scratch_dir.resolve())
    touch_t2v_heartbeat(r, worker_id=worker_id)

    while True:
        try:
            touch_t2v_heartbeat(r, worker_id=worker_id)
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
            req.job_id,
            req.op_id,
            req.width,
            req.height,
            req.num_frames,
            req.steps,
            req.prompt[:80],
        )

        try:
            result = handle_request(req, scratch_dir)
            publish_t2v_result(r, result)
            logger.info(
                "PUBLISHED ok op_id=%s latent_uri=%s shape=%s",
                result.op_id,
                result.latent_uri,
                result.latent_shape,
            )
        except Exception as e:
            logger.error("worker failed for op_id=%s: %s\n%s", req.op_id, e, traceback.format_exc())
            publish_t2v_result(
                r,
                T2VRemoteResult.fail(job_id=req.job_id, op_id=req.op_id, error=str(e)),
            )


if __name__ == "__main__":
    main()
