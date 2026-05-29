"""Deepiri Renderflow AI orchestrator application package."""

from __future__ import annotations

import sys
from pathlib import Path


def _add_repo_lib_to_path(lib_name: str) -> None:
    # Allow running from source without installing Poetry path deps first.
    repo_root = Path(__file__).resolve().parents[3]
    lib_root = repo_root / "lib" / lib_name
    if not lib_root.is_dir():
        return
    lib_root_str = str(lib_root)
    if lib_root_str not in sys.path:
        sys.path.insert(0, lib_root_str)


_add_repo_lib_to_path("renderflow_queue")
