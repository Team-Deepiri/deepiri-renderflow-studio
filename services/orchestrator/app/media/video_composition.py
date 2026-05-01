"""Video composition pipeline - brings all media together."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COMPOSITION_STAGES = [
    "timeline_setup",
    "video_import",
    "audio_sync",
    "effects_stack",
    "transitions",
    "titles",
    "color_grade",
    "render",
]


def compose_multimedia(
    video_path: str | None,
    audio_path: str | None,
    music_path: str | None,
    output_path: str,
) -> dict[str, Any]:
    """Compose video with audio tracks."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    inputs = []
    filters = []
    map_v = "0:v"
    map_a = "0:a"

    if video_path and video_path != output_path:
        inputs.extend(["-i", video_path])

    if audio_path:
        inputs.extend(["-i", audio_path])
        map_a = f"{len(inputs) - 1}:a"

    if music_path:
        inputs.extend(["-i", music_path])
        if audio_path:
            filter_str = f"[{len(inputs) - 1}:a]volume=0.3[music];[{len(inputs) - 2}:a][music]amix=inputs=2:duration=longest[aout]"
            filters.append(filter_str)
            map_a = "[aout]"

    cmd = [exe, "-y"]
    cmd.extend(inputs)
    if filters:
        cmd.extend(["-filter_complex", ";".join(filters)])
    cmd.extend(["-map", map_v, "-map", map_a, "-shortest", output_path])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path}

    except Exception as e:
        logger.warning("compose_multimedia: %s", e)
        return {"ok": False, "error": str(e)}


def add_transition(
    input_path: str,
    output_path: str,
    transition_type: str = "fade",
    duration: float = 0.5,
) -> dict[str, Any]:
    """Add transition between scenes."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    trans_map = {
        "fade": f"fade=t=in:st=0:d={duration},fade=t=out:st=-{duration}:d={duration}",
        "dissolve": f"fade=t=in:st=0:d={duration}",
        "wipe_left": "fade",
        "slide_left": "fade",
    }

    vf = trans_map.get(transition_type, trans_map["fade"])

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", input_path,
                "-vf", vf,
                "-c:a", "copy",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "transition": transition_type}

    except Exception as e:
        logger.warning("add_transition: %s", e)
        return {"ok": False, "error": str(e)}


def apply_lut(
    input_path: str,
    output_path: str,
    lut_name: str = "cinematic",
) -> dict[str, Any]:
    """Apply color LUT to video."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    luts = {
        "cinematic": "colorchart=contrast=1.1:saturation=0.9:gamma=1.1",
        "noir": "colorchart=contrast=1.3:saturation=0.3:gamma=1.2",
        "vintage": "colorchart=contrast=0.9:saturation=0.7:gamma=1.2",
        "vibrant": "colorchart=contrast=1.2:saturation=1.3",
        "muted": "colorchart=contrast=0.95:saturation=0.6",
        "warm": "colorchart=contrast=1.0:saturation=1.1:gamma=1.15",
        "cool": "colorchart=contrast=1.0:saturation=0.9:gamma=0.95",
    }

    lut = luts.get(lut_name, luts["cinematic"])

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", input_path,
                "-vf", lut,
                "-c:a", "copy",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "lut": lut_name}

    except Exception as e:
        logger.warning("apply_lut: %s", e)
        return {"ok": False, "error": str(e)}


def list_luts() -> dict[str, Any]:
    """List available LUTs."""
    luts = {
        "cinematic": "Balanced contrast and saturation",
        "noir": "High contrast, desaturated",
        "vintage": "Retro faded look",
        "vibrant": "Saturated and punchy",
        "muted": "Low saturation, soft",
        "warm": "Yellow/orange tones",
        "cool": "Blue tones",
    }
    return {"ok": True, "luts": luts}


def create_picture_in_picture(
    base_path: str,
    overlay_path: str,
    output_path: str,
    position: str = "bottom_right",
    scale: float = 0.25,
) -> dict[str, Any]:
    """Create picture-in-picture."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    positions = {
        "top_left": "10:10",
        "top_right": "W-w-10:10",
        "bottom_left": "10:H-h-10",
        "bottom_right": "W-w-10:H-h-10",
        "center": "(W-w)/2:(H-h)/2",
    }

    pos = positions.get(position, positions["bottom_right"])

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", base_path,
                "-i", overlay_path,
                "-filter_complex",
                f"[1:v]scale=iw*{scale}:ih*{scale}[pip];[0:v][pip]overlay={pos}",
                "-c:a", "copy",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "position": position}

    except Exception as e:
        logger.warning("create_picture_in_picture: %s", e)
        return {"ok": False, "error": str(e)}


def create_grid(
    inputs: list[str],
    output_path: str,
    cols: int = 2,
    spacing: int = 10,
) -> dict[str, Any]:
    """Create grid layout from multiple videos."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    if not inputs:
        return {"ok": False, "error": "no inputs"}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    filter_chain = ""
    for i, inp in enumerate(inputs):
        filter_chain += f"[{i}:v]"
    filter_chain += f"xstack=inputs={len(inputs)}:layout="

    layouts = []
    for i in range(len(inputs)):
        row = i // cols
        col = i % cols
        layouts.append(f"{col}_0_{row}_0")

    filter_chain += "_".join(layouts)

    inputs_cmd = []
    for inp in inputs:
        inputs_cmd.extend(["-i", inp])

    try:
        proc = subprocess.run(
            [exe, "-y"] + inputs_cmd + ["-filter_complex", filter_chain, "-c:v", "libx264", output_path],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}

        return {"ok": True, "output": output_path, "inputs": len(inputs), "cols": cols}

    except Exception as e:
        logger.warning("create_grid: %s", e)
        return {"ok": False, "error": str(e)}


def stabilize_video(input_path: str, output_path: str) -> dict[str, Any]:
    """Stabilize shaky video."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    try:
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-i", input_path,
                "-vf", "deshake",
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
        logger.warning("stabilize_video: %s", e)
        return {"ok": False, "error": str(e)}


def speed_ramp(
    input_path: str,
    output_path: str,
    segments: list[dict],
) -> dict[str, Any]:
    """Create speed ramp (slow-mo, fast) segments."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "error": "ffmpeg not found"}

    temp_dir = f"/tmp/speed_ramp_{uuid.uuid4().hex[:8]}"
    os.makedirs(temp_dir, exist_ok=True)

    for i, seg in enumerate(segments):
        speed = seg.get("speed", 1.0)
        out = f"{temp_dir}/seg_{i}.mp4"

        try:
            proc = subprocess.run(
                [
                    exe,
                    "-y",
                    "-i", input_path,
                    "-filter:v", f"setpts={1.0/speed}*PTS",
                    "-filter:a", f"atempo={speed}",
                    "-ss", str(seg.get("start", 0)),
                    "-t", str(seg.get("duration", 1)),
                    out,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

        except Exception:
            pass

    segments_list = [f"{temp_dir}/seg_{i}.mp4" for i in range(len(segments))]
    result = mix_tracks(segments_list, output_path)

    shutil.rmtree(temp_dir, ignore_errors=True)

    return result


class VideoCompositionPipeline:
    def __init__(self) -> None:
        self.stages = COMPOSITION_STAGES


class EffectsChain:
    def __init__(self) -> None:
        self.effects: list[Effect] = []
        self._cache: dict[str, Any] = {}

    def add_effect(self, effect: "Effect") -> "EffectsChain":
        self.effects.append(effect)
        return self

    def build_filter_graph(self) -> str:
        parts = []
        for effect in self.effects:
            parts.append(effect.to_filter())
        return ";".join(parts)

    def clear_cache(self) -> None:
        self._cache.clear()


class Effect:
    def __init__(self, name: str) -> None:
        self.name = name
        self.params: dict[str, Any] = {}

    def param(self, key: str, value: Any) -> "Effect":
        self.params[key] = value
        return self

    def to_filter(self) -> str:
        return self.name


class ColorGradeEffect(Effect):
    def __init__(self) -> None:
        super().__init__("colorbalance")

    def shadows(self, r: float, g: float, b: float) -> "ColorGradeEffect":
        self.params["rs"] = r
        self.params["gs"] = g
        self.params["bs"] = b
        return self

    def midtones(self, r: float, g: float, b: float) -> "ColorGradeEffect":
        self.params["rm"] = r
        self.params["gm"] = g
        self.params["bm"] = b
        return self

    def highlights(self, r: float, g: float, b: float) -> "ColorGradeEffect":
        self.params["rh"] = r
        self.params["gh"] = g
        self.params["bh"] = b
        return self

    def to_filter(self) -> str:
        parts = [self.name]
        for k, v in self.params.items():
            parts.append(f"{k}={v}")
        return "=".join(parts)


class BlurEffect(Effect):
    def __init__(self) -> None:
        super().__init__("boxblur")

    def radius(self, r: int) -> "BlurEffect":
        self.params["radius"] = r
        return self

    def to_filter(self) -> str:
        radius = self.params.get("radius", 1)
        return f"boxblur=radius={radius}"


class SharpenEffect(Effect):
    def __init__(self) -> None:
        super().__init__("unsharp")

    def amount(self, a: float) -> "SharpenEffect":
        self.params["amount"] = a
        return self

    def to_filter(self) -> str:
        amount = self.params.get("amount", 1.0)
        return f"unsharp=amount={amount}"


class VignetteEffect(Effect):
    def __init__(self) -> None:
        super().__init__("vignette")

    def angle(self, a: float) -> "VignetteEffect":
        self.params["angle"] = a
        return self

    def to_filter(self) -> str:
        angle = self.params.get("angle", "PI/5")
        return f"vignette=angle={angle}"


class NoiseEffect(Effect):
    def __init__(self) -> None:
        all = super().__init__("noise")

    def amount(self, a: int) -> "NoiseEffect":
        self.params["all"] = a
        return self

    def to_filter(self) -> str:
        all = self.params.get("all", 0)
        return f"noise=all={all}"


class PipelineBuilder:
    """Builder for video composition pipelines."""

    def __init__(self) -> None:
        self.steps: list[PipelineStep] = []

    def add_input(self, path: str, label: str = "v") -> "PipelineBuilder":
        self.steps.append(PipelineStep(PipelineStepType.INPUT, path, label))
        return self

    def add_filter(self, filter: str) -> "PipelineBuilder":
        self.steps.append(PipelineStep(PipelineStepType.FILTER, filter))
        return self

    def add_output(self, path: str) -> "PipelineBuilder":
        self.steps.append(PipelineStep(PipelineStepType.OUTPUT, path))
        return self

    def build(self) -> str:
        cmd = ["ffmpeg", "-y"]
        for step in self.steps:
            if step.step_type == PipelineStepType.INPUT:
                cmd.extend(["-i", step.value])
            elif step.step_type == PipelineStepType.FILTER:
                cmd.extend(["-vf", step.value])
            elif step.step_type == PipelineStepType.OUTPUT:
                cmd.append(step.value)
        return " ".join(cmd)


class PipelineStep:
    def __init__(self, step_type: "PipelineStepType", value: str = "", label: str = "") -> None:
        self.step_type = step_type
        self.value = value
        self.label = label


class PipelineStepType:
    INPUT = "input"
    FILTER = "filter"
    OUTPUT = "output"

    def run_full_composition(
        self,
        project_config: dict,
    ) -> dict[str, Any]:
        """Run full video composition pipeline."""
        job_id = str(uuid.uuid4())

        video = project_config.get("video")
        audio = project_config.get("audio")
        music = project_config.get("music")
        subtitles = project_config.get("subtitles")
        lut = project_config.get("lut", "cinematic")

        output_path = project_config.get("output", f"/tmp/{job_id}.mp4")

        result = compose_multimedia(video, audio, music, output_path)

        if subtitles and result.get("ok"):
            from app.media.caption_service import embed_subtitles
            result = embed_subtitles(output_path, subtitles, output_path)

        if lut and result.get("ok"):
            result = apply_lut(output_path, output_path, lut)

        return {
            "ok": result.get("ok", False),
            "job_id": job_id,
            "output": result.get("output", ""),
            "stages": self.stages,
        }


pipeline = VideoCompositionPipeline()