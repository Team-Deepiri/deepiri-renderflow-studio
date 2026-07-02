"""Tests for the in-process RFIR path in worker_loop (§1.14).

When RENDERFLOW_RFIR_ENABLED=true and a scene job is processed locally
(no Redis dispatch to model-workers), _process_job must run the real RFIR
pipeline instead of run_scene_stages() stubs: real MP4 on disk, RFIR-aware
stage names, and FAILED with a meaningful error when inference breaks.

ML ops are replaced by the shared fake_ml_ops fixture (conftest.py) —
no torch or weights needed.
"""
from __future__ import annotations

import shutil
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image

import app.main  # noqa: F401 -- resolves the app.api <-> app.worker_loop import cycle first
from app.config import Settings
from app.job_store import JobStatus, JobStore
from tests.conftest import EXPECTED_RFIR_SCENE_STAGES

ffmpeg_required = pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="ffmpeg not found in PATH"
)


def _settings(tmp_path) -> Settings:
    return Settings(rfir_enabled=True, ai_stages_simulate_ms=0, data_dir=str(tmp_path))


@ffmpeg_required
def test_scene_job_lands_in_review_with_real_mp4(tmp_path, fake_ml_ops):
    from app.worker_loop import _process_job
    from pathlib import Path

    store = JobStore()
    job = store.create(uuid4(), "scene", "a calm lake at sunrise")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), _settings(tmp_path))

    final = store.get(job.id)
    assert final.status == JobStatus.REVIEW
    output = Path(final.metadata["output_path"])
    assert output.name == "output.mp4"
    assert output.exists()
    assert final.metadata["rfir_metrics"]["nodes"]


@ffmpeg_required
def test_scene_job_reports_rfir_stages(tmp_path, fake_ml_ops):
    from app.worker_loop import _process_job

    store = JobStore()
    job = store.create(uuid4(), "scene", "a red balloon")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), _settings(tmp_path))

    final = store.get(job.id)
    for stage in EXPECTED_RFIR_SCENE_STAGES:
        assert stage in final.stages, f"missing stage {stage!r} in {final.stages}"


def test_scene_job_failure_sets_failed_with_error(tmp_path, monkeypatch):
    from app.rfir.ops import t2i_keyframe
    from app.worker_loop import _process_job

    def broken(*a, **kw):
        raise RuntimeError("model weights not found: flux-schnell-fp16")

    monkeypatch.setattr(t2i_keyframe, "run", broken)

    store = JobStore()
    job = store.create(uuid4(), "scene", "anything")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), _settings(tmp_path))

    final = store.get(job.id)
    assert final.status == JobStatus.FAILED
    assert "failed" in final.stages
    assert "model weights not found" in final.metadata["error"]


def test_scene_job_cancelled_mid_run(tmp_path, monkeypatch):
    from app.rfir.ops import depth_estimate, t2i_keyframe
    from app.worker_loop import _cancelled_jobs, _process_job

    store = JobStore()
    job = store.create(uuid4(), "scene", "cancel me mid-flight")

    def t2i_then_cancel(prompt, *, width=512, height=288, **kw):
        _cancelled_jobs.add(str(job.id))
        return Image.new("RGB", (width, height), (0, 0, 0))

    monkeypatch.setattr(t2i_keyframe, "run", t2i_then_cancel)
    monkeypatch.setattr(
        depth_estimate, "run",
        lambda image, **kw: np.zeros((image.height, image.width), dtype=np.float32),
    )

    try:
        with patch("app.worker_loop.store", store):
            _process_job(str(job.id), _settings(tmp_path))
    finally:
        _cancelled_jobs.discard(str(job.id))

    final = store.get(job.id)
    assert final.status == JobStatus.CANCELLED
    assert "cancelled" in final.stages


def test_audio_job_still_uses_stub_stages(tmp_path):
    from app.worker_loop import _process_job

    store = JobStore()
    job = store.create(uuid4(), "audio", "narrate this")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), _settings(tmp_path))

    final = store.get(job.id)
    assert final.status == JobStatus.REVIEW
    assert "voice_cast" in final.stages


def test_rfir_disabled_keeps_stub_scene_stages(tmp_path):
    from app.worker_loop import _process_job

    store = JobStore()
    job = store.create(uuid4(), "scene", "stub please")

    with patch("app.worker_loop.store", store):
        _process_job(str(job.id), Settings(rfir_enabled=False, ai_stages_simulate_ms=0))

    final = store.get(job.id)
    assert final.status == JobStatus.REVIEW
    assert "storyboard" in final.stages
