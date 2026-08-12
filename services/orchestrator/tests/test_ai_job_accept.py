"""Accepting an AI job must describe the real artifact, not a guess.

The asset created on accept feeds the timeline: the UI turns duration_ms
into clip length and shows width/height/fps in the asset list. Hardcoded
metadata puts a wrong-length clip on the timeline, so these tests probe a
real MP4 of known dimensions and assert the asset matches it.
"""
from __future__ import annotations

import shutil
import subprocess
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.job_store import JobStatus, store
from app.main import app

ffmpeg_required = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe not found in PATH",
)

client = TestClient(app)


def _make_video(path: str, duration: float, size: str = "320x240", fps: int = 24) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=blue:s={size}:r={fps}",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            path,
        ],
        check=True,
        capture_output=True,
    )


def _job_in_review(output_path: str) -> str:
    """A scene job parked in review with `output_path` as its artifact."""
    rec = store.create(uuid4(), "scene", "a blue field")
    store.merge_meta(rec.id, "output_path", output_path)
    store.update_status(rec.id, JobStatus.REVIEW, stages=["preparing", "review"])
    return str(rec.id)


@ffmpeg_required
def test_accept_records_the_artifacts_real_duration(tmp_path):
    mp4 = tmp_path / "output.mp4"
    _make_video(str(mp4), duration=3.0)
    job_id = _job_in_review(str(mp4))

    accepted = client.post(f"/v1/jobs/{job_id}/accept")
    assert accepted.status_code == 200, accepted.text

    asset = client.get(f"/v1/assets/{accepted.json()['metadata']['asset_id']}").json()
    assert asset["duration_ms"] == pytest.approx(3000, abs=200)


@ffmpeg_required
def test_accept_records_the_artifacts_real_dimensions(tmp_path):
    """RFIR renders at its own resolution — the asset must not claim 1080p."""
    mp4 = tmp_path / "output.mp4"
    _make_video(str(mp4), duration=1.0, size="426x240", fps=12)
    job_id = _job_in_review(str(mp4))

    accepted = client.post(f"/v1/jobs/{job_id}/accept")
    assert accepted.status_code == 200, accepted.text

    meta = client.get(f"/v1/assets/{accepted.json()['metadata']['asset_id']}").json()["meta_jsonb"]
    assert (meta["width"], meta["height"]) == (426, 240)
    assert meta["fps"] == pytest.approx(12.0, abs=0.1)
    assert meta["codec"]


def test_accept_without_ffprobe_invents_nothing(tmp_path, monkeypatch):
    """No ffprobe (or an unreadable file) leaves duration/size unknown rather
    than guessing — a made-up duration becomes a wrong-length clip."""
    from app.media import ffmpeg as ffmpeg_util

    monkeypatch.setattr(
        ffmpeg_util, "detect_format",
        lambda _p: {"ok": False, "error": "ffprobe not found on PATH"},
    )

    mp4 = tmp_path / "output.mp4"
    mp4.write_bytes(b"not really an mp4")
    job_id = _job_in_review(str(mp4))

    accepted = client.post(f"/v1/jobs/{job_id}/accept")
    assert accepted.status_code == 200, accepted.text

    asset = client.get(f"/v1/assets/{accepted.json()['metadata']['asset_id']}").json()
    assert asset["duration_ms"] is None
    assert "width" not in asset["meta_jsonb"]
    assert "height" not in asset["meta_jsonb"]
    # The asset is still usable — it just carries why it is thin.
    assert asset["meta_jsonb"]["probe_error"]
