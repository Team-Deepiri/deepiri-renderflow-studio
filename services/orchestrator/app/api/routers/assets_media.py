from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.schemas.studio import AssetCreate, AssetImportBody, FrameBody, ProbeBody
from app.media import ffmpeg as ffmpeg_util
from app.services import studio

from app.paths import data_subdir, resolve_within_data_dir

router = APIRouter()

_PROXY_DIR = data_subdir("proxies")


@router.post("/v1/projects/{project_id}/assets", tags=["assets"])
def create_asset(project_id: UUID, body: AssetCreate) -> dict[str, Any]:
    if not studio.get_project(project_id):
        raise HTTPException(404, "project not found")
    return studio.create_asset(
        project_id, body.kind, body.uri, body.sha256, body.duration_ms, body.meta
    )


@router.post("/v1/projects/{project_id}/assets/import", tags=["assets"])
def import_asset(project_id: UUID, body: AssetImportBody) -> dict[str, Any]:
    if not studio.get_project(project_id):
        raise HTTPException(404, "project not found")

    fmt = ffmpeg_util.detect_format(body.path)

    if fmt.get("video"):
        kind = "video"
    elif fmt.get("audio"):
        kind = "audio"
    else:
        kind = "image"

    duration_ms: int | None = 5000
    if fmt.get("ok") and fmt.get("duration_seconds"):
        duration_ms = int(float(fmt["duration_seconds"]) * 1000)

    meta: dict[str, Any] = {
        "proxy_status": "pending" if fmt.get("ok") and kind in ("video", "audio") else "unavailable",
        "proxy_path": None,
        "name": Path(body.path).name,
    }
    if fmt.get("ok"):
        meta["size_bytes"] = fmt.get("size_bytes", 0)
        if fmt.get("video"):
            meta["width"] = fmt["video"].get("width")
            meta["height"] = fmt["video"].get("height")
            meta["fps"] = fmt["video"].get("fps")
            meta["codec"] = fmt["video"].get("codec")
        if fmt.get("audio"):
            meta["audio_codec"] = fmt["audio"].get("codec")
            meta["sample_rate"] = fmt["audio"].get("sample_rate")
            meta["channels"] = fmt["audio"].get("channels")

    asset = studio.create_asset(project_id, kind, body.path, "pending", duration_ms, meta)
    asset_uuid: UUID = asset["id"]

    if meta["proxy_status"] == "pending":
        def _make_proxy(aid: UUID, input_path: str) -> None:
            _PROXY_DIR.mkdir(parents=True, exist_ok=True)
            out_path = str(_PROXY_DIR / f"{aid}_proxy.mp4")
            result = ffmpeg_util.transcode_proxy(input_path, out_path)
            if result.get("ok"):
                studio.update_asset_meta(aid, {"proxy_status": "ready", "proxy_path": out_path})
            else:
                studio.update_asset_meta(aid, {"proxy_status": "failed"})

        threading.Thread(target=_make_proxy, args=(asset_uuid, body.path), daemon=True).start()

    return studio.get_asset(asset_uuid)


@router.get("/v1/projects/{project_id}/assets", tags=["assets"])
def list_assets(project_id: UUID) -> list[dict[str, Any]]:
    return studio.list_assets(project_id)


@router.get("/v1/assets/{asset_id}", tags=["assets"])
def get_asset_by_id(asset_id: UUID) -> dict[str, Any]:
    asset = studio.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, "asset not found")
    return asset


@router.post("/v1/media/probe", tags=["media"])
def media_probe(body: ProbeBody) -> dict[str, Any]:
    try:
        p = resolve_within_data_dir(body.path)
    except ValueError:
        raise HTTPException(403, "path outside data directory")
    return ffmpeg_util.probe(str(p))


@router.post("/v1/media/frame", tags=["media"])
def media_frame(body: FrameBody) -> dict[str, Any]:
    try:
        p = resolve_within_data_dir(body.path)
    except ValueError:
        raise HTTPException(403, "path outside data directory")
    result = ffmpeg_util.extract_frame_base64(str(p), body.time_seconds)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "frame extraction failed"))
    return result


@router.api_route("/v1/media/stream", methods=["GET", "HEAD"], tags=["media"])
def media_stream(path: str) -> FileResponse:
    try:
        p = resolve_within_data_dir(path)
    except ValueError:
        raise HTTPException(403, "path outside data directory")
    if not p.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(str(p), media_type="video/mp4")
