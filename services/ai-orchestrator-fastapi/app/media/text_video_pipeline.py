"""Text-to-video generation pipeline."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VIDEO_STAGES = [
    "script_generation",
    "storyboard",
    "asset_generation",
    "scene_composition",
    "animation",
    "effects",
    "color_grade",
    "final_render",
]


def check_video_engines() -> dict[str, Any]:
    """Check available video generation tools."""
    engines = []

    if shutil.which("sdxl"):
        engines.append("sdxl")
    if shutil.which("comfy"):
        engines.append("comfyui")
    if shutil.which("ffmpeg"):
        engines.append("ffmpeg")

    return {"ok": True, "engines": engines, "count": len(engines)}


def generate_video_from_text(
    prompt: str,
    output_path: str,
    duration_secs: float = 5.0,
    style: str = "cinematic",
) -> dict[str, Any]:
    """Generate video from text prompt."""
    exe = shutil.which("sdxl")
    if not exe:
        return {"ok": False, "error": "sdxl not available"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        proc = subprocess.run(
            [
                exe,
                "--prompt", prompt,
                "--output", output_path,
                "--duration", str(duration_secs),
                "--style", style,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "duration": duration_secs}

    except Exception as e:
        logger.warning("generate_video_from_text: %s", e)
        return {"ok": False, "error": str(e)}


def generate_storyboard(
    prompt: str,
    num_scenes: int = 4,
) -> dict[str, Any]:
    """Generate storyboard from script/prompt."""
    scenes = []
    prompt_lower = prompt.lower()

    topics = _extract_topics(prompt_lower, num_scenes)
    for i, topic in enumerate(topics):
        scenes.append(
            {
                "scene_id": i + 1,
                "description": topic,
                "duration_sec": max(2.0, 60.0 / num_scenes),
                "camera": _suggest_camera(i, num_scenes),
                "action": _suggest_action(i, num_scenes),
                "mood": _suggest_mood(topic),
            }
        )

    return {"ok": True, "scenes": scenes, "count": len(scenes)}


def _extract_topics(text: str, num: int) -> list[str]:
    """Extract topics from text."""
    sentences = text.replace(".", ";").split(";")
    topics = [s.strip() for s in sentences if s.strip()]
    if not topics:
        topics = [f"Scene about {text[:20]}" for _ in range(num)]
    return topics[:num] or topics


def _suggest_camera(scene_idx: int, total: int) -> str:
    """Suggest camera movement."""
    if scene_idx == 0:
        return "wide establishing"
    elif scene_idx == total - 1:
        return "pull back"
    elif scene_idx % 2 == 0:
        return "pan left"
    else:
        return "pan right"


def _suggest_action(scene_idx: int, total: int) -> str:
    """Suggest action."""
    if scene_idx == 0:
        return "enter frame"
    elif scene_idx == total - 1:
        return "exit frame"
    else:
        return "dialog action"


def _suggest_mood(text: str) -> str:
    """Suggest mood from text."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["dark", "sad", "lost", "miss"]):
        return "melancholic"
    elif any(w in text_lower for w in ["happy", "joy", "great", "amazing"]):
        return "uplifting"
    elif any(w in text_lower for w in ["action", "run", "fight", "chase"]):
        return "intense"
    else:
        return "neutral"


def generate_image_sequence(
    storyboard: list[dict],
    output_dir: str,
    width: int = 1024,
    height: int = 576,
) -> dict[str, Any]:
    """Generate image sequence from storyboard."""
    os.makedirs(output_dir, exist_ok=True)

    frames = []
    for scene in storyboard:
        frame_path = f"{output_dir}/frame_{scene['scene_id']:03d}.png"
        result = generate_video_from_text(
            scene.get("description", ""),
            frame_path,
            duration_secs=scene.get("duration_sec", 3.0),
        )
        if result.get("ok"):
            frames.append(frame_path)

    return {"ok": True, "frames": frames, "count": len(frames)}


def images_to_video(
    frame_dir: str,
    output_path: str,
    fps: int = 24,
) -> dict[str, Any]:
    """Convert image sequence to video."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-framerate", str(fps),
                "-i", f"{frame_dir}/frame_%03d.png",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "18",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "fps": fps}

    except Exception as e:
        logger.warning("images_to_video: %s", e)
        return {"ok": False, "error": str(e)}


def compose_video_with_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
) -> dict[str, Any]:
    """Compose video with audio track."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
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
        logger.warning("compose_video_with_audio: %s", e)
        return {"ok": False, "error": str(e)}


def add_text_overlay(
    video_path: str,
    output_path: str,
    text: str,
    position: str = "bottom",
    font_size: int = 24,
) -> dict[str, Any]:
    """Add text overlay to video."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    y_pos = "h-th-40" if position == "bottom" else "40"
    fontfile = "arial" if os.name == "nt" else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", video_path,
                "-vf", f"drawtext=text='{text}':fontfile={fontfile}:fontsize={font_size}:x=(w-text_w)/2:y={y_pos}:borderw=2:bordercolor=black:alpha=0.8",
                "-c:a", "copy",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path}

    except Exception as e:
        logger.warning("add_text_overlay: %s", e)
        return {"ok": False, "error": str(e)}


class TextToVideoPipeline:
    def __init__(self) -> None:
        self.stages = VIDEO_STAGES

    def run(
        self,
        prompt: str,
        output_path: str,
        audio_path: str | None = None,
        add_captions: bool = False,
    ) -> dict[str, Any]:
        """Run full text-to-video pipeline."""
        job_id = str(uuid.uuid4())

        storyboard = generate_storyboard(prompt)
        output_dir = f"/tmp/{job_id}"
        frames_result = generate_image_sequence(storyboard.get("scenes", []), output_dir)

        video_result = images_to_video(output_dir, output_path)

        if audio_path and video_result.get("ok"):
            video_result = compose_video_with_audio(output_path, audio_path, output_path)

        if add_captions and video_result.get("ok"):
            for i, scene in enumerate(storyboard.get("scenes", [])):
                scene_text = scene.get("description", "")
                add_text_overlay(output_path, output_path, scene_text)

        return {
            "ok": video_result.get("ok", False),
            "job_id": job_id,
            "stages": self.stages,
            "storyboard": storyboard.get("scenes", []),
            "output": video_result.get("output", ""),
        }


pipeline = TextToVideoPipeline()