"""Bridge package — grafts model-workers' RFIR subtree into the orchestrator.

Both services use the top-level package name `app`, so the orchestrator can
never reach model-workers' `app.rfir` through PYTHONPATH: Python resolves
`app` to whichever package loads first, not a merged namespace of both.
This package resolves that collision as a path dependency on model-workers:
it extends its own search path with model-workers' rfir directory, so
`app.rfir.*` submodules resolve to the canonical sources under
services/model-workers. That subtree only imports within `app.rfir.*`
(guarded by tests/test_rfir_bridge.py), so every internal import resolves
back through this bridge to a single set of module instances.

Heavy ML dependencies (torch, diffusers, transformers) are imported lazily
inside the RFIR ops; the orchestrator itself only needs numpy + pillow to
compile graphs and drive the executor. Ops that require missing ML runtimes
or model weights raise at execution time, which the worker surfaces as a
failed job rather than an import-time crash.

Production GPU execution still runs in model-workers via the Redis queue
(see worker_loop.py); this bridge powers the in-process fallback and the
desktop preview when no Redis/model-worker deployment is available.

Spec reference: rfir-inference-engine-implementation.md §1.11
"""
from __future__ import annotations

import os
from pathlib import Path

_env_dir = os.environ.get("RENDERFLOW_RFIR_PACKAGE_DIR")
_default_dir = Path(__file__).resolve().parents[3] / "model-workers" / "app" / "rfir"
_rfir_dir = Path(_env_dir) if _env_dir else _default_dir

if _rfir_dir.is_dir():
    __path__.append(str(_rfir_dir))
# If the directory is missing (orchestrator deployed without the monorepo
# checkout), `app.rfir.<submodule>` imports raise ModuleNotFoundError, which
# callers already degrade on: rfir_preview returns a 503 and the worker
# fails the job with a clear error message.
