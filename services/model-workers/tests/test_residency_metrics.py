"""Disk working-set metrics: is E[disk] holding up in production?

Task 7 of docs/superpowers/plans/2026-08-21-rfir-role-residency.md
"""
from __future__ import annotations

import json

import pytest

from app.rfir.metrics import MetricsRegistry
from app.rfir.models.fetcher import residency_report
from app.rfir.models.residency import DEFAULT_T2I_MODEL_ID, catalog_bytes_fp16


def _plant(root, name: str, nbytes: int = 8) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.safetensors").write_bytes(b"w" * nbytes)


# --- residency_report -------------------------------------------------------


def test_report_splits_hot_from_missing(tmp_path):
    _plant(tmp_path, "depth-anything-v2-small")

    report = residency_report(
        frozenset({"t2i_keyframe", "depth_estimate"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
    )

    assert report.hot_roles == frozenset({"depth_estimate"})
    assert report.missing_roles == frozenset({"t2i_keyframe"})


def test_report_bytes_use_the_fp16_size_table(tmp_path):
    _plant(tmp_path, "depth-anything-v2-small")

    report = residency_report(
        frozenset({"t2i_keyframe", "depth_estimate"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
    )

    assert report.miss_bytes == 12 * 10**9   # FLUX
    assert report.hot_bytes == 200 * 10**6   # depth


def test_rho_hat_is_the_share_of_the_old_catalog(tmp_path):
    _plant(tmp_path, "depth-anything-v2-small")

    report = residency_report(
        frozenset({"depth_estimate"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
    )

    assert report.rho_hat == pytest.approx(200 * 10**6 / catalog_bytes_fp16(False))
    assert 0.0 < report.rho_hat < 0.05


def test_tier_a_report_is_a_fraction_of_the_prepaid_pile(tmp_path):
    for name in ("flux-schnell", "qwen2.5-3b-instruct-gguf", "depth-anything-v2-small"):
        _plant(tmp_path, name)

    report = residency_report(
        frozenset({"t2i_keyframe", "plan_shots", "depth_estimate"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
    )

    assert report.missing_roles == frozenset()
    assert report.rho_hat < 0.65  # ~14 GB of a ~24 GB catalog, no CogVideoX


def test_report_with_nothing_on_disk_is_all_miss(tmp_path):
    report = residency_report(
        frozenset({"t2i_keyframe"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
    )

    assert report.hot_bytes == 0
    assert report.rho_hat == 0.0
    assert report.missing_roles == frozenset({"t2i_keyframe"})


def test_roles_with_no_artifact_are_not_counted_as_missing(tmp_path):
    """ffmpeg/Vulkan ops have no weights to be missing."""
    report = residency_report(
        frozenset({"not_a_role"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
    )

    assert report.missing_roles == frozenset()
    assert report.hot_roles == frozenset()


# --- metrics registry -------------------------------------------------------


def test_registry_counts_hits_and_misses():
    reg = MetricsRegistry()

    reg.record_residency(
        hot_roles=frozenset({"depth_estimate", "plan_shots"}),
        missing_roles=frozenset({"t2i_keyframe"}),
        hot_bytes=2_200_000_000,
        miss_bytes=12_000_000_000,
        disk_bytes=2_300_000_000,
    )

    assert reg.model_hit_roles_total == 2
    assert reg.model_miss_roles_total == 1
    assert reg.model_fetch_bytes_total == 12_000_000_000
    assert reg.model_disk_bytes == 2_300_000_000


def test_fetch_bytes_accumulate_but_disk_bytes_is_a_gauge():
    reg = MetricsRegistry()

    for _ in range(2):
        reg.record_residency(
            hot_roles=frozenset(),
            missing_roles=frozenset({"sparse_t2v"}),
            hot_bytes=0,
            miss_bytes=10_000_000_000,
            disk_bytes=500,
        )

    assert reg.model_fetch_bytes_total == 20_000_000_000
    assert reg.model_disk_bytes == 500  # last observation wins, not a sum


def test_a_fully_hot_job_fetches_nothing():
    reg = MetricsRegistry()

    reg.record_residency(
        hot_roles=frozenset({"t2i_keyframe"}),
        missing_roles=frozenset(),
        hot_bytes=12_000_000_000,
        miss_bytes=0,
        disk_bytes=12_000_000_000,
    )

    assert reg.model_fetch_bytes_total == 0
    assert reg.model_miss_roles_total == 0


def test_prometheus_output_carries_the_four_series():
    reg = MetricsRegistry()
    reg.record_residency(
        hot_roles=frozenset({"depth_estimate"}),
        missing_roles=frozenset({"t2i_keyframe"}),
        hot_bytes=200_000_000,
        miss_bytes=12_000_000_000,
        disk_bytes=200_000_000,
    )

    text = reg.render_prometheus()

    assert "rfir_model_disk_bytes 200000000" in text
    assert "rfir_model_fetch_bytes_total 12000000000" in text
    assert "rfir_model_hit_roles_total 1" in text
    assert "rfir_model_miss_roles_total 1" in text
    assert "# TYPE rfir_model_disk_bytes gauge" in text
    assert "# TYPE rfir_model_fetch_bytes_total counter" in text


def test_prometheus_output_is_valid_before_any_job():
    text = MetricsRegistry().render_prometheus()

    assert "rfir_model_disk_bytes 0" in text
    assert text.endswith("\n")


def test_executor_records_residency_for_the_job(monkeypatch, tmp_path):
    """The counters move on a real run, not just when called directly."""
    from app.rfir.executor import engine
    from app.rfir.ir.types import RfirGraph, RfirNode
    from app.rfir.metrics import registry

    _plant(tmp_path, "depth-anything-v2-small")
    monkeypatch.setattr("app.rfir.models.fetcher.ensure_roles", lambda roles, **kw: [])
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("RENDERFLOW_RFIR_T2I_MODEL", DEFAULT_T2I_MODEL_ID)

    before_hits = registry.model_hit_roles_total
    before_fetch = registry.model_fetch_bytes_total

    engine._prepare_models(
        RfirGraph(
            nodes=[
                RfirNode(id="a", op="depth_estimate"),
                RfirNode(id="b", op="t2i_keyframe"),
            ]
        )
    )

    assert registry.model_hit_roles_total == before_hits + 1        # depth resident
    assert registry.model_fetch_bytes_total == before_fetch + 12 * 10**9  # FLUX cold


def test_record_residency_logs_one_json_line(caplog):
    reg = MetricsRegistry()

    with caplog.at_level("INFO", logger="app.rfir.metrics"):
        reg.record_residency(
            hot_roles=frozenset({"depth_estimate"}),
            missing_roles=frozenset({"t2i_keyframe"}),
            hot_bytes=200_000_000,
            miss_bytes=12_000_000_000,
            disk_bytes=200_000_000,
        )

    line = next(r.message for r in caplog.records if r.message.startswith("{"))
    payload = json.loads(line)
    assert payload["roles"] == ["depth_estimate", "t2i_keyframe"]  # sorted, stable
    assert payload["hot_bytes"] == 200_000_000
    assert payload["miss_bytes"] == 12_000_000_000
    assert payload["rho_hat"] == pytest.approx(200_000_000 / catalog_bytes_fp16(False))
