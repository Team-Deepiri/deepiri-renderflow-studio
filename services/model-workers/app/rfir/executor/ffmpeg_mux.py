"""Assemble ``output.mp4`` from ``ExecutionContext.shot_clips`` (mux step 3).

Encodes each shot in timeline index order, then concatenates. Stills are held
for ``duration_sec``; frame lists are stretched over that duration. All clips
are scaled to a shared even size so mixed A/B/C shots can concat.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from app.rfir.executor.shot_clips import ShotClip, _validate_paths

logger = logging.getLogger(__name__)

_MIN_DURATION_SEC = 0.1
_MUX_TIMEOUT_BASE_SEC = 60


class MuxError(RuntimeError):
    """Raised when ffmpeg_mux cannot produce a valid output.mp4."""


def even_dim(value: int) -> int:
    n = max(2, int(value))
    return n if n % 2 == 0 else n + 1


def probe_size(path: str) -> tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def shared_output_size(clips: list[ShotClip]) -> tuple[int, int]:
    """Even (width, height) large enough for every clip's first frame."""
    max_w, max_h = 2, 2
    for clip in clips:
        w, h = probe_size(clip.paths[0])
        max_w = max(max_w, w)
        max_h = max(max_h, h)
    return even_dim(max_w), even_dim(max_h)


def _scale_vf(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
    )


def _run_ffmpeg(cmd: list[str], timeout: int) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True, timeout=timeout)
    except FileNotFoundError as e:
        raise MuxError("ffmpeg not found in PATH") from e
    except subprocess.TimeoutExpired as e:
        raise MuxError(f"ffmpeg timed out after {timeout}s") from e
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode(errors="replace")[:500]
        raise MuxError(f"ffmpeg failed: {err or e}") from e
    if proc.returncode != 0:
        raise MuxError("ffmpeg returned non-zero")


def _stage_frames(clip: ShotClip, staging: Path) -> Path:
    staging.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(clip.paths):
        dest = staging / f"frame_{i:06d}.png"
        shutil.copyfile(src, dest)
    return staging / "frame_%06d.png"


def encode_shot_clip(
    ffmpeg: str,
    clip: ShotClip,
    dest: Path,
    size: tuple[int, int],
    staging: Path,
    timeout: int,
) -> None:
    duration = max(_MIN_DURATION_SEC, float(clip.duration_sec) or _MIN_DURATION_SEC)
    width, height = size
    vf = _scale_vf(width, height)
    fps = max(1, int(clip.fps) or 24)

    if clip.kind == "still" or len(clip.paths) == 1:
        cmd = [
            ffmpeg, "-y",
            "-loop", "1", "-i", clip.paths[0],
            "-vf", vf,
            "-t", f"{duration:.4f}",
            "-r", str(fps),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
            str(dest),
        ]
        _run_ffmpeg(cmd, timeout)
        return

    pattern = _stage_frames(clip, staging)
    input_fps = max(len(clip.paths) / duration, 1 / duration)
    cmd = [
        ffmpeg, "-y",
        "-framerate", f"{input_fps:.6f}",
        "-i", str(pattern),
        "-vf", vf,
        "-t", f"{duration:.4f}",
        "-r", str(fps),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        str(dest),
    ]
    _run_ffmpeg(cmd, timeout)


def _write_concat_list(paths: list[Path], list_path: Path) -> None:
    lines: list[str] = []
    for src in paths:
        escaped = str(src).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_clips(ffmpeg: str, clips: list[Path], dest: Path, list_path: Path, timeout: int) -> None:
    if len(clips) == 1:
        shutil.copyfile(clips[0], dest)
        return
    _write_concat_list(clips, list_path)
    cmd = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(dest),
    ]
    try:
        _run_ffmpeg(cmd, timeout)
    except MuxError:
        logger.warning("ffmpeg_mux: concat copy failed, re-encoding")
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
            str(dest),
        ]
        _run_ffmpeg(cmd, timeout)


def ordered_clips(shot_clips: dict[int, ShotClip]) -> list[ShotClip]:
    if not shot_clips:
        raise MuxError("ffmpeg_mux: shot_clips is empty")
    return [shot_clips[i] for i in sorted(shot_clips)]


def assemble_output_mp4(shot_clips: dict[int, ShotClip], out_path: Path) -> Path:
    """Encode every shot in index order and write ``out_path / output.mp4``."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MuxError("ffmpeg not found in PATH")

    clips = ordered_clips(shot_clips)
    for clip in clips:
        verified = _validate_paths(clip.paths)
        if verified is None:
            raise MuxError(
                f"ffmpeg_mux: shot {clip.shot_index} has missing or empty paths "
                f"(source={clip.source_node})"
            )
        clip.paths = verified

    size = shared_output_size(clips)
    timeout = _MUX_TIMEOUT_BASE_SEC + 60 * len(clips)
    work = out_path / "_mux"
    work.mkdir(parents=True, exist_ok=True)

    encoded: list[Path] = []
    try:
        for clip in clips:
            dest = work / f"shot_{clip.shot_index:04d}.mp4"
            staging = work / f"frames_{clip.shot_index:04d}"
            logger.info(
                "ffmpeg_mux: encoding shot %d (%s, %d file(s), %.2fs) → %s",
                clip.shot_index, clip.kind, len(clip.paths), clip.duration_sec, dest,
            )
            encode_shot_clip(ffmpeg, clip, dest, size, staging, timeout)
            if not dest.is_file() or dest.stat().st_size <= 0:
                raise MuxError(f"ffmpeg_mux: empty encode for shot {clip.shot_index}")
            encoded.append(dest)

        output_mp4 = out_path / "output.mp4"
        concat_list = work / "concat_list.txt"
        concat_clips(ffmpeg, encoded, output_mp4, concat_list, timeout)
        if not output_mp4.is_file() or output_mp4.stat().st_size <= 0:
            raise MuxError("ffmpeg_mux: output.mp4 missing or empty")
        return output_mp4
    finally:
        shutil.rmtree(work, ignore_errors=True)
