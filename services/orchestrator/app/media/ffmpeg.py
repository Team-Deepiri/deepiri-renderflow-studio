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


def detect_format(path_or_uri: str) -> dict[str, Any]:
    """Detect media format, codec, and container type."""
    probe_result = probe(path_or_uri)
    if not probe_result.get("ok"):
        return probe_result

    ffprobe = probe_result.get("ffprobe", {})
    streams = ffprobe.get("streams", [])
    format_info = ffprobe.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    return {
        "ok": True,
        "container": format_info.get("format_name"),
        "duration_seconds": float(format_info.get("duration", 0)),
        "size_bytes": int(format_info.get("size", 0)),
        "bitrate": int(format_info.get("bit_rate", 0)),
        "video": {
            "codec": video_stream.get("codec_name") if video_stream else None,
            "width": video_stream.get("width") if video_stream else None,
            "height": video_stream.get("height") if video_stream else None,
            "fps": _parse_frame_rate(video_stream.get("r_frame_rate")) if video_stream else None,
            "pix_fmt": video_stream.get("pix_fmt") if video_stream else None,
        } if video_stream else None,
        "audio": {
            "codec": audio_stream.get("codec_name") if audio_stream else None,
            "sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream else None,
            "channels": audio_stream.get("channels") if audio_stream else None,
        } if audio_stream else None,
    }


def _parse_frame_rate(rate_str: str | None) -> float | None:
    """Parse FFmpeg frame rate like '30/1' or '30000/1001'."""
    if not rate_str:
        return None
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/")
            return float(num) / float(den)
        return float(rate_str)
    except (ValueError, ZeroDivisionError):
        return None
