"""Render worker — assembles trimmed timeline clips into a final export."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RenderClip:
    source_path: str
    in_tick: int
    out_tick: int
    src_in_tick: int = 0
    speed_ratio: float = 1.0


def render_sequence(
    clips: list[RenderClip],
    fps: int,
    output_path: str,
    resolution_w: int = 1920,
    resolution_h: int = 1080,
) -> dict[str, Any]:
    """Render a list of trimmed clips with gap padding into output_path.

    Each clip's in_tick/out_tick define its position on the timeline.
    src_in_tick defines the offset into the source file (head trim / slip).
    Gaps between clips are filled with black+silent padding.
    """
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    if not clips:
        return {"ok": False, "error": "no clips to render"}

    for clip in clips:
        if not Path(clip.source_path).exists():
            return {"ok": False, "error": f"source not found: {clip.source_path}"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        segments: list[str] = []
        prev_out_tick = 0

        for i, clip in enumerate(sorted(clips, key=lambda c: c.in_tick)):
            gap_ticks = clip.in_tick - prev_out_tick
            if gap_ticks > 0:
                gap_sec = gap_ticks / fps
                gap_path = os.path.join(tmp_dir, f"gap_{i}.mp4")
                result = _black_segment(exe, gap_sec, resolution_w, resolution_h, fps, gap_path)
                if not result["ok"]:
                    return result
                segments.append(gap_path)

            start_sec = clip.src_in_tick / fps
            duration_sec = (clip.out_tick - clip.in_tick) / fps / clip.speed_ratio
            seg_path = os.path.join(tmp_dir, f"seg_{i}.mp4")
            result = _trim_clip(exe, clip.source_path, start_sec, duration_sec, resolution_w, resolution_h, fps, seg_path)
            if not result["ok"]:
                return result
            segments.append(seg_path)

            prev_out_tick = clip.out_tick

        if len(segments) == 1:
            shutil.copy2(segments[0], output_path)
            return {"ok": True, "output": output_path, "segments": 1}

        return _concat_segments(exe, segments, tmp_dir, output_path)


def _trim_clip(
    exe: str,
    source_path: str,
    start_sec: float,
    duration_sec: float,
    width: int,
    height: int,
    fps: int,
    output_path: str,
) -> dict[str, Any]:
    cmd = [
        exe, "-y",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", source_path,
        "-vf", f"scale={width}:{height}",
        "-r", str(fps),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _black_segment(
    exe: str,
    duration_sec: float,
    width: int,
    height: int,
    fps: int,
    output_path: str,
) -> dict[str, Any]:
    cmd = [
        exe, "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}",
        "-f", "lavfi", "-i", "aevalsrc=0:c=stereo",
        "-t", str(duration_sec),
        "-c:v", "libx264",
        "-c:a", "aac",
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _concat_segments(
    exe: str,
    segments: list[str],
    tmp_dir: str,
    output_path: str,
) -> dict[str, Any]:
    concat_list = os.path.join(tmp_dir, "concat.txt")
    with open(concat_list, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")

    cmd = [
        exe, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list,
        "-c", "copy",
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}
        return {"ok": True, "output": output_path, "segments": len(segments)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
