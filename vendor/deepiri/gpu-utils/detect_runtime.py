"""
Vendored from: deepiri-gpu-utils/src/deepiri_gpu_utils/detect.py
Adapted for: deepiri-renderflow-studio runtime capability checks.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Literal

Backend = Literal["cuda", "rocm", "mps", "cpu", "unknown"]


@dataclass(frozen=True)
class DetectResult:
    backend: Backend
    confidence: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def detect_backend() -> DetectResult:
    if shutil.which("nvidia-smi"):
        try:
            proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                gpu_name = (proc.stdout or "").strip().splitlines()[0]
                return DetectResult(
                    backend="cuda",
                    confidence=0.9,
                    details={"gpu": gpu_name, "platform": platform.system()},
                )
        except (OSError, subprocess.TimeoutExpired, IndexError):
            pass
    if platform.system() == "Darwin":
        return DetectResult(backend="mps", confidence=0.8)
    return DetectResult(backend="cpu", confidence=0.8)
