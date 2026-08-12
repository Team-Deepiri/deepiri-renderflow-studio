"""The AI prompt loop, end to end through the HTTP API.

Walks the path the studio UI drives after a scene job lands in review:

    accept the job          → video asset with real ffprobe metadata
    create a clip           → the accepted asset on the sequence's timeline
    submit a render job     → export.mp4 on disk containing that clip

The render worker is driven directly rather than through its background
thread so the assertion lands on a finished file, not on a race.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.job_store import JobStatus, store
from app.main import app
from app.render_worker import _process_render_job

ffmpeg_required = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe not found in PATH",
)

client = TestClient(app)
FPS = 24


def _make_video(path: str, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=teal:s=320x240:r={FPS}",
            "-t", str(duration), "-pix_fmt", "yuv420p", path,
        ],
        check=True,
        capture_output=True,
    )


def _probe_duration(path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(proc.stdout)["format"]["duration"])


@ffmpeg_required
def test_accepted_clip_reaches_the_exported_file(tmp_path):
    project = client.post("/v1/projects", json={"name": "loop", "fps_num": FPS, "fps_den": 1}).json()
    pid = project["id"]
    seq = client.post(f"/v1/projects/{pid}/sequences", json={"name": "Main Sequence"}).json()
    track = client.post(
        f"/v1/sequences/{seq['id']}/tracks",
        json={"track_type": "video", "lane_index": 0, "name": "V1"},
    ).json()

    # A finished scene job awaiting review, with a real 2s artifact.
    mp4 = tmp_path / "output.mp4"
    _make_video(str(mp4), duration=2.0)
    job = store.create(uuid4(), "scene", "a teal horizon")
    store.merge_meta(job.id, "output_path", str(mp4))
    store.update_status(job.id, JobStatus.REVIEW, stages=["preparing", "review"])

    accepted = client.post(f"/v1/jobs/{job.id}/accept").json()
    asset_id = accepted["metadata"]["asset_id"]
    asset = client.get(f"/v1/assets/{asset_id}").json()

    # The UI turns the probed duration into clip length — 2s at 24fps.
    out_tick = round(asset["duration_ms"] / 1000 * FPS)
    assert out_tick == 48

    clip = client.post(
        f"/v1/sequences/{seq['id']}/clips",
        json={
            "track_id": track["id"], "asset_id": asset_id,
            "in_tick": 0, "out_tick": out_tick,
            "src_in_tick": 0, "speed_ratio": 1.0,
        },
    )
    assert clip.status_code == 200, clip.text

    render = client.post(
        f"/v1/projects/{pid}/render-jobs",
        json={"sequence_id": seq["id"], "preset": "h264_1080p"},
    ).json()

    _process_render_job(render["id"], Settings(data_dir=str(tmp_path)))

    final = client.get(f"/v1/render-jobs/{render['id']}").json()
    assert final["status"] == "completed", final
    exported = Path(final["output_uri"])
    assert exported.is_file()
    assert _probe_duration(str(exported)) == pytest.approx(2.0, abs=0.5)


@ffmpeg_required
def test_export_of_an_empty_sequence_falls_back_to_a_placeholder(tmp_path):
    """Exporting before anything is on the timeline yields the 5s placeholder
    rather than an error — the contrast that proves the test above really
    rendered the accepted clip and not this."""
    project = client.post("/v1/projects", json={"name": "empty", "fps_num": FPS, "fps_den": 1}).json()
    seq = client.post(f"/v1/projects/{project['id']}/sequences", json={"name": "Main"}).json()

    render = client.post(
        f"/v1/projects/{project['id']}/render-jobs",
        json={"sequence_id": seq["id"], "preset": "h264_1080p"},
    ).json()

    _process_render_job(render["id"], Settings(data_dir=str(tmp_path)))

    final = client.get(f"/v1/render-jobs/{render['id']}").json()
    assert final["status"] == "completed", final
    assert _probe_duration(final["output_uri"]) == pytest.approx(5.0, abs=0.5)
