from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.guardrails import check_prompt
from app.media import (
    caption_service,
    music_service,
    text_video_pipeline,
    video_composition,
)

router = APIRouter()


@router.get("/video/check", tags=["video"])
def check_video_engines() -> dict:
    return text_video_pipeline.check_video_engines()


@router.post("/video/generate", tags=["video"])
def generate_video(
    prompt: str,
    output_path: str,
    duration_secs: float = 5.0,
    style: str = "cinematic",
) -> dict:
    check_prompt(prompt)
    result = text_video_pipeline.generate_video_from_text(
        prompt, output_path, duration_secs, style
    )
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Video generation failed"))
    return result


@router.post("/video/storyboard", tags=["video"])
def generate_storyboard(prompt: str, num_scenes: int = 4) -> dict:
    check_prompt(prompt)
    return text_video_pipeline.generate_storyboard(prompt, num_scenes)


@router.post("/video/render", tags=["video"])
def render_images_to_video(frame_dir: str, output_path: str, fps: int = 24) -> dict:
    result = text_video_pipeline.images_to_video(frame_dir, output_path, fps)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Render failed"))
    return result


@router.get("/caption/styles", tags=["caption"])
def list_caption_styles() -> dict:
    return caption_service.generate_caption_styles()


@router.post("/caption/transcribe", tags=["caption"])
def transcribe_audio(audio_path: str) -> dict:
    result = caption_service.transcribe_audio(audio_path)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Transcription failed"))
    return result


@router.post("/caption/generate", tags=["caption"])
def generate_subtitles(audio_path: str, format: str = "srt") -> dict:
    if format == "srt":
        result = caption_service.generate_srt_subtitles(audio_path)
    else:
        result = caption_service.generate_vtt_subtitles(audio_path)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Subtitle generation failed"))
    return result


@router.post("/caption/embed", tags=["caption"])
def embed_subtitles(video_path: str, subtitle_path: str, output_path: str) -> dict:
    result = caption_service.embed_subtitles(video_path, subtitle_path, output_path)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Embed failed"))
    return result


@router.get("/music/styles", tags=["music"])
def list_music_styles() -> dict:
    return music_service.list_music_styles()


@router.post("/music/generate", tags=["music"])
def generate_music(
    prompt: str,
    output_path: str,
    duration_secs: float = 30.0,
    style: str = "cinematic",
) -> dict:
    check_prompt(prompt)
    result = music_service.generate_music(prompt, output_path, duration_secs, style)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Music generation failed"))
    return result


@router.post("/music/by_style", tags=["music"])
def generate_by_style(output_path: str, style: str, duration_secs: float = 30.0) -> dict:
    result = music_service.generate_from_style(output_path, style, duration_secs)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Music generation failed"))
    return result


@router.post("/music/mix", tags=["music"])
def mix_audio_tracks(tracks: list[str], output_path: str, volumes: list[float] | None = None) -> dict:
    result = music_service.mix_tracks(tracks, output_path, volumes)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Mix failed"))
    return result


@router.get("/composition/stages", tags=["composition"])
def composition_stages() -> dict:
    return {"stages": video_composition.pipeline.stages}


@router.get("/composition/luts", tags=["composition"])
def list_luts() -> dict:
    return video_composition.list_luts()


@router.post("/composition/compose", tags=["composition"])
def compose_media(
    video_path: str | None,
    audio_path: str | None,
    music_path: str | None,
    output_path: str,
) -> dict:
    result = video_composition.compose_multimedia(video_path, audio_path, music_path, output_path)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Composition failed"))
    return result


@router.post("/composition/lut", tags=["composition"])
def apply_lut(video_path: str, output_path: str, lut: str = "cinematic") -> dict:
    result = video_composition.apply_lut(video_path, output_path, lut)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "LUT application failed"))
    return result


@router.post("/composition/pip", tags=["composition"])
def create_pip(
    base_path: str,
    overlay_path: str,
    output_path: str,
    position: str = "bottom_right",
    scale: float = 0.25,
) -> dict:
    result = video_composition.create_picture_in_picture(
        base_path, overlay_path, output_path, position, scale
    )
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "PIP failed"))
    return result


@router.post("/composition/grid", tags=["composition"])
def create_video_grid(inputs: list[str], output_path: str, cols: int = 2) -> dict:
    result = video_composition.create_grid(inputs, output_path, cols)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Grid failed"))
    return result


@router.post("/composition/full", tags=["composition"])
def run_full_composition(project_config: dict) -> dict:
    return video_composition.pipeline.run_full_composition(project_config)