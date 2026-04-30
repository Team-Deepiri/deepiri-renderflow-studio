from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.schemas.studio import AiJobCreate, AiJobOut
from app.media import audio_recording, tts_service
from app.media.voice_animation_pipeline import pipeline

router = APIRouter()


@router.get("/audio/check", tags=["audio"])
def check_audio_system() -> dict:
    mic = audio_recording.check_microphone()
    tts = tts_service.check_tts_engines()
    voices = tts_service.list_voices()
    return {"microphone": mic, "tts": tts, "voices": voices}


@router.post("/audio/record/start", tags=["audio"])
def start_recording(output_path: str) -> dict:
    recorder = audio_recording.get_recorder()
    return recorder.start_recording(output_path)


@router.post("/audio/record/stop", tags=["audio"])
def stop_recording() -> dict:
    recorder = audio_recording.get_recorder()
    return recorder.stop_recording()


@router.get("/audio/record/status", tags=["audio"])
def recording_status() -> dict:
    recorder = audio_recording.get_recorder()
    return {"recording": recorder.is_recording()}


@router.post("/tts/generate", tags=["tts"])
def generate_speech(
    text: str,
    output_path: str,
    engine: str = "edge-tts",
    voice: str | None = None,
) -> dict:
    result = tts_service.generate_speech(text, output_path, engine, voice)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "TTS failed"))
    return result


@router.get("/tts/voices", tags=["tts"])
def list_tts_voices() -> dict:
    return tts_service.list_voices()


@router.post("/tts/convert", tags=["tts"])
def convert_audio(
    input_path: str,
    output_path: str,
    sample_rate: int = 48000,
) -> dict:
    result = tts_service.convert_to_wav(input_path, output_path, sample_rate)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Conversion failed"))
    return result


@router.post("/tts/normalize", tags=["tts"])
def normalize_audio(
    input_path: str,
    output_path: str,
    target_db: float = -3.0,
) -> dict:
    result = tts_service.normalize_audio(input_path, output_path, target_db)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Normalization failed"))
    return result


@router.post("/animation/voice", tags=["animation"])
async def generate_voice_animation(
    audio_path: str,
    prompt: str | None = None,
    character_config: dict | None = None,
) -> dict:
    result = await pipeline.run(audio_path, prompt, character_config)
    return result


@router.get("/animation/stages", tags=["animation"])
def animation_stages() -> dict:
    return {"stages": pipeline.stages}