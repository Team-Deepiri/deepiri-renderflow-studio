"""Guards for the app.rfir bridge package (app/rfir/__init__.py).

The bridge grafts model-workers' RFIR sources onto the orchestrator's own
`app.rfir` search path. That only stays sound while the RFIR subtree keeps
all its intra-`app` imports inside `app.rfir.*` — an import of any other
`app.<module>` would resolve against the orchestrator's `app` package
in-process and model-workers' `app` package out-of-process, silently
diverging. These tests fail loudly if either side of that contract breaks.
"""
from __future__ import annotations

import re
from pathlib import Path

import app.rfir as bridge

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[1]
RFIR_DIR = ORCHESTRATOR_ROOT.parents[0] / "model-workers" / "app" / "rfir"


def test_bridge_resolves_to_model_workers_sources():
    assert str(RFIR_DIR) in bridge.__path__, (
        f"bridge __path__ {bridge.__path__} does not include {RFIR_DIR}"
    )

    from app.rfir.ir import types as rfir_types

    assert Path(rfir_types.__file__).resolve() == (RFIR_DIR / "ir" / "types.py").resolve()


def test_rfir_subtree_only_imports_within_app_rfir():
    pattern = re.compile(r"^\s*(?:from|import)\s+(app\.[\w.]+)", re.MULTILINE)
    offenders: list[str] = []

    for py_file in RFIR_DIR.rglob("*.py"):
        for match in pattern.finditer(py_file.read_text(encoding="utf-8")):
            module = match.group(1)
            if not module.startswith("app.rfir"):
                offenders.append(f"{py_file.relative_to(RFIR_DIR)}: {module}")

    assert not offenders, (
        "RFIR modules must only import within app.rfir.* to stay compatible "
        f"with the orchestrator bridge; found: {offenders}"
    )


def test_executor_engine_imports_without_ml_runtimes():
    """The engine (and everything it pulls in) must not require torch at
    import time — the orchestrator only ships numpy + pillow."""
    import sys

    from app.rfir.executor import engine  # noqa: F401

    assert "torch" not in sys.modules, (
        "importing app.rfir.executor.engine pulled in torch at module level; "
        "keep torch imports lazy inside the RFIR ops"
    )
