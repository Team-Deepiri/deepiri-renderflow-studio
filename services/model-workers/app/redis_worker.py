"""
Consume AI job IDs from Redis (same queue as orchestrator) and run the real
RFIR pipeline: plan shots -> compile graph -> execute -> report status back.

The orchestrator cannot import app.rfir directly (package name collision —
both services use the top-level name `app`), so this process is the sole
owner of RFIR execution. Status/results are written to Redis via
`renderflow_queue.JobStatusReporter` for the orchestrator's worker_loop to
mirror into its own job_store.

Run from services/model-workers after: poetry install && poetry run python -m app.redis_worker
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import traceback
from pathlib import Path

from renderflow_queue import JobStatusReporter, REDIS_KEY_JOBS, RfirJobState, RfirJobStatus

from app.guardrails.plan_client import PlanBlocked, check_plan

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "orchestrator" / "data" / "render_outputs"


def _output_dir(job_id: str) -> Path:
    root = os.environ.get("RENDERFLOW_RENDER_OUTPUT_DIR")
    base = Path(root) if root else DEFAULT_OUTPUT_ROOT
    return base / job_id


def _checkpoint_dir() -> str:
    return os.environ.get("RENDERFLOW_CHECKPOINT_DIR", "/tmp/rfir-checkpoints")


def _plan_shots(prompt: str, max_tier):
    """Plan shots via Qwen; fall back to a single Tier-A shot if the planner
    model isn't available (no GGUF weights downloaded yet, etc.).
    """
    from app.rfir import planner
    from app.rfir.ir.types import CameraMotion, CameraPath, Shot, ShotList, Tier

    try:
        return planner.plan(prompt, guardrail=lambda p: True, max_tier=max_tier)
    except planner.PlannerBlocked: 
        raise
    except Exception as e:
        logger.warning("planner unavailable (%s) — falling back to a single Tier-A shot", e)
        return ShotList(prompt=prompt, shots=[
            Shot(index=0, description=prompt, tier=Tier.A, duration_sec=5.0,
                 camera=CameraPath(motion=CameraMotion.ZOOM, speed=1.0)),
        ])


def _apply_tier_adjustments(shot_list, adjusted: list[dict]) -> None:
    """Write the plan gate's tier downgrades back onto the ShotList.

    The gate caps against the project's policy.max_tier, which can be stricter
    than the budget max_tier the planner already applied via assign_tiers().
    Per §6 the plan gate is authoritative, so its result wins.
    """
    from app.rfir.ir.types import Tier

    for shot, entry in zip(shot_list.shots, adjusted):
        raw = str(entry.get("tier", "")).upper()
        if not raw or raw == shot.tier.value:
            continue
        try:
            shot.tier = Tier[raw]
        except KeyError:
            logger.warning("plan gate returned unknown tier %r; keeping %s", raw, shot.tier.value)


def _warmup() -> None:
    """Run one tiny throwaway generation at startup so the Metal/CUDA JIT
    shader compilation (~200s cold on MPS) happens once when the worker
    boots, not on the user's first job. Models stay resident afterwards.

    Disable with RENDERFLOW_RFIR_WARMUP=0 (e.g. in tests or CI where model
    weights aren't available).
    """
    if os.environ.get("RENDERFLOW_RFIR_WARMUP", "1") != "1":
        logger.info("warmup disabled via RENDERFLOW_RFIR_WARMUP")
        return

    from app.rfir.ops import t2i_keyframe

    logger.info("warmup: compiling t2i pipeline (first run may take minutes)...")
    t0 = time.monotonic()
    try:
        t2i_keyframe.run("warmup", width=512, height=288, steps=1, seed=0)
        logger.info("warmup: done in %.1fs — models resident, JIT compiled", time.monotonic() - t0)
    except Exception as e:
        logger.warning("warmup failed (%s) — first job will pay the JIT cost instead", e)


def run_rfir_job(job_id: str, payload: dict, reporter: JobStatusReporter) -> None:
    """Run the full RFIR pipeline for one job: plan -> compile -> execute."""
    from app.rfir.ir.types import InferenceBudget, Tier
    from app.rfir.compiler.builder import build, CompileError
    from app.rfir.compiler.fusion import fuse
    from app.rfir.compiler.memory_plan import plan as memory_plan
    from app.rfir.executor.engine import run_graph

    prompt = payload.get("prompt", "")
    guardrail_verdict = payload.get("guardrail_verdict", "allow")

    if guardrail_verdict != "allow":
        logger.warning("job %s: refusing — guardrail_verdict=%r (not 'allow')", job_id, guardrail_verdict)
        reporter.set_status(RfirJobStatus(
            job_id=job_id, state=RfirJobState.FAILED,
            error=f"guardrail_verdict={guardrail_verdict!r}, refusing to run GPU work",
        ))
        return

    budget_cfg = payload.get("budget") or {}
    try:
        max_tier = Tier[str(budget_cfg.get("max_tier", "C")).upper()]
    except KeyError:
        max_tier = Tier.C
    budget = InferenceBudget(
        max_gpu_seconds=float(budget_cfg.get("max_gpu_seconds", 120.0)),
        max_tier=max_tier,
    )

    reporter.set_status(RfirJobStatus(job_id=job_id, state=RfirJobState.PREPARING))
    logger.info("job %s: planning shots for prompt=%r", job_id, prompt[:60])

    try:
        shot_list = _plan_shots(prompt, max_tier)

        # Layer 2 (§6) — the planner's shot descriptions become the per-node
        # generation prompts, so they get their own pass before compile.
        # Runs before the storyboard status so a blocked plan never surfaces
        # a shot count to the review UI.
        _apply_tier_adjustments(shot_list, check_plan(job_id, shot_list))

        reporter.set_status(RfirJobStatus(
            job_id=job_id, state=RfirJobState.RUNNING, stage="storyboard",
            metadata={"stage_storyboard": {"shot_count": len(shot_list.shots)}},
        ))

        graph = build(shot_list, budget=budget, ai_enabled=True)
        graph = fuse(graph)
        mp = memory_plan(graph)
        graph.metadata["downgrade_hints"] = mp.downgrade_hints

        reporter.set_status(RfirJobStatus(
            job_id=job_id, state=RfirJobState.RUNNING, stage="asset_generation",
            metadata={"stage_layout": {"shots": len(shot_list.shots),
                                        "tier_distribution": graph.metadata.get("tier_distribution", {})}},
        ))

        out_dir = _output_dir(job_id)
        ctx = run_graph(graph, job_id=job_id, output_dir=str(out_dir),
                         budget=budget, checkpoint_dir=_checkpoint_dir())

        metrics = ctx.to_metrics_dict()
        artifacts = {k: v for k, v in ctx.artifacts.items() if k == "output_mp4" or v.endswith(".mp4")}
        if not artifacts and ctx.artifacts:
            # No mux output (e.g. ffmpeg missing) — surface the last artifact so
            # review still has something to inspect rather than nothing at all.
            last_key = list(ctx.artifacts)[-1]
            artifacts = {last_key: ctx.artifacts[last_key]}

        reporter.set_status(RfirJobStatus(
            job_id=job_id, state=RfirJobState.REVIEW,
            artifacts=artifacts, metrics=metrics,
            metadata={"stage_review": {"ready": True}},
        ))
        logger.info("job %s: complete — %d nodes, %.2fs GPU, $%.4f est.",
                    job_id, len(metrics.get("nodes", [])), metrics.get("total_gpu_ms", 0) / 1000.0,
                    metrics.get("cost_estimate_usd", 0.0))

    except PlanBlocked as e:
        logger.warning("job %s: plan guard blocked: %s", job_id, e)
        reporter.set_status(RfirJobStatus(
            job_id=job_id, state=RfirJobState.FAILED,
            error=f"plan rejected by guardrail: {e}",
        ))
    except CompileError as e:
        logger.warning("job %s: compile failed: %s", job_id, e)
        reporter.set_status(RfirJobStatus(job_id=job_id, state=RfirJobState.FAILED, error=str(e)))
    except Exception as e:
        logger.error("job %s: failed: %s\n%s", job_id, e, traceback.format_exc())
        reporter.set_status(RfirJobStatus(job_id=job_id, state=RfirJobState.FAILED, error=str(e)))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    p = argparse.ArgumentParser()
    p.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0"))
    args = p.parse_args()
    import redis

    r = redis.Redis.from_url(args.redis_url, decode_responses=True)
    reporter = JobStatusReporter(r)
    _warmup()
    logger.info("listening %s on %s", REDIS_KEY_JOBS, args.redis_url)

    while True:
        try:
            item = r.blpop(REDIS_KEY_JOBS, timeout=5)
        except redis.exceptions.TimeoutError:
            # A blocking read timing out at the socket layer is equivalent to
            # blpop's own timeout elapsing with no item — just poll again.
            continue
        except redis.exceptions.ConnectionError as e:
            logger.warning("redis connection error, retrying: %s", e)
            time.sleep(1.0)
            continue
        if not item:
            continue
        _, raw = item
        try:
            data = json.loads(raw)
            job_id = data.get("job_id", "")
            payload = data.get("payload") or {}
        except json.JSONDecodeError:
            logger.warning("malformed job message, skipping: %s", raw[:200])
            continue

        if not job_id:
            logger.warning("job message missing job_id, skipping")
            continue

        if not payload.get("prompt"):
            # Not an RFIR payload (legacy stub jobs push {} as payload) —
            # nothing for this worker to do; the orchestrator's own in-process
            # stub path already handles those.
            logger.debug("job %s: no RFIR payload (prompt missing), skipping", job_id)
            continue

        logger.info("job %s: received RFIR payload", job_id)
        run_rfir_job(job_id, payload, reporter)


if __name__ == "__main__":
    main()
