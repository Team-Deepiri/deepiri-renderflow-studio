"""Text-to-speech and voice-over generation service."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def check_tts_engines() -> dict[str, Any]:
    """Check available TTS engines."""
    engines = []

    if shutil.which("edge-tts"):
        engines.append("edge-tts")
    if shutil.which("piper"):
        engines.append("piper")
    if shutil.which("espeak"):
        engines.append("espeak")

    return {"ok": True, "engines": engines, "count": len(engines)}


def generate_speech_edge(
    text: str,
    output_path: str,
    voice: str = "en-US-AriaNeural",
    rate: str = "+0%",
    pitch: str = "+0%",
) -> dict[str, Any]:
    """Generate speech using Edge TTS."""
    exe = shutil.which("edge-tts")
    if not exe:
        return {"ok": False, "error": "edge-tts not installed"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        proc = subprocess.run(
            [exe, "--voice", voice, "--write-media", output_path, "--text", text],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500] if proc.stderr else "edge-tts failed"}

        return {"ok": True, "output": output_path, "engine": "edge-tts", "voice": voice}

    except Exception as e:
        logger.warning("generate_speech_edge: %s", e)
        return {"ok": False, "error": str(e)}


def generate_speech_piper(
    text: str,
    output_path: str,
    model: str = "en_US-lessac-medium",
) -> dict[str, Any]:
    """Generate speech using Piper TTS."""
    exe = shutil.which("piper")
    if not exe:
        return {"ok": False, "error": "piper not installed"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    model_path = model
    if not model_path.endswith(".onnx"):
        model_path = f"/tmp/{model}.onnx"

    try:
        proc = subprocess.run(
            [exe, "--model", model_path, "--output_file", output_path],
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500] if proc.stderr else "piper failed"}

        return {"ok": True, "output": output_path, "engine": "piper", "model": model}

    except Exception as e:
        logger.warning("generate_speech_piper: %s", e)
        return {"ok": False, "error": str(e)}


def generate_speech(
    text: str,
    output_path: str,
    engine: str = "edge-tts",
    voice: str | None = None,
) -> dict[str, Any]:
    """Generate speech with auto-detected engine."""
    if engine == "edge-tts":
        return generate_speech_edge(text, output_path, voice or "en-US-AriaNeural")
    elif engine == "piper":
        return generate_speech_piper(text, output_path, voice or "en_US-lessac-medium")
    else:
        return generate_speech_edge(text, output_path)


def convert_to_wav(input_path: str, output_path: str, sample_rate: int = 48000) -> dict[str, Any]:
    """Convert audio file to WAV format."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i",
                input_path,
                "-ar",
                str(sample_rate),
                "-ac",
                "1",
                "-acodec",
                "pcm_s16le",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500] if proc.stderr else "conversion failed"}

        return {"ok": True, "output": output_path, "sample_rate": sample_rate}

    except Exception as e:
        logger.warning("convert_to_wav: %s", e)
        return {"ok": False, "error": str(e)}


def normalize_audio(input_path: str, output_path: str, target_db: float = -3.0) -> dict[str, Any]:
    """Normalize audio to target loudness."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i",
                input_path,
                "-af",
                f"loudnorm=I={target_db}:TP=-1.5:LRA=11",
                "-ar",
                "48000",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500] if proc.stderr else "normalization failed"}

        return {"ok": True, "output": output_path}

    except Exception as e:
        logger.warning("normalize_audio: %s", e)
        return {"ok": False, "error": str(e)}


AVAILABLE_VOICES = {
    "en-US-AriaNeural": {"name": "Aria", "gender": "Female", "style": "newscast"},
    "en-US-GuyNeural": {"name": "Guy", "gender": "Male", "style": "newscast"},
    "en-US-JennyNeural": {"name": "Jenny", "gender": "Female", "style": "conversational"},
    "en-US-SaraNeural": {"name": "Sara", "gender": "Female", "style": "cheerful"},
    "en-US-TonyNeural": {"name": "Tony", "gender": "Male", "style": "aggressive"},
    "en-GB-SoniaNeural": {"name": "Sonia", "gender": "Female", "style": "newscast"},
    "en-GB-RyanNeural": {"name": "Ryan", "gender": "Male", "style": "newscast"},
}


def list_voices() -> dict[str, Any]:
    """List available TTS voices."""
    return {"ok": True, "voices": AVAILABLE_VOICES}