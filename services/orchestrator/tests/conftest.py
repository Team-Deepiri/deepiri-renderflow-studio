"""Shared fixtures for orchestrator tests."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

# The full RFIR stage progression a successful in-process scene job walks
# through (job bookends around the stage_for_op() vocabulary from
# renderflow_queue). Asserted by the worker-loop and e2e tests.
EXPECTED_RFIR_SCENE_STAGES = (
    "preparing",
    "compiling",
    "generating_keyframe",
    "estimating_depth",
    "rendering_frames",
    "muxing",
    "review",
)


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Disable all Postgres calls so tests run without a real database."""
    import app.db as db_mod

    monkeypatch.setattr(db_mod, "init_db", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "pool_ready", lambda: False)
    monkeypatch.setattr(db_mod, "insert_ai_job", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "update_ai_job_status", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "sync_job_stages", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "get_ai_job", lambda *a: None)
    monkeypatch.setattr(db_mod, "get_ai_job_stages", lambda *a: [])


@pytest.fixture
def fake_ml_ops(monkeypatch):
    """Replace the RFIR ML ops with deterministic fakes (no torch / weights).

    The real compiler, validator, executor engine, and ffmpeg mux still run.
    """
    from app.rfir.ops import depth_estimate, t2i_keyframe

    monkeypatch.setattr(
        t2i_keyframe, "run",
        lambda prompt, *, width=512, height=288, **kw: Image.new("RGB", (width, height), (120, 40, 200)),
    )
    monkeypatch.setattr(
        depth_estimate, "run",
        lambda image, **kw: np.zeros((image.height, image.width), dtype=np.float32),
    )
