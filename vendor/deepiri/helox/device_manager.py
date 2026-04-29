"""
Vendored from: deepiri-platform/diri-helox/core/device_manager.py
Adapted for: Renderflow model worker device selection.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass
class DeviceInfo:
    device: str
    is_gpu: bool
    name: str | None = None


def get_optimal_device(force_device: str | None = None) -> DeviceInfo:
    if force_device == "cpu":
        return DeviceInfo(device="cpu", is_gpu=False)
    if torch.cuda.is_available():
        return DeviceInfo(
            device="cuda",
            is_gpu=True,
            name=torch.cuda.get_device_name(0),
        )
    if torch.backends.mps.is_available():
        return DeviceInfo(device="mps", is_gpu=True, name="Apple MPS")
    return DeviceInfo(device="cpu", is_gpu=False)
