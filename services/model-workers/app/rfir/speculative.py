"""Speculative keyframe generation — overlap T2I work with shot planning (§5.3).

While the planner (Qwen) is still producing later shots, this scheduler kicks
off keyframe generation for earlier shots that are already known, instead of
waiting for the full ShotList. This works on any device (CUDA/MPS/CPU) since
it's pure Python concurrency, not a GPU-specific optimization.

Today `planner.plan()` returns the full ShotList synchronously (Qwen's
`create_chat_completion` isn't called in streaming mode), so `stream_shots()`
below yields shots one at a time from that completed list — this models the
"shots become available progressively" contract. If the planner is later
changed to parse Qwen's JSON incrementally as tokens stream in, only
`stream_shots()` needs to change; `SpeculativeScheduler` already overlaps
work correctly with any iterable that yields shots over time.

Spec reference: rfir-inference-engine-implementation.md §5.3
"""
from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Iterable, Iterator, TypeVar

from app.rfir.ir.types import Shot, ShotList

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_MAX_WORKERS = 2


def stream_shots(shot_list: ShotList) -> Iterator[Shot]:
    """Yield shots from an already-planned ShotList, one at a time.

    Placeholder for true incremental planning (Qwen streaming JSON parse).
    Kept as a separate function so callers depend on the streaming contract,
    not on `plan()`'s current synchronous implementation.
    """
    yield from shot_list.shots


class SpeculativeScheduler:
    """Submits work for each shot as soon as it's available, without waiting
    for the rest of the shot stream to finish.
    """

    def __init__(self, max_workers: int = DEFAULT_MAX_WORKERS) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: list[tuple[int, Future]] = []

    def submit_stream(
        self,
        shots: Iterable[Shot],
        work_fn: Callable[[Shot], T],
    ) -> None:
        """Submit `work_fn(shot)` for each shot as it arrives from the stream.

        Does not block on the full stream — each shot is dispatched to the
        thread pool the moment it's yielded, so work for shot 0 can finish
        (or be in flight) while shot 3 is still being planned.
        """
        for shot in shots:
            future = self._executor.submit(work_fn, shot)
            self._futures.append((shot.index, future))
            logger.info("speculative: submitted shot %d for early keyframe work", shot.index)

    def results(self) -> dict[int, T]:
        """Block until all submitted work completes; return {shot_index: result}."""
        out: dict[int, T] = {}
        for shot_index, future in self._futures:
            try:
                out[shot_index] = future.result()
            except Exception as e:
                logger.warning("speculative: shot %d work failed: %s", shot_index, e)
        return out

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def __enter__(self) -> "SpeculativeScheduler":
        return self

    def __exit__(self, *exc_info) -> None:
        self.shutdown(wait=True)


def run_speculative_keyframes(
    shot_list: ShotList,
    keyframe_fn: Callable[[Shot], T],
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[int, T]:
    """Convenience wrapper: generate keyframes for all shots, overlapped."""
    with SpeculativeScheduler(max_workers=max_workers) as scheduler:
        scheduler.submit_stream(stream_shots(shot_list), keyframe_fn)
        return scheduler.results()
