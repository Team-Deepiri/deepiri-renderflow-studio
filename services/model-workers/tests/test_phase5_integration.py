"""Phase 5 integration tests — torch.compile bucketing, CUDA graph stub,
speculative scheduling, and Prometheus metrics (§5.1-5.4).

All tests run on CPU/MPS without GPU model weights.
"""
import time

import pytest

from app.rfir.ir.types import CameraMotion, CameraPath, Shot, ShotList, Tier
from app.rfir.models.compile_utils import compiled_call, is_compile_enabled, clear_compile_cache
from app.rfir.models.cuda_graph import is_available as cuda_graph_available, capture_or_get, clear_graph_cache
from app.rfir.speculative import SpeculativeScheduler, run_speculative_keyframes, stream_shots
from app.rfir.metrics import MetricsRegistry
from app.rfir.executor.context import ExecutionContext


# ---------------------------------------------------------------------------
# 5.1 — torch.compile bucketing
# ---------------------------------------------------------------------------

def test_compile_enabled_on_cuda_and_mps():
    assert is_compile_enabled("cuda") is True
    assert is_compile_enabled("mps") is True


def test_compile_disabled_on_cpu():
    assert is_compile_enabled("cpu") is False


def test_compile_disabled_via_env(monkeypatch):
    monkeypatch.setenv("RENDERFLOW_RFIR_DISABLE_COMPILE", "1")
    assert is_compile_enabled("cuda") is False
    assert is_compile_enabled("mps") is False


def test_compiled_call_returns_same_fn_on_cpu():
    clear_compile_cache()

    def fn(x):
        return x * 2

    out = compiled_call(fn, cache_key=("test_op", 512, 288), device="cpu")
    assert out is fn  # CPU skips compilation entirely


def test_compiled_call_caches_by_key():
    clear_compile_cache()
    calls = []

    def fn(x):
        calls.append(x)
        return x

    # Same cache key twice should return the same wrapped callable object
    # (whether compiled or eager-fallback), not recompile each time.
    out1 = compiled_call(fn, cache_key=("op", 512, 288, 4), device="mps")
    out2 = compiled_call(fn, cache_key=("op", 512, 288, 4), device="mps")
    assert out1 is out2


def test_compiled_call_different_buckets_are_independent():
    clear_compile_cache()

    def fn(x):
        return x

    out_a = compiled_call(fn, cache_key=("op", 512, 288), device="mps")
    out_b = compiled_call(fn, cache_key=("op", 1024, 576), device="mps")
    # Different shape buckets get their own cache entries (may be eager
    # fallback on this machine, but the keys must not collide).
    assert ("mps", "reduce-overhead", "op", 512, 288) in _peek_cache()
    assert ("mps", "reduce-overhead", "op", 1024, 576) in _peek_cache()


def _peek_cache():
    from app.rfir.models import compile_utils
    return compile_utils._compiled_cache


# ---------------------------------------------------------------------------
# 5.2 — CUDA graph capture (CUDA-only; no-op verified on non-CUDA)
# ---------------------------------------------------------------------------

def test_cuda_graph_unavailable_on_mps():
    assert cuda_graph_available("mps") is False


def test_cuda_graph_unavailable_on_cpu():
    assert cuda_graph_available("cpu") is False


def test_capture_or_get_returns_none_on_non_cuda():
    clear_graph_cache()

    def fn(x):
        return x

    result = capture_or_get(("tier_a_batch",), device="mps", fn=fn, example_inputs={"x": 1})
    assert result is None


# ---------------------------------------------------------------------------
# 5.3 — Speculative keyframe generation
# ---------------------------------------------------------------------------

def _shotlist(n: int) -> ShotList:
    return ShotList(prompt="test", shots=[
        Shot(index=i, description=f"shot {i}", tier=Tier.A, duration_sec=3.0,
             camera=CameraPath(motion=CameraMotion.STATIC))
        for i in range(n)
    ])


def test_stream_shots_yields_all():
    sl = _shotlist(4)
    shots = list(stream_shots(sl))
    assert len(shots) == 4
    assert [s.index for s in shots] == [0, 1, 2, 3]


def test_speculative_scheduler_overlaps_work():
    """Work for shot 0 should run concurrently with shot 1, not sequentially."""
    sl = _shotlist(3)
    started_at: dict[int, float] = {}

    def work_fn(shot):
        started_at[shot.index] = time.monotonic()
        time.sleep(0.1)
        return f"result_{shot.index}"

    t0 = time.monotonic()
    with SpeculativeScheduler(max_workers=3) as scheduler:
        scheduler.submit_stream(stream_shots(sl), work_fn)
        results = scheduler.results()
    elapsed = time.monotonic() - t0

    assert results == {0: "result_0", 1: "result_1", 2: "result_2"}
    # 3 shots * 0.1s each would be 0.3s sequential; with overlap it should
    # be much closer to 0.1-0.15s.
    assert elapsed < 0.25, f"expected overlap, took {elapsed:.3f}s"


def test_speculative_scheduler_handles_failures_gracefully():
    sl = _shotlist(3)

    def work_fn(shot):
        if shot.index == 1:
            raise ValueError("boom")
        return f"ok_{shot.index}"

    with SpeculativeScheduler(max_workers=2) as scheduler:
        scheduler.submit_stream(stream_shots(sl), work_fn)
        results = scheduler.results()

    # Shot 1 failed and is omitted; shots 0 and 2 still succeeded.
    assert results == {0: "ok_0", 2: "ok_2"}


def test_run_speculative_keyframes_convenience_wrapper():
    sl = _shotlist(2)
    results = run_speculative_keyframes(sl, lambda shot: shot.description)
    assert results == {0: "shot 0", 1: "shot 1"}


# ---------------------------------------------------------------------------
# 5.4 — Prometheus metrics
# ---------------------------------------------------------------------------

def _ctx_with_data() -> ExecutionContext:
    ctx = ExecutionContext(job_id="metrics-test", device="mps")
    ctx.record_node("n1", "t2i_keyframe", wall_ms=100, gpu_ms=800)
    ctx.record_node("n2", "sparse_t2v_window", wall_ms=500, gpu_ms=5000)
    ctx.tier_distribution = {"A": 2, "C": 1}
    ctx.downgrades = [{"node_id": "n1", "op": "t2i_keyframe"}]
    return ctx


def test_metrics_registry_records_job():
    reg = MetricsRegistry()
    reg.record_job(_ctx_with_data())

    assert reg.jobs_total == 1
    assert reg.gpu_seconds_by_op["t2i_keyframe"] == pytest.approx(0.8)
    assert reg.gpu_seconds_by_op["sparse_t2v_window"] == pytest.approx(5.0)
    assert reg.tier_count["A"] == 2
    assert reg.tier_count["C"] == 1
    assert reg.downgrades_total == 1
    assert reg.cost_usd_total > 0


def test_metrics_registry_accumulates_across_jobs():
    reg = MetricsRegistry()
    reg.record_job(_ctx_with_data())
    reg.record_job(_ctx_with_data())

    assert reg.jobs_total == 2
    assert reg.gpu_seconds_by_op["t2i_keyframe"] == pytest.approx(1.6)
    assert reg.tier_count["A"] == 4


def test_render_prometheus_format():
    reg = MetricsRegistry()
    reg.record_job(_ctx_with_data())
    text = reg.render_prometheus()

    assert "# TYPE rfir_gpu_seconds_total counter" in text
    assert 'rfir_gpu_seconds_total{op="t2i_keyframe"}' in text
    assert 'rfir_tier_count{tier="A"} 2' in text
    assert "rfir_jobs_total 1" in text
    assert "rfir_downgrades_total 1" in text
    assert "rfir_cost_usd_total" in text


def test_render_prometheus_empty_registry():
    reg = MetricsRegistry()
    text = reg.render_prometheus()
    assert "rfir_jobs_total 0" in text
    assert "rfir_downgrades_total 0" in text
