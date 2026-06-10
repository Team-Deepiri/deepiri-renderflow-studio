"""Tests for trimmed clip export via render_worker.py.

Unit tests run without ffmpeg by mocking subprocess.
Integration tests (marked ffmpeg_available) require a real ffmpeg install.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.media.render_worker import RenderClip, render_sequence

FPS = 24

ffmpeg_available = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not installed",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _ok_run(*args, **kwargs):
    return MagicMock(returncode=0, stderr="")


# ── unit tests (no real ffmpeg needed) ───────────────────────────────────────


def test_no_clips_returns_error(tmp_path):
    result = render_sequence([], fps=FPS, output_path=str(tmp_path / "out.mp4"))
    assert result["ok"] is False
    assert "no clips" in result["error"]


def test_missing_source_returns_error(tmp_path):
    clip = RenderClip(
        source_path=str(tmp_path / "nonexistent.mp4"),
        in_tick=0,
        out_tick=72,
    )
    result = render_sequence([clip], fps=FPS, output_path=str(tmp_path / "out.mp4"))
    assert result["ok"] is False
    assert "source not found" in result["error"]


def test_ffmpeg_not_found_returns_error(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")
    clip = RenderClip(source_path=str(src), in_tick=0, out_tick=24)

    with patch("shutil.which", return_value=None):
        result = render_sequence([clip], fps=FPS, output_path=str(tmp_path / "out.mp4"))

    assert result["ok"] is False
    assert "ffmpeg not found" in result["error"]


def test_trim_uses_correct_ss_and_t(tmp_path):
    """src_in_tick and in/out ticks should map to -ss and -t correctly."""
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")

    # clip spans ticks 24→96 on timeline (3s), source starts at tick 48 (2s in)
    clip = RenderClip(
        source_path=str(src),
        in_tick=24,
        out_tick=96,
        src_in_tick=48,
    )

    with patch("subprocess.run", side_effect=_ok_run) as mock_run, \
         patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        render_sequence([clip], fps=FPS, output_path=str(tmp_path / "out.mp4"))

    trim_cmd = None
    for c in mock_run.call_args_list:
        cmd = c.args[0]
        if "-ss" in cmd and str(src) in cmd:
            trim_cmd = cmd
            break

    assert trim_cmd is not None, "no trim ffmpeg call found"
    ss = float(trim_cmd[trim_cmd.index("-ss") + 1])
    t  = float(trim_cmd[trim_cmd.index("-t") + 1])
    assert ss == pytest.approx(2.0)   # src_in_tick=48 / 24fps
    assert t  == pytest.approx(3.0)   # (out 96 - in 24) / 24fps


def test_gap_between_clips_generates_black_segment(tmp_path):
    """A gap between two clips should produce exactly one black-segment call."""
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")

    clip1 = RenderClip(source_path=str(src), in_tick=0,  out_tick=24)
    clip2 = RenderClip(source_path=str(src), in_tick=48, out_tick=72)  # 1s gap

    with patch("subprocess.run", side_effect=_ok_run) as mock_run, \
         patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        render_sequence([clip1, clip2], fps=FPS, output_path=str(tmp_path / "out.mp4"))

    black_calls = [
        c for c in mock_run.call_args_list
        if any("color=c=black" in str(a) for a in c.args[0])
    ]
    assert len(black_calls) == 1


def test_no_gap_does_not_generate_black_segment(tmp_path):
    """Adjacent clips with no gap should not produce any black segment."""
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")

    clip1 = RenderClip(source_path=str(src), in_tick=0,  out_tick=24)
    clip2 = RenderClip(source_path=str(src), in_tick=24, out_tick=48)

    with patch("subprocess.run", side_effect=_ok_run) as mock_run, \
         patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        render_sequence([clip1, clip2], fps=FPS, output_path=str(tmp_path / "out.mp4"))

    black_calls = [
        c for c in mock_run.call_args_list
        if any("color=c=black" in str(a) for a in c.args[0])
    ]
    assert len(black_calls) == 0


def test_ffmpeg_failure_propagates_error(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")
    clip = RenderClip(source_path=str(src), in_tick=0, out_tick=24)

    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        mock_run.return_value = MagicMock(returncode=1, stderr="codec not found")
        result = render_sequence([clip], fps=FPS, output_path=str(tmp_path / "out.mp4"))

    assert result["ok"] is False
    assert "codec not found" in result["error"]


# ── integration tests (real ffmpeg) ──────────────────────────────────────────


def _make_video(path: str, duration: float, color: str = "blue", size: str = "320x240") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=24",
            "-f", "lavfi", "-i", "aevalsrc=0:c=stereo",
            "-t", str(duration), path,
        ],
        check=True,
        capture_output=True,
    )


def _probe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


@ffmpeg_available
def test_trimmed_clip_exports_correct_duration(tmp_path):
    """A 5s source trimmed to 3s on the timeline should export as ~3s."""
    src = str(tmp_path / "src.mp4")
    _make_video(src, duration=5.0)

    out = str(tmp_path / "out.mp4")
    clip = RenderClip(source_path=src, in_tick=0, out_tick=72, src_in_tick=0)
    result = render_sequence([clip], fps=FPS, output_path=out)

    assert result["ok"] is True
    assert abs(_probe_duration(out) - 3.0) < 0.5


@ffmpeg_available
def test_src_in_tick_seeks_into_source(tmp_path):
    """src_in_tick=120 (5s at 24fps) should seek 5s into the source."""
    src = str(tmp_path / "src.mp4")
    _make_video(src, duration=10.0)

    out = str(tmp_path / "out.mp4")
    clip = RenderClip(
        source_path=src,
        in_tick=0,
        out_tick=48,      # 2s on timeline
        src_in_tick=120,  # start 5s into the source
    )
    result = render_sequence([clip], fps=FPS, output_path=out)

    assert result["ok"] is True
    assert abs(_probe_duration(out) - 2.0) < 0.5


@ffmpeg_available
def test_gap_is_preserved_in_output(tmp_path):
    """Two clips with a 1s gap should produce ~5s total (2+1+2)."""
    src = str(tmp_path / "src.mp4")
    _make_video(src, duration=10.0)

    out = str(tmp_path / "out.mp4")
    clip1 = RenderClip(source_path=src, in_tick=0,  out_tick=48)  # 2s
    clip2 = RenderClip(source_path=src, in_tick=72, out_tick=120) # 2s, 1s gap before
    result = render_sequence([clip1, clip2], fps=FPS, output_path=out)

    assert result["ok"] is True
    assert abs(_probe_duration(out) - 5.0) < 0.5
