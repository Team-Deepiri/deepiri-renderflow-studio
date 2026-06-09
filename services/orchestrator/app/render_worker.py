from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue
from uuid import UUID

from app.api.utils import get_event_emitter
from app.config import Settings
from app.paths import data_subdir
from app.services import studio

logger = logging.getLogger(__name__)

_local_render_pending: Queue[str] = Queue()
_render_worker_thread: threading.Thread | None = None

_PRESET_FILTERS = {
    "h264_1080p": "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
    "h264_4k": "scale=3840:2160:force_original_aspect_ratio=decrease,pad=3840:2160:(ow-iw)/2:(oh-ih)/2",
}


def _emit_render(job_id: str, status: str, project_id: str) -> None:
    try:
        get_event_emitter().emit(
            "render_update",
            {"job_id": job_id, "status": status, "project_id": project_id},
        )
    except Exception:
        pass


def enqueue_render_job(job_id: str) -> None:
    _local_render_pending.put(job_id)


def _resolve_clip_source(asset: dict) -> str | None:
    meta = asset.get("meta_jsonb") or {}
    proxy = meta.get("proxy_path")
    if meta.get("proxy_status") == "ready" and proxy and Path(proxy).exists():
        return str(proxy)
    uri = asset.get("uri")
    return str(uri) if uri and Path(uri).exists() else None


def _write_placeholder(output_path: str) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1920x1080:d=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            output_path,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        logger.warning("placeholder ffmpeg failed: %s", (proc.stderr or proc.stdout)[:500])
    return Path(output_path).exists()


def _ffmpeg_concat(sources: list[str], output_path: str, preset: str = "h264_1080p") -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False

    out_dir = Path(output_path).parent
    list_path = out_dir / "concat_list.txt"
    lines = []
    for src in sources:
        escaped = src.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    vf = _PRESET_FILTERS.get(preset, _PRESET_FILTERS["h264_1080p"])
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            output_path,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        logger.warning("concat ffmpeg failed: %s", (proc.stderr or proc.stdout)[:500])
    return Path(output_path).exists()


def _process_render_job(job_id: str, settings: Settings) -> None:
    try:
        jid = UUID(job_id)
    except ValueError:
        logger.error("invalid render job id %s", job_id)
        return

    job = studio.get_render_job(jid)
    if not job:
        logger.warning("render job not in store: %s", job_id)
        return

    studio.update_render_job(jid, status="rendering", progress=0.1)
    _emit_render(job_id, "rendering", str(job["project_id"]))

    sequence_id = job.get("sequence_id")
    if not sequence_id:
        studio.update_render_job(jid, status="failed", error="sequence_id required", ended=True)
        _emit_render(job_id, "failed", str(job["project_id"]))
        return

    tracks = studio.list_tracks(sequence_id)
    video_track_ids = {t["id"] for t in tracks if t.get("track_type") == "video"}
    clips = sorted(
        [c for c in studio.list_clips_for_sequence(sequence_id) if c["track_id"] in video_track_ids],
        key=lambda c: c["in_tick"],
    )

    out_dir = data_subdir("render_outputs", settings) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / "export.mp4")

    ok = False
    if not clips:
        ok = _write_placeholder(output_path)
    else:
        sources: list[str] = []
        for clip in clips:
            asset = studio.get_asset(clip["asset_id"])
            if not asset:
                continue
            src = _resolve_clip_source(asset)
            if src:
                sources.append(src)
        if not sources:
            studio.update_render_job(
                jid,
                status="failed",
                error="no readable clip sources",
                ended=True,
            )
            _emit_render(job_id, "failed", str(job["project_id"]))
            return
        studio.update_render_job(jid, progress=0.5)
        ok = _ffmpeg_concat(sources, output_path, preset=job.get("preset", "h264_1080p"))

    if ok and Path(output_path).exists():
        studio.update_render_job(
            jid,
            status="completed",
            output_uri=output_path,
            progress=1.0,
            ended=True,
        )
        _emit_render(job_id, "completed", str(job["project_id"]))
    else:
        err = "ffmpeg not found" if not shutil.which("ffmpeg") else "ffmpeg did not produce export.mp4"
        studio.update_render_job(jid, status="failed", error=err, ended=True)
        _emit_render(job_id, "failed", str(job["project_id"]))


def _loop(settings: Settings) -> None:
    while True:
        try:
            jid = _local_render_pending.get(timeout=0.5)
        except Empty:
            continue
        try:
            _process_render_job(jid, settings)
        except Exception:
            logger.exception("render job %s failed", jid)


def start_render_worker(settings: Settings) -> None:
    global _render_worker_thread
    if _render_worker_thread and _render_worker_thread.is_alive():
        return

    def run() -> None:
        try:
            _loop(settings)
        except Exception:
            logger.exception("render worker crashed")

    _render_worker_thread = threading.Thread(
        target=run,
        name="renderflow-render-worker",
        daemon=True,
    )
    _render_worker_thread.start()
