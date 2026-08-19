"""Layer 3 — Runtime guard for model workers.

Called between RFIR IR node executions during job processing.
Worker must abort the job on any BLOCK verdict and must NOT persist
the offending keyframe to long-term storage.
"""
from __future__ import annotations

import io
import logging
import os

from diri_agent_guardrails.core.result import CheckResult
from diri_agent_guardrails.core.verdict import Verdict

logger = logging.getLogger(__name__)

__all__ = ["check_keyframe", "check_budget"]

_MODEL_ID = "nsfw-image-detection"
_THRESHOLDS = {"block": 0.7, "restricted": 0.9}
_DEFAULT_THRESHOLD = _THRESHOLDS["block"]


def _nsfw_score(frame_bytes: bytes) -> float:
    """P(nsfw) for one encoded frame, via the registry's nsfw_classify model."""
    import torch
    from PIL import Image

    from app.rfir.models.loader import load_model

    bundle = load_model(_MODEL_ID)
    model, processor, device = bundle["model"], bundle["processor"], bundle["device"]

    image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")

    # The processor always emits float32; the model may be fp16 (MPS/CUDA per
    # precision.resolve), so match it or torch raises a dtype mismatch.
    pixel_values = inputs["pixel_values"].to(device=device, dtype=model.dtype)

    with torch.no_grad():
        logits = model(pixel_values=pixel_values).logits

    probs = torch.softmax(logits.float(), dim=-1)[0]

    nsfw_idx = next(
        (i for i, label in model.config.id2label.items() if label.lower() == "nsfw"),
        None,
    )
    if nsfw_idx is None:
        raise RuntimeError(
            f"{_MODEL_ID} has no 'nsfw' label in id2label={model.config.id2label}"
        )

    return float(probs[nsfw_idx])


def check_keyframe(
    frame_bytes: bytes,
    nsfw_mode: str = "block",
    *,
    frame_index: int = 0,
) -> CheckResult:
    """Scan a single decoded keyframe for policy violations."""
    if nsfw_mode == "off":
        return CheckResult(
            passed=True, verdict=Verdict.ALLOW,
            details={"frame_index": frame_index, "nsfw_mode": nsfw_mode},
        )

    threshold = _THRESHOLDS.get(nsfw_mode, _DEFAULT_THRESHOLD)

    try:
        score = _nsfw_score(frame_bytes)
    except Exception as e:
        # Fail closed: an unavailable classifier must not silently become a
        # bypass. Mirrors guardrails config._check_enabled() — degraded
        # behavior is a dev-only concession, never a production one.
        if os.environ.get("READINESS_MODE", "dev").strip().lower() == "dev":
            logger.warning(
                "keyframe classifier unavailable (%s) — allowing frame %d in dev mode",
                e, frame_index,
            )
            return CheckResult(
                passed=True, verdict=Verdict.ALLOW,
                details={"frame_index": frame_index, "classifier_error": str(e)},
            )
        raise

    if score >= threshold:
        return CheckResult(
            passed=False, verdict=Verdict.BLOCK, score=score,
            message=f"NSFW score {score:.3f} >= {threshold} (nsfw_mode={nsfw_mode})",
            details={
                "frame_index": frame_index,
                "nsfw_mode": nsfw_mode,
                "threshold": threshold,
            },
        )

    return CheckResult(
        passed=True, verdict=Verdict.ALLOW, score=score,
        details={
            "frame_index": frame_index,
            "nsfw_mode": nsfw_mode,
            "threshold": threshold,
            "frame_size_bytes": len(frame_bytes),
        },
    )


def check_budget(
    elapsed_gpu_sec: float,
    max_gpu_seconds: float | None,
) -> CheckResult:
    """Check whether the job has exceeded its GPU time budget."""
    if max_gpu_seconds is not None and elapsed_gpu_sec > max_gpu_seconds:
        return CheckResult(
            passed=False, verdict=Verdict.BLOCK, score=1.0,
            message=f"GPU budget exceeded: {elapsed_gpu_sec:.1f}s / {max_gpu_seconds:.1f}s",
            details={"elapsed_sec": elapsed_gpu_sec, "limit_sec": max_gpu_seconds},
        )
    return CheckResult(passed=True, verdict=Verdict.ALLOW)
