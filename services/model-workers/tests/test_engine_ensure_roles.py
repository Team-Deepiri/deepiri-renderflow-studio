"""The executor fetches the graph's roles before it walks any node.

Task 5 of docs/superpowers/plans/2026-08-21-rfir-role-residency.md
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.rfir.executor import engine
from app.rfir.ir.types import RfirGraph, RfirNode
from app.rfir.models.fetcher import all_role_dirs
from app.rfir.models.residency import DEFAULT_T2I_MODEL_ID, FALLBACK_T2I_MODEL_ID


def _graph(*ops: str) -> RfirGraph:
    return RfirGraph(nodes=[RfirNode(id=f"n{i}", op=op) for i, op in enumerate(ops)])


def test_prepare_models_requests_exactly_the_graphs_roles(monkeypatch, tmp_path):
    seen: dict[str, object] = {}

    def fake_ensure(roles, *, models_dir, t2i_model_id, **kwargs):
        seen["roles"] = roles
        seen["models_dir"] = models_dir
        seen["t2i_model_id"] = t2i_model_id
        return []

    monkeypatch.setattr("app.rfir.models.fetcher.ensure_roles", fake_ensure)
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    monkeypatch.delenv("RENDERFLOW_RFIR_T2I_MODEL", raising=False)

    engine._prepare_models(_graph("plan_shots", "t2i_keyframe", "depth_estimate", "ffmpeg_mux"))

    assert seen["roles"] == frozenset({"plan_shots", "t2i_keyframe", "depth_estimate"})
    assert seen["models_dir"] == str(tmp_path)
    assert seen["t2i_model_id"] == DEFAULT_T2I_MODEL_ID


def test_tier_a_graph_never_asks_for_t2v(monkeypatch, tmp_path):
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "app.rfir.models.fetcher.ensure_roles",
        lambda roles, **kw: seen.setdefault("roles", roles) and [],
    )
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))

    engine._prepare_models(_graph("t2i_keyframe", "depth_estimate", "vulkan_parallax", "ffmpeg_mux"))

    assert "sparse_t2v" not in seen["roles"]
    assert "segment_subject" not in seen["roles"]


def test_t2i_backend_comes_from_env(monkeypatch, tmp_path):
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "app.rfir.models.fetcher.ensure_roles",
        lambda roles, **kw: seen.setdefault("t2i", kw["t2i_model_id"]) and [],
    )
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("RENDERFLOW_RFIR_T2I_MODEL", FALLBACK_T2I_MODEL_ID)

    engine._prepare_models(_graph("t2i_keyframe"))

    assert seen["t2i"] == FALLBACK_T2I_MODEL_ID


def test_prepare_models_is_a_noop_without_models_dir(monkeypatch):
    """No RENDERFLOW_MODELS_DIR means the loader uses the HF cache; don't fetch."""
    called = False

    def fake_ensure(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("app.rfir.models.fetcher.ensure_roles", fake_ensure)
    monkeypatch.delenv("RENDERFLOW_MODELS_DIR", raising=False)

    engine._prepare_models(_graph("t2i_keyframe"))

    assert called is False


def test_graph_with_no_model_ops_fetches_nothing(monkeypatch, tmp_path):
    calls: list[frozenset] = []
    monkeypatch.setattr(
        "app.rfir.models.fetcher.ensure_roles",
        lambda roles, **kw: calls.append(roles) or [],
    )
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))

    engine._prepare_models(_graph("ffmpeg_mux", "vulkan_upscale"))

    assert calls == []


def test_fetch_failure_propagates(monkeypatch, tmp_path):
    """A missing model must stop the job, not surface as a loader error mid-graph."""

    def boom(*args, **kwargs):
        raise RuntimeError("gated repo")

    monkeypatch.setattr("app.rfir.models.fetcher.ensure_roles", boom)
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="gated repo"):
        engine._prepare_models(_graph("t2i_keyframe"))


def test_t2i_failure_is_survivable_when_the_other_backend_is_on_disk(monkeypatch, tmp_path):
    """FLUX is gated; SDXL is installed. The op falls back, so do not fail early."""
    (tmp_path / "sdxl-turbo").mkdir()
    (tmp_path / "sdxl-turbo" / "model.safetensors").write_bytes(b"w")
    asked: list[frozenset] = []

    def gated(roles, **kwargs):
        asked.append(roles)
        if "t2i_keyframe" in roles:
            raise RuntimeError("403 gated")
        return []

    monkeypatch.setattr("app.rfir.models.fetcher.ensure_roles", gated)
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("RENDERFLOW_RFIR_T2I_MODEL", DEFAULT_T2I_MODEL_ID)

    engine._prepare_models(_graph("t2i_keyframe", "depth_estimate"))

    # Retried without the unreachable T2I, so depth still gets fetched.
    assert asked[-1] == frozenset({"depth_estimate"})


def test_t2i_failure_still_fails_when_no_backend_is_on_disk(monkeypatch, tmp_path):
    def gated(roles, **kwargs):
        raise RuntimeError("403 gated")

    monkeypatch.setattr("app.rfir.models.fetcher.ensure_roles", gated)
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="403 gated"):
        engine._prepare_models(_graph("t2i_keyframe"))


def test_a_stub_t2i_dir_does_not_count_as_a_fallback(monkeypatch, tmp_path):
    """The 16 KB README-only dir a gated pull leaves behind is not a backend."""
    (tmp_path / "sdxl-turbo").mkdir()
    (tmp_path / "sdxl-turbo" / "README.md").write_text("#")

    monkeypatch.setattr(
        "app.rfir.models.fetcher.ensure_roles",
        lambda roles, **kw: (_ for _ in ()).throw(RuntimeError("403 gated")),
    )
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="403 gated"):
        engine._prepare_models(_graph("t2i_keyframe"))


# --- post-job bookkeeping ---------------------------------------------------


def test_finish_models_touches_used_roles(monkeypatch, tmp_path):
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    monkeypatch.delenv("RENDERFLOW_MODELS_MAX_BYTES", raising=False)

    engine._finish_models(_graph("t2i_keyframe", "depth_estimate"))

    from app.rfir.models.disk_lru import LRU_STATE_FILE
    import json

    state = json.loads((tmp_path / LRU_STATE_FILE).read_text())
    assert set(state) == {"t2i_keyframe", "depth_estimate"}


def test_finish_models_evicts_only_when_cap_is_set(monkeypatch, tmp_path):
    (tmp_path / "cogvideox-2b").mkdir()
    (tmp_path / "cogvideox-2b" / "w.bin").write_bytes(b"x" * 100)
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    monkeypatch.delenv("RENDERFLOW_MODELS_MAX_BYTES", raising=False)

    engine._finish_models(_graph("t2i_keyframe"))
    assert (tmp_path / "cogvideox-2b").is_dir()  # no cap → nothing evicted

    monkeypatch.setenv("RENDERFLOW_MODELS_MAX_BYTES", "10")
    engine._finish_models(_graph("t2i_keyframe"))
    assert not (tmp_path / "cogvideox-2b").exists()


def test_finish_models_never_evicts_a_pin(monkeypatch, tmp_path):
    (tmp_path / "depth-anything-v2-small").mkdir()
    (tmp_path / "depth-anything-v2-small" / "w.bin").write_bytes(b"x" * 100)
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("RENDERFLOW_MODELS_MAX_BYTES", "0")

    engine._finish_models(_graph("t2i_keyframe"))

    assert (tmp_path / "depth-anything-v2-small").is_dir()


def test_finish_models_survives_a_bad_cap(monkeypatch, tmp_path):
    """Bookkeeping must not fail a job that already produced its output."""
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("RENDERFLOW_MODELS_MAX_BYTES", "not-a-number")

    engine._finish_models(_graph("t2i_keyframe"))


def test_stale_unused_t2i_backend_is_evictable(tmp_path):
    """The SDXL dir left by an old prepaid install must be reclaimable."""
    dirs = all_role_dirs(DEFAULT_T2I_MODEL_ID)

    assert dirs["t2i_keyframe"] == "flux-schnell"
    assert "sdxl-turbo" in dirs.values()
    assert dirs["t2i_keyframe_fallback"] == "sdxl-turbo"


def test_run_graph_prepares_models_before_any_op(monkeypatch, tmp_path):
    """End-to-end ordering: fetch happens, then ops run."""
    events: list[str] = []

    monkeypatch.setattr(
        "app.rfir.models.fetcher.ensure_roles",
        lambda roles, **kw: events.append("fetch") or [],
    )
    monkeypatch.setattr(engine, "detect_device", lambda: "cpu")
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))

    engine._register_handlers()
    monkeypatch.setitem(engine._OP_HANDLERS, "t2i_keyframe", lambda *a, **k: events.append("op"))
    monkeypatch.setitem(engine._OP_HANDLERS, "ffmpeg_mux", lambda *a, **k: None)

    engine.run_graph(
        _graph("t2i_keyframe", "ffmpeg_mux"),
        job_id="j1",
        output_dir=str(tmp_path / "out"),
    )

    assert events == ["fetch", "op"]
    assert Path(tmp_path / "out").is_dir()
