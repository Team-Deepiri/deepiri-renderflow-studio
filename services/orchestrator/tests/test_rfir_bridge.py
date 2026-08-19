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



WORKER_GUARDRAILS_DIR = ORCHESTRATOR_ROOT.parents[0] / "model-workers" / "app" / "guardrails"

def test_guardrails_bridge_resolves_runtime_guard_to_model_workers():
    from app.guardrails import runtime_guard

    assert Path(runtime_guard.__file__).resolve() == (
        WORKER_GUARDRAILS_DIR / "runtime_guard.py"
    ).resolve()


def test_guardrails_bridge_does_not_shadow_orchestrator_modules():
    """The orchestrator's own directory stays first in __path__, so its
    modules win if a worker-side file ever takes one of their names."""
    import app.guardrails as pkg
    from app.guardrails import config

    assert Path(config.__file__).resolve().parent == (ORCHESTRATOR_ROOT / "app" / "guardrails")
    assert pkg.__path__[0] == str(ORCHESTRATOR_ROOT / "app" / "guardrails")


def test_runtime_guard_imports_without_ml_runtimes():
    """Layer 3 is imported mid-render on the in-process path, so its
    torch/transformers use has to stay lazy inside _nsfw_score.
    """
    import subprocess
    import sys

    probe = (
        "import sys; "
        "from app.guardrails import runtime_guard; "
        "sys.exit(1 if 'torch' in sys.modules else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe], cwd=ORCHESTRATOR_ROOT, capture_output=True, text=True,
    )

    assert proc.returncode == 0, (
        "importing app.guardrails.runtime_guard pulled in torch at module level "
        f"(rc={proc.returncode}) {proc.stderr[-300:]}"
    )
