"""Op: ffmpeg_mux — concatenate every shot's frames into one MP4.

Per shot, in manifest order, builds one ffmpeg input plus its filter chain:
  - a frame directory (frames/<tensor>/%05d.png)   -> encode the sequence
  - a single still image (Tier A, or a degraded tier) -> camera-driven
    zoompan/crop over the shot's effective duration
  - neither                                         -> a black segment,
    logged at error level, so a missing shot shortens nothing

Exactly one ffmpeg invocation: every input is concatenated in a single
`-filter_complex ... concat=` pass. No per-shot segment files, no re-encode.

Spec reference: docs/specs/rfir-mp4-output-pipeline.md §6 Step 4
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.rfir.ir.types import CameraMotion

logger = logging.getLogger(__name__)


_ZOOMPAN_MOTIONS = {CameraMotion.ZOOM.value, CameraMotion.DOLLY.value, CameraMotion.ORBIT.value}


def _uses_zoompan(motion: str) -> bool:
    return motion in _ZOOMPAN_MOTIONS


def _normalize(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"


def _still_filter(motion: str, speed: float, width: int, height: int, duration: float, fps: int) -> str:
    """Camera-driven ffmpeg filter chain for a single still image (task 1.17,
    the Tier A fallback made universal — Decision 2)."""
    base = _normalize(width, height)
    d_frames = max(1, int(round(duration * fps)))
    speed = max(0.1, float(speed))

    # zoompan's `d=` is output frames *per input frame*, not a duration. The
    # looped still is fed as a single repeating input frame (no input-side
    # `-t` — see the caller), so without `d`'s own frame count, the input
    # would never signal EOF and concat would hang forever. `trim=end_frame`
    # is what actually stops the stream at the exact intended length.
    if motion == CameraMotion.ZOOM.value:
        return (f"{base},zoompan=z='min(zoom+{0.0015 * speed:.5f},1.2)':d={d_frames}:"
                f"s={width}x{height}:fps={fps},trim=end_frame={d_frames}")
    if motion == CameraMotion.DOLLY.value:
        return (f"{base},zoompan=z='min(zoom+{0.0030 * speed:.5f},1.35)':d={d_frames}:"
                f"s={width}x{height}:fps={fps},trim=end_frame={d_frames}")
    if motion == CameraMotion.ORBIT.value:
        return (
            f"{base},zoompan=z='min(zoom+{0.0010 * speed:.5f},1.15)':"
            f"x='iw/2-(iw/zoom/2)+20*sin(on/30)':y='ih/2-(ih/zoom/2)+10*cos(on/30)':"
            f"d={d_frames}:s={width}x{height}:fps={fps},trim=end_frame={d_frames}"
        )
    if motion == CameraMotion.PAN.value:
        dur = max(duration, 0.01)
        return (
            f"scale={int(width * 1.15)}:{int(height * 1.15)}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='(iw-{width})*t/{dur}':y=(ih-{height})/2,setsar=1,fps={fps}"
        )
    if motion == CameraMotion.TRACKING.value:
        dur = max(duration, 0.01)
        return (
            f"scale={int(width * 1.15)}:{int(height * 1.15)}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='(iw-{width})*(0.5+0.5*sin(t/{dur}))':y=(ih-{height})/2,setsar=1,fps={fps}"
        )
    # STATIC / unknown
    return f"{base},fps={fps}"


def run(
    shots: list[dict],
    frame_dirs: dict[str, str],
    stills: dict[str, str],
    out_path: Path,
    *,
    fps: int = 24,
    width: int = 1920,
    height: int = 1080,
) -> str | None:
    """Concatenate all shots (in manifest order) into out_path/output.mp4.

    Never raises: logs and returns None on failure so the caller can report
    a clean {"ok": False, ...} rather than crash.
    """
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg_mux: ffmpeg not found in PATH")
        return None
    if not shots:
        logger.error("ffmpeg_mux: no shots in manifest")
        return None

    cmd: list[str] = ["ffmpeg", "-y"]
    filters: list[str] = []
    n = len(shots)

    for i, shot in enumerate(shots):
        tensor = shot.get("output_tensor", "")
        eff_duration = float(shot.get("effective_duration_sec", shot.get("duration_sec", 1.0)))
        shot_fps = int(round(float(shot.get("fps", fps))))
        frame_dir = frame_dirs.get(tensor)
        still = stills.get(tensor)

        if frame_dir:
            cmd += ["-framerate", str(shot_fps), "-i", f"{frame_dir}/%05d.png"]
            filters.append(f"[{i}:v]{_normalize(width, height)},fps={shot_fps}[v{i}]")
        elif still:
            motion = str(shot.get("camera", "static"))
            if _uses_zoompan(motion):
                # zoompan's own `d=` parameter is a per-input-frame output
                # count, not a duration: combined with an input-side `-t`,
                # the looped still is read as many native-rate frames and
                # zoompan multiplies `d` output frames for *each* of them
                # (5s at the input's native ~25fps * d=120 -> 15000 frames,
                # a 10x+ blowup). Omitting `-t` here lets `-loop 1` present
                # one repeating frame so `d` alone sets the exact length.
                cmd += ["-loop", "1", "-i", still]
            else:
                cmd += ["-loop", "1", "-t", str(eff_duration), "-i", still]
            chain = _still_filter(
                motion, float(shot.get("camera_speed", 1.0)),
                width, height, eff_duration, shot_fps,
            )
            filters.append(f"[{i}:v]{chain}[v{i}]")
        else:
            logger.error(
                "ffmpeg_mux: shot %s has neither a frame dir nor a still (expected tensor %r) — "
                "emitting a black segment instead of dropping it",
                shot.get("index"), tensor,
            )
            cmd += ["-f", "lavfi", "-t", str(eff_duration), "-i", f"color=black:s={width}x{height}:r={shot_fps}"]
            filters.append(f"[{i}:v]setsar=1[v{i}]")

    concat_inputs = "".join(f"[v{i}]" for i in range(n))
    filters.append(f"{concat_inputs}concat=n={n}:v=1:a=0[outv]")
    filter_complex = ";".join(filters)

    output_mp4 = Path(out_path) / "output.mp4"
    cmd += [
        "-filter_complex", filter_complex, "-map", "[outv]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output_mp4),
    ]

    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=300)
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg_mux failed: %s", e.stderr.decode(errors="replace")[:500] if e.stderr else str(e))
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.error("ffmpeg_mux failed: %s", e)
        return None

    return str(output_mp4)
