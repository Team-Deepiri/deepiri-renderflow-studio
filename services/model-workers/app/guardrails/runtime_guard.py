"""Layer 3 — Runtime guard for model workers.

Called between RFIR IR node executions during job processing.
Worker must abort the job on any BLOCK verdict and must NOT persist
the offending keyframe to long-term storage.
"""
from __future__ import annotations

from diri_agent_guardrails.core.result import CheckResult
from diri_agent_guardrails.core.verdict import Verdict

__all__ = ["check_keyframe", "check_budget"]


def check_keyframe(
    frame_bytes: bytes,
    nsfw_mode: str = "block",
    *,
    frame_index: int = 0,
) -> CheckResult:
    """Scan a single decoded keyframe for policy violations.

    Stub — plug in a real image classifier (e.g. Falconsai/nsfw_image_detection).
    """
    if nsfw_mode != "off":
        # TODO: integrate real image classifier
        pass

    return CheckResult(
        passed=True, verdict=Verdict.ALLOW,
        details={"frame_index": frame_index, "frame_size_bytes": len(frame_bytes)},
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
