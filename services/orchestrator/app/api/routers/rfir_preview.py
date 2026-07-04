"""RFIR desktop preview — compile (and where wired, run) a single Tier A shot.

Backs the Tauri "preview" command (§5.5): lets the desktop app show a fast
local Tier A result for a prompt without going through the full staged job
review flow.

The historical `app` package collision between the orchestrator and
model-workers is resolved by the bridge package (app/rfir/__init__.py),
which grafts model-workers' RFIR sources onto the orchestrator's own
`app.rfir` search path. If the bridge can't find those sources (e.g. the
orchestrator is deployed without the monorepo checkout), this endpoint
degrades to a clear 503 rather than a raw ImportError/500, so the desktop
UI can show "AI preview unavailable" instead of crashing.

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
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=(
                "RFIR module not available in the orchestrator environment "
                f"({e}). The app.rfir bridge could not locate model-workers' "
                "RFIR sources — deploy the monorepo checkout or set "
                "RENDERFLOW_RFIR_PACKAGE_DIR."
            ),
        )

    with tempfile.TemporaryDirectory(prefix="rfir-preview-") as tmpdir:
        result = compile_tier_a(req.prompt, tmpdir, duration_sec=req.duration_sec)

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "compile failed"))

    return result
