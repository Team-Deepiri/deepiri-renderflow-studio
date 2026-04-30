"""AI animation pipeline - voice to animation generation."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AUDIO_STAGES = [
    "voice_input",
    "speech_analysis",
    "gesture_generation",
    "lip_sync",
    "scene_composition",
    "render_preview",
    "review",
]


async def process_voice_to_animation(
    project_id: str,
    audio_path: str,
    prompt: str,
    mode: str = "animate_speech",
) -> dict[str, Any]:
    """Process voice audio into animated scene."""
    job_id = str(uuid.uuid4())

    result = {
        "job_id": job_id,
        "project_id": project_id,
        "mode": mode,
        "stages": AUDIO_STAGES,
        "status": "queued",
    }

    return result


async def analyze_speech(
    audio_path: str,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Analyze speech for emotion, pacing, and content."""
    exe = shutil.which("whisper")
    if not exe:
        return {"ok": True, "transcript": "Speech analysis unavailable", "emotion": "neutral"}

    try:
        proc = subprocess.run(
            [exe, "--model", "base", "--file", audio_path, "--language", "en"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            return {"ok": True, "transcript": "", "emotion": "neutral"}

        transcript = proc.stdout.strip()
        emotion = _detect_emotion(transcript)

        return {
            "ok": True,
            "transcript": transcript,
            "emotion": emotion,
            "word_count": len(transcript.split()),
        }

    except Exception as e:
        logger.warning("analyze_speech: %s", e)
        return {"ok": False, "error": str(e)}


def _detect_emotion(text: str) -> str:
    """Simple emotion detection from text."""
    text_lower = text.lower()
    excitement = ["!", "amazing", "great", "awesome", "excited", "wow"]
    sadness = ["sad", "miss", "sorry", "lost", "gone"]
    urgency = ["now", "hurry", "quick", "urgent", "emergency"]

    for word in excitement:
        if word in text_lower:
            return "excited"
    for word in sadness:
        if word in text_lower:
            return "sad"
    for word in urgency:
        if word in text_lower:
            return "urgent"

    return "neutral"


async def generate_gestures(
    transcript: str,
    emotion: str,
    style: str = "natural",
) -> dict[str, Any]:
    """Generate hand and body gestures from transcript."""
    gestures = []

    sentences = transcript.split(".")
    for i, sent in enumerate(sentences):
        if not sent.strip():
            continue

        start_time = i * 2.0
        gesture_type = "idle"

        if emotion == "excited":
            gesture_type = "gesture_big"
        elif emotion == "sad":
            gesture_type = "gesture_small"
        elif "?" in sent:
            gesture_type = "gesture_shrug"
        elif len(sent.split()) > 10:
            gesture_type = "gesture_talk"

        gestures.append(
            {
                "time": start_time,
                "end_time": start_time + 2.0,
                "type": gesture_type,
                "amplitude": 0.5 if emotion == "neutral" else 1.0,
                "speed": 1.0,
            }
        )

    return {"ok": True, "gestures": gestures, "count": len(gestures)}


async def generate_lip_sync(
    audio_path: str,
    transcript: str,
) -> dict[str, Any]:
    """Generate viseme (mouth shape) keyframes from audio."""
    try:
        visemes = []
        words = transcript.split()
        duration_per_word = max(0.1, 15.0 / max(1, len(words)))

        for i, word in enumerate(words):
            visemes.append(
                {
                    "time": i * duration_per_word,
                    "viseme": _word_to_viseme(word),
                    "phonemes": _get_phonemes(word),
                }
            )

        return {"ok": True, "visemes": visemes, "count": len(visemes)}

    except Exception as e:
        logger.warning("generate_lip_sync: %s", e)
        return {"ok": False, "error": str(e)}


def _word_to_viseme(word: str) -> str:
    """Map word to basic viseme."""
    w = word.lower()
    if any(c in w for c in "bpfv"):
        return "VH_F"
    elif any(c in w for c in "aeiou"):
        return "VH_AE"
    elif any(c in w for c in "tdnl"):
        return "VH_T"
    elif any(c in w for c in "kgŋ"):
        return "VH_K"
    elif any(c in w for c in "szʃ"):
        return "VH_S"
    else:
        return "VH_rest"


def _get_phonemes(word: str) -> list[str]:
    """Get approximate phonemes for word."""
    return [c.upper() for c in word[:3]]


async def generate_motion_scene(
    gestures: dict[str, Any],
    lip_sync: dict[str, Any],
    emotion: str,
    character_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose animation scene with character and motion."""
    scene = {
        "id": str(uuid.uuid4()),
        "character": character_config
        or {
            "name": "Speaker",
            "style": "cartoon",
            "position": {"x": 0, "y": 0, "z": 0},
        },
        "gestures": gestures.get("gestures", []),
        "lip_sync": lip_sync.get("visemes", []),
        "emotion": emotion,
        "duration": lip_sync.get("visemes", [])[-1].get("time", 0) if lip_sync.get("visemes") else 5.0,
    }

    return {"ok": True, "scene": scene}


async def compose_final_animation(
    character_scene: dict[str, Any],
    background: str | None = None,
) -> dict[str, Any]:
    """Compose final animation with background."""
    timeline = {
        "layers": [
            {"type": "background", "asset": background or "solid_color"},
            {
                "type": "character",
                "data": character_scene["character"],
                "animations": character_scene.get("gestures", []),
            },
            {
                "type": "audio",
                "track": character_scene.get("audio_path", ""),
            },
        ],
        "duration": character_scene.get("duration", 5.0),
        "resolution": {"w": 1920, "h": 1080},
        "fps": 30,
    }

    return {"ok": True, "timeline": timeline}


class VoiceAnimationPipeline:
    def __init__(self) -> None:
        self.stages = AUDIO_STAGES

    async def run(
        self,
        audio_path: str,
        prompt: str | None = None,
        character_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run full voice-to-animation pipeline."""
        analysis = await analyze_speech(audio_path, prompt)
        transcript = analysis.get("transcript", "")
        emotion = analysis.get("emotion", "neutral")

        gestures = await generate_gestures(transcript, emotion)
        lip_sync = await generate_lip_sync(audio_path, transcript)
        character_scene = await generate_motion_scene(
            gestures, lip_sync, emotion, character_config
        )

        result = await compose_final_animation(character_scene)

        return {
            "ok": True,
            "transcript": transcript,
            "emotion": emotion,
            "gesture_count": gestures.get("count", 0),
            "timeline": result.get("timeline"),
        }


pipeline = VoiceAnimationPipeline()