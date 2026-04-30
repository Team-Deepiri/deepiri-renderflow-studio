"""AI-powered caption/subtitle generation from audio."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def transcribe_audio(audio_path: str) -> dict[str, Any]:
    """Transcribe audio to text using Whisper."""
    exe = shutil.which("whisper")
    if not exe:
        return {"ok": False, "error": "whisper not found"}

    try:
        proc = subprocess.run(
            [
                exe,
                "--model", "base",
                "--language", "en",
                "--output_format", "json",
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        output_json = audio_path.replace(
            audio_path.split(".")[-1], "json"
        )
        if os.path.exists(output_json):
            with open(output_json) as f:
                data = json.load(f)
            return {"ok": True, "transcript": data.get("text", ""), "segments": data.get("segments", [])}

        return {"ok": True, "transcript": proc.stdout.strip()}

    except Exception as e:
        logger.warning("transcribe_audio: %s", e)
        return {"ok": False, "error": str(e)}


def generate_srt_subtitles(
    audio_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate SRT subtitles from audio."""
    result = transcribe_audio(audio_path)
    if not result.get("ok"):
        return result

    transcript = result.get("transcript", "")
    segments = result.get("segments", [])

    if not segments:
        segments = _simple_segmentize(transcript, audio_path)

    srt_content = _build_srt(segments)

    if output_path is None:
        output_path = audio_path.replace(
            audio_path.split(".")[-1], "srt"
        )

    with open(output_path, "w") as f:
        f.write(srt_content)

    return {"ok": True, "output": output_path, "segments": len(segments)}


def _simple_segmentize(text: str, audio_path: str) -> list[dict]:
    """Simple segmentation by sentences."""
    sentences = text.replace(".", "•").split("•")
    duration = _get_audio_duration(audio_path)

    segments = []
    for i, sent in enumerate(sentences):
        if not sent.strip():
            continue

        start_time = i * (duration / max(1, len(sentences)))
        end_time = start_time + (duration / max(1, len(sentences)))

        segments.append(
            {
                "start": start_time,
                "end": end_time,
                "text": sent.strip(),
            }
        )

    return segments


def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds."""
    exe = shutil.which("ffprobe")
    if not exe:
        return 10.0

    try:
        proc = subprocess.run(
            [
                exe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if proc.returncode == 0 and proc.stdout.strip():
            return float(proc.stdout.strip())

    except Exception:
        pass

    return 10.0


def _build_srt(segments: list[dict]) -> str:
    """Build SRT content from segments."""
    lines = []

    for i, seg in enumerate(segments, 1):
        start = _format_srt_time(seg.get("start", 0))
        end = _format_srt_time(seg.get("end", 0))
        text = seg.get("text", "")

        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    """Format seconds to SRT time format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_vtt_subtitles(
    audio_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate WebVTT subtitles from audio."""
    result = transcribe_audio(audio_path)
    if not result.get("ok"):
        return result

    transcript = result.get("transcript", "")
    segments = result.get("segments", [])

    if not segments:
        segments = _simple_segmentize(transcript, audio_path)

    vtt_content = "WEBVTT\n\n"
    for seg in segments:
        start = _format_vtt_time(seg.get("start", 0))
        end = _format_vtt_time(seg.get("end", 0))
        text = seg.get("text", "")

        vtt_content += f"{start} --> {end}\n"
        vtt_content += f"{text}\n\n"

    if output_path is None:
        output_path = audio_path.replace(
            audio_path.split(".")[-1], "vtt"
        )

    with open(output_path, "w") as f:
        f.write(vtt_content)

    return {"ok": True, "output": output_path, "segments": len(segments)}


def _format_vtt_time(seconds: float) -> str:
    """Format seconds to VTT time format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) / 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def embed_subtitles(
    video_path: str,
    subtitle_path: str,
    output_path: str,
) -> dict[str, Any]:
    """Burn subtitles into video."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    ext = subtitle_path.split(".")[-1]
    if ext == "srt":
        sub_codec = "subtitles"
    else:
        sub_codec = "webvtt"

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", video_path,
                "-vf", f"{sub_codec}='{subtitle_path}'",
                "-c:a", "copy",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path}

    except Exception as e:
        logger.warning("embed_subtitles: %s", e)
        return {"ok": False, "error": str(e)}


def generate_caption_styles() -> dict[str, Any]:
    """List available caption styles."""
    styles = {
        "simple": {
            "font": "Arial",
            "size": 24,
            "color": "white",
            "bg": "black@80%",
        },
        "subtitle": {
            "font": "Arial",
            "size": 28,
            "color": "white",
            "bg": "black@70%",
        },
        "cinematic": {
            "font": "Impact",
            "size": 32,
            "color": "#FFD700",
            "bg": "transparent",
        },
        "news": {
            "font": "Helvetica",
            "size": 32,
            "color": "white",
            "bg": "#000000@80%",
        },
    }

    return {"ok": True, "styles": styles}