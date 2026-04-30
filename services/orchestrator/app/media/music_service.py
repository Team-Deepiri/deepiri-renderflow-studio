"""AI music and soundtrack generation service."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def check_music_engines() -> dict[str, Any]:
    """Check available music generation tools."""
    engines = []

    if shutil.which("musicgen"):
        engines.append("musicgen")
    if shutil.which("suno"):
        engines.append("suno")
    if shutil.which("audiocraft"):
        engines.append("audiocraft")

    return {"ok": True, "engines": engines, "count": len(engines)}


def generate_music(
    prompt: str,
    output_path: str,
    duration_secs: float = 30.0,
    style: str = "cinematic",
) -> dict[str, Any]:
    """Generate music from text prompt."""
    exe = shutil.which("musicgen")
    if not exe:
        return {"ok": False, "error": "musicgen not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        proc = subprocess.run(
            [
                exe,
                "--prompt", prompt,
                "--duration", str(duration_secs),
                "--output", output_path,
            ],
            capture_output=True,
            text=True,
            timeout=duration_secs + 60,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "duration": duration_secs}

    except Exception as e:
        logger.warning("generate_music: %s", e)
        return {"ok": False, "error": str(e)}


MUSIC_STYLES = {
    "cinematic": {
        "tags": ["orchestra", "epic", "trailer"],
        "tempo": "slow",
        "key": "minor",
    },
    "electronic": {
        "tags": ["synth", "beat", "edm"],
        "tempo": "fast",
        "key": "minor",
    },
    "ambient": {
        "tags": ["drone", "texture", "atmospheric"],
        "tempo": "slow",
        "key": "major",
    },
    "corporate": {
        "tags": ["positive", "uplifting", "business"],
        "tempo": "medium",
        "key": "major",
    },
    "horror": {
        "tags": ["dark", "tension", "scary"],
        "tempo": "slow",
        "key": "minor",
    },
    "comedy": {
        "tags": ["funny", "whimsical", "quirky"],
        "tempo": "medium",
        "key": "major",
    },
    "romance": {
        "tags": ["love", "tender", "warm"],
        "tempo": "slow",
        "key": "major",
    },
    "action": {
        "tags": ["intense", "driving", "rock"],
        "tempo": "fast",
        "key": "minor",
    },
}


def list_music_styles() -> dict[str, Any]:
    """List available music styles."""
    return {"ok": True, "styles": MUSIC_STYLES}


def generate_from_style(
    output_path: str,
    style: str = "cinematic",
    duration_secs: float = 30.0,
) -> dict[str, Any]:
    """Generate music from style preset."""
    style_info = MUSIC_STYLES.get(style, MUSIC_STYLES["cinematic"])
    prompt = ", ".join(style_info.get("tags", []))

    return generate_music(prompt, output_path, duration_secs, style)


def adjust_tempo(
    input_path: str,
    output_path: str,
    tempo_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Adjust music tempo."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", input_path,
                "-filter:a", f"atempo={tempo_multiplier}",
                "-ar", "48000",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "tempo": tempo_multiplier}

    except Exception as e:
        logger.warning("adjust_tempo: %s", e)
        return {"ok": False, "error": str(e)}


def mix_tracks(
    tracks: list[str],
    output_path: str,
    volumes: list[float] | None = None,
) -> dict[str, Any]:
    """Mix multiple audio tracks."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    if volumes is None:
        volumes = [1.0 / len(tracks)] * len(tracks)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    inputs = []
    for track in tracks:
        inputs.extend(["-i", track])

    filter_str = ""
    for i in range(len(tracks)):
        vol = volumes[i] if i < len(volumes) else 1.0
        filter_str += f"[{i}:a]volume={vol}[a{i}];"
    for i in range(len(tracks)):
        filter_str += f"[a{i}]"
    filter_str += f"amix=inputs={len(tracks)}:duration=longest[aout]"

    try:
        proc = subprocess.run(
            [exe, "-y"] + inputs + ["-filter_complex", filter_str, "-map", "[aout]", output_path],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "tracks": len(tracks)}

    except Exception as e:
        logger.warning("mix_tracks: %s", e)
        return {"ok": False, "error": str(e)}


def add_fade(
    input_path: str,
    output_path: str,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
) -> dict[str, Any]:
    """Add fade in/out to audio."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    filters = []
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        filters.append(f"afade=t=out:st=-{fade_out}:d={fade_out}")

    if not filters:
        return {"ok": False, "error": "no fade specified"}

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", input_path,
                "-af", ",".join(filters),
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "fade_in": fade_in, "fade_out": fade_out}

    except Exception as e:
        logger.warning("add_fade: %s", e)
        return {"ok": False, "error": str(e)}


def loop_audio(
    input_path: str,
    output_path: str,
    target_duration: float,
) -> dict[str, Any]:
    """Loop audio to target duration."""
    current_dur = _get_duration(input_path)
    if current_dur <= 0:
        return {"ok": False, "error": "cannot determine duration"}

    loops = int(target_duration / current_dur) + 1
    segments = [input_path] * loops

    return mix_tracks(segments, output_path)


def _get_duration(audio_path: str) -> float:
    """Get audio duration."""
    exe = shutil.which("ffprobe")
    if not exe:
        return 0.0

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

    return 0.0