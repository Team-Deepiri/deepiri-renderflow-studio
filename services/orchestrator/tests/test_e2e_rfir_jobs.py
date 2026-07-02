"""End-to-end tests for the RFIR job flow through the real HTTP API.

Boots the FastAPI app (lifespan: settings, worker thread, gRPC), then
drives the exact user path from the task acceptance criteria:

    POST /v1/jobs {mode: "scene"}  →  guardrail gates  →  enqueue  →
    in-process worker  →  RFIR compile + execute + ffmpeg mux  →
    GET /v1/jobs/{id} shows RFIR stages and lands in "review" with
    metadata.output_path pointing at a real MP4 on disk.

Only the two ML ops (t2i, depth) are faked — HTTP layer, guardrails,
job store, worker thread, bridge, compiler, validator, executor engine,
and ffmpeg are all real. The failure path runs with NO fakes at all:
torch isn't installed in this venv, so the t2i op genuinely fails,
which must land the job in "failed" with a meaningful error.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image

import app.main  # noqa: F401 -- resolves the app.api <-> app.worker_loop import cycle first

ffmpeg_required = pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="ffmpeg not found in PATH"
)

POLL_TIMEOUT_SEC = 30.0
TERMINAL = {"review", "failed", "cancelled"}


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    import app.db as db_mod

    monkeypatch.setattr(db_mod, "init_db", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "pool_ready", lambda: False)
    monkeypatch.setattr(db_mod, "insert_ai_job", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "update_ai_job_status", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "sync_job_stages", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "get_ai_job", lambda *a: None)
    monkeypatch.setattr(db_mod, "get_ai_job_stages", lambda *a: [])


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Real app + real worker thread, configured for local RFIR execution."""
    monkeypatch.setenv("RENDERFLOW_RFIR_ENABLED", "true")
    monkeypatch.setenv("RENDERFLOW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RENDERFLOW_AI_STAGE_MS", "0")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # The worker thread is a module-global that survives across tests; force
    # a fresh one so it picks up this test's settings.
    import app.worker_loop as wl

    monkeypatch.setattr(wl, "_worker_thread", None)
    wl._stop.clear()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c

    wl._stop.set()
    if wl._worker_thread is not None:
        wl._worker_thread.join(timeout=5.0)
    monkeypatch.setattr(wl, "_worker_thread", None)
    wl._stop.clear()


@pytest.fixture
def fake_ml_ops(monkeypatch):
    from app.rfir.ops import depth_estimate, t2i_keyframe

    monkeypatch.setattr(
        t2i_keyframe, "run",
        lambda prompt, *, width=512, height=288, **kw: Image.new("RGB", (width, height), (200, 120, 40)),
    )
    monkeypatch.setattr(
        depth_estimate, "run",
        lambda image, **kw: np.zeros((image.height, image.width), dtype=np.float32),
    )


def _submit_scene_job(client, prompt: str) -> dict:
    resp = client.post("/v1/jobs", json={
        "project_id": str(uuid4()),
        "mode": "scene",
        "prompt": prompt,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def _poll_until_terminal(client, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SEC
    body: dict = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.2)
    pytest.fail(f"job {job_id} did not reach a terminal state in {POLL_TIMEOUT_SEC}s: {body}")


@ffmpeg_required
def test_e2e_scene_job_review_with_real_mp4(client, fake_ml_ops):
    job = _submit_scene_job(client, "a lighthouse in a storm at dusk")

    final = _poll_until_terminal(client, job["id"])

    assert final["status"] == "review", final
    output = Path(final["metadata"]["output_path"])
    assert output.name == "output.mp4"
    assert output.exists(), f"missing MP4 at {output}"
    assert output.stat().st_size > 1024

    for stage in ("preparing", "compiling", "generating_keyframe",
                  "estimating_depth", "rendering_frames", "muxing", "review"):
        assert stage in final["stages"], f"missing stage {stage!r} in {final['stages']}"

    assert final["metadata"]["rfir_metrics"]["nodes"]

    # Accepting the reviewed job must create a video asset from the real MP4.
    resp = client.post(f"/v1/jobs/{job['id']}/accept")
    assert resp.status_code == 200, resp.text
    accepted = resp.json()
    assert accepted["status"] == "committed"
    assert accepted["metadata"].get("asset_id")


def test_e2e_scene_job_without_ml_runtime_fails_with_error(client):
    """No fakes: torch/diffusers aren't installed here, so inference must
    genuinely fail and the API must surface a failed status + reason."""
    job = _submit_scene_job(client, "a prompt that cannot be rendered here")

    final = _poll_until_terminal(client, job["id"])

    assert final["status"] == "failed", final
    assert "failed" in final["stages"]
    assert final["metadata"].get("error"), "expected metadata.error explaining the failure"


@ffmpeg_required
def test_e2e_rfir_preview_endpoint(client):
    resp = client.post("/v1/rfir/preview", json={"prompt": "a calm lake at sunrise"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["shot_count"] == 1
