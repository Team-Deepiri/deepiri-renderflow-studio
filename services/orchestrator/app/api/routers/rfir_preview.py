"""RFIR desktop preview — compile (and where wired, run) a single Tier A shot.

Backs the Tauri "preview" command (§5.5): lets the desktop app show a fast
local Tier A result for a prompt without going through the full staged job
review flow.

Known gap: `cfsv_pipeline.py` imports `app.rfir.*`, which lives in
`services/model-workers`, not `services/orchestrator`. Both services use
the top-level package name `app`, so adding model-workers to PYTHONPATH
does NOT fix this — Python resolves `app` to whichever package loads
first in the process, not a merged namespace of both. This is a real
package-naming collision, not just a missing path entry; resolving it
needs either a rename of one `app` package or routing all RFIR execution
through the Redis queue (never importing `app.rfir` in-process from the
orchestrator). This endpoint surfaces the failure as a clear 503 rather
than a raw ImportError/500, so the desktop UI can show "AI preview
unavailable" instead of crashing.

Spec reference: rfir-inference-engine-implementation.md §5.5
"""
from __future__ import annotations

import tempfile
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["rfir"])


class PreviewRequest(BaseModel):
    prompt: str
    duration_sec: float = 5.0


@router.post("/v1/rfir/preview")
def preview_tier_a(req: PreviewRequest) -> dict[str, Any]:
    """Compile a single Tier-A shot graph for fast local preview.

    Returns graph metadata. Does not yet execute the graph in-process —
    actual pixel generation still requires the model-workers executor
    (via the Redis job queue), which is a separate process/runtime.
    """
    try:
        from app.media.cfsv_pipeline import compile_tier_a
    except ModuleNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail=(
                "RFIR module not available in the orchestrator environment "
                f"({e}). The orchestrator and model-workers are separate "
                "Poetry projects; app.rfir needs a path dependency or "
                "PYTHONPATH entry to be reachable here."
            ),
        )

    with tempfile.TemporaryDirectory(prefix="rfir-preview-") as tmpdir:
        result = compile_tier_a(req.prompt, tmpdir, duration_sec=req.duration_sec)

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "compile failed"))

    return result
