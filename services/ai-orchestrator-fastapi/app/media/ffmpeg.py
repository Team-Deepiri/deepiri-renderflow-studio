"""FFmpeg/ffprobe integration for media inspection (optional binary on PATH)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def probe(path_or_uri: str) -> dict[str, Any]:
    """Return ffprobe JSON summary or error stub when ffprobe is missing."""
    exe = shutil.which("ffprobe")
    if not exe:
        return {
            "ok": False,
            "error": "ffprobe not found on PATH",
            "path": path_or_uri,
        }
    try:
        proc = subprocess.run(
            [
                exe,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path_or_uri,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": (proc.stderr or proc.stdout or "ffprobe failed").strip()[:2000],
                "path": path_or_uri,
            }
        data = json.loads(proc.stdout or "{}")
        return {"ok": True, "path": path_or_uri, "ffprobe": data}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.warning("ffprobe: %s", e)
        return {"ok": False, "error": str(e), "path": path_or_uri}
