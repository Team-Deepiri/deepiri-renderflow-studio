"""FFmpeg/ffprobe integration for media inspection (optional binary on PATH)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def probe(path_or_uri: str) -> dict[str, Any]:
    """Return ffprobe JSON summary or error stub when ffprobe is missing."""
    exe = shutil.which("ffprobe")
    if not exe:
        return {
            "ok": False,
            "error": "ffprobe not found on PATH",
            "path": path_or_uri,
        }
    try:
        proc = subprocess.run(
            [
                exe,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path_or_uri,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": (proc.stderr or proc.stdout or "ffprobe failed").strip()[:2000],
                "path": path_or_uri,
            }
        data = json.loads(proc.stdout or "{}")
        return {"ok": True, "path": path_or_uri, "ffprobe": data}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.warning("ffprobe: %s", e)
        return {"ok": False, "error": str(e), "path": path_or_uri}


def transcode_proxy(
    input_path: str,
    output_path: str,
    width: int = 854,
    height: int = 480,
    codec: str = "libx264",
    crf: int = 23,
) -> dict[str, Any]:
    """Generate a proxy file with reduced resolution."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found on PATH"}
    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i",
                input_path,
                "-vf",
                f"scale={width}:{height}",
                "-c:v",
                codec,
                "-crf",
                str(crf),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": (proc.stderr or proc.stdout or "ffmpeg failed").strip()[:2000],
            }
        return {"ok": True, "input": input_path, "output": output_path}
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("transcode_proxy: %s", e)
        return {"ok": False, "error": str(e)}


def extract_thumbnail(
    input_path: str,
    output_path: str,
    time_offset: str = "00:00:01.000",
    width: int = 320,
) -> dict[str, Any]:
    """Extract a single thumbnail frame."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found on PATH"}
    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-ss",
                time_offset,
                "-i",
                input_path,
                "-vframes",
                "1",
                "-vf",
                f"scale={width}:-1",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": (proc.stderr or proc.stdout or "ffmpeg failed").strip()[:2000],
            }
        return {"ok": True, "output": output_path}
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("extract_thumbnail: %s", e)
        return {"ok": False, "error": str(e)}


def extract_audio_waveform(
    input_path: str,
    output_path: str,
    samples_per_second: int = 10,
) -> dict[str, Any]:
    """Extract audio as PCM waveform data for visualization."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found on PATH"}
    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i",
                input_path,
                "-ac",
                "1",
                "-ar",
                str(samples_per_second),
                "-f",
                "s16le",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": (proc.stderr or proc.stdout or "ffmpeg failed").strip()[:2000],
            }
        return {"ok": True, "output": output_path}
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("extract_audio_waveform: %s", e)
        return {"ok": False, "error": str(e)}
