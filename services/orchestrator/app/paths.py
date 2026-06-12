from __future__ import annotations

import os
from pathlib import Path

from app.config import Settings

# app/paths.py -> app/ -> services/orchestrator/
ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent


def resolve_data_dir(settings: Settings | None = None) -> Path:
    raw = None
    if settings and settings.data_dir:
        raw = settings.data_dir
    else:
        raw = os.environ.get("RENDERFLOW_DATA_DIR")
    if not raw:
        return ORCHESTRATOR_ROOT / "data"
    p = Path(raw)
    return p if p.is_absolute() else ORCHESTRATOR_ROOT / p


def data_subdir(name: str, settings: Settings | None = None) -> Path:
    """e.g. data_subdir('proxies'), data_subdir('ai_outputs', settings)."""
    return resolve_data_dir(settings) / name