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


def is_persisted_output(path: str | None) -> bool:
    """True if `path` names a real file on disk — the single definition of a
    valid, persisted job artifact. Used both when a job's output is recorded
    (worker_loop) and when it's consumed (accept), so the two never disagree.
    """
    return bool(path) and Path(path).is_file()

def resolve_within_data_dir(path: str, settings: Settings | None = None) -> Path:
    """Resolve `path` and makes sure it's inside the data dir. If not,
    raise ValueError.
    """
    p = Path(path).resolve()
    data_root = resolve_data_dir(settings).resolve()
    if not p.is_relative_to(data_root):
        raise ValueError(f"path outside data directory: {path!r}")
    return p
