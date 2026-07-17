"""Thin wrapper around the vendored RIFE 4.6 network.

This module is RenderFlow integration code only — image<->tensor conversion,
padding, arbitrary-timestep sampling, device/dtype handling, and PIL output.
The actual interpolation network (IFNet + warp) is the upstream MIT source
committed in `_vendor/`; we only *call* it here. See NOTICE.md.

Public surface used by the loader/op:
    RIFEModel.load(weights_path, device, dtype) -> RIFEModel
    RIFEModel.interpolate(img0: PIL, img1: PIL, factor: int) -> list[PIL]
        returns the `factor - 1` intermediate frames (endpoints added by caller)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

# RIFE's coarse-to-fine flow pyramid downsamples by 2 several times; inputs must
# be padded up to a multiple of this before inference, then cropped back.
_PAD_MULTIPLE = 32


def _load_vendored_net(weights_path: str, device: str) -> Any:
    """Instantiate the upstream RIFE network and load its checkpoint.

    Imports lazily from `_vendor` so this file imports fine before vendoring;
    raises a clear error (→ op blend fallback) when the arch isn't present.
    """
    import os

    import torch

    # The two vendored upstream files live flat in `_vendor/` (IFNet_HDv3.py +
    # warplayer.py) as a normal subpackage, so a plain package import works —
    # no sys.path juggling, no Model wrapper (which pulled in training-only
    # loss/torchvision).
    try:
        from app.rfir.models.rife._vendor.IFNet_HDv3 import IFNet  # type: ignore
    except Exception as e:  # noqa: BLE001 - any import failure means "not vendored"
        raise RuntimeError(
            "RIFE architecture is not vendored. Populate "
            "app/rfir/models/rife/_vendor/{IFNet_HDv3.py, warplayer.py} "
            f"(see NOTICE.md) ({e})"
        ) from e

    ckpt = os.path.join(weights_path, "flownet.pkl")
    if not os.path.isfile(ckpt):
        raise FileNotFoundError(f"RIFE checkpoint not found: {ckpt}")

    state = torch.load(ckpt, map_location="cpu")
    # RIFE checkpoints are saved from DataParallel (`module.` prefix) and carry
    # the removed contextnet weights; strip the prefix and load non-strict so
    # the unused keys are ignored rather than raising.
    state = {k.replace("module.", ""): v for k, v in state.items()}

    net = IFNet()
    net.load_state_dict(state, strict=False)
    net.to(device).eval()
    return net


class RIFEModel:
    def __init__(self, net: Any, device: str, dtype: str = "float32") -> None:
        self._net = net
        self.device = device
        self.dtype = dtype

    @classmethod
    def load(cls, weights_path: str, device: str, dtype: str = "float32") -> "RIFEModel":
        net = _load_vendored_net(weights_path, device)
        logger.info("RIFE 4.6 loaded on %s (dtype=%s)", device, dtype)
        return cls(net, device, dtype)

    # ── tensor plumbing (ours) ────────────────────────────────────────────────

    def _to_tensor(self, img: Image.Image):
        import numpy as np
        import torch

        arr = np.asarray(img.convert("RGB"), dtype="float32") / 255.0  # H,W,3
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)         # 1,3,H,W
        dtype = torch.float16 if (self.dtype == "float16" and self.device == "cuda") else torch.float32
        return t.to(device=self.device, dtype=dtype)

    @staticmethod
    def _pad(t):
        import torch.nn.functional as F

        _, _, h, w = t.shape
        ph = (_PAD_MULTIPLE - h % _PAD_MULTIPLE) % _PAD_MULTIPLE
        pw = (_PAD_MULTIPLE - w % _PAD_MULTIPLE) % _PAD_MULTIPLE
        # pad right/bottom only so the top-left crop back is trivial
        return F.pad(t, (0, pw, 0, ph), mode="replicate"), (h, w)

    def _to_pil(self, t, size) -> Image.Image:
        import numpy as np

        h, w = size
        t = t[:, :, :h, :w].clamp(0.0, 1.0)
        arr = (t[0].permute(1, 2, 0).float().cpu().numpy() * 255.0).round().astype("uint8")
        return Image.fromarray(arr, mode="RGB")

    def _infer_mid(self, t0, t1, timestep: float):
        """One intermediate frame at `timestep` in (0, 1).

        Calls the vendored IFNet: forward(cat(img0, img1), timestep, scale_list)
        returns (flow, mask, merged); the interpolated frame is the finest-scale
        entry, merged[-1]. scale_list is the standard 8/4/2/1 coarse-to-fine
        pyramid at scale 1.0.

        On CUDA the net is wrapped with torch.compile (bucketed by input shape,
        so it compiles once per resolution) for kernel fusion / lower launch
        overhead. `compiled_call` is a no-op on MPS/CPU — those run eager,
        unchanged — and falls back to eager if compilation fails.
        """
        import torch

        from app.rfir.models.compile_utils import compiled_call

        net = compiled_call(
            self._net, cache_key=("rife", tuple(t0.shape)), device=self.device
        )
        with torch.no_grad():
            _flow, _mask, merged = net(torch.cat((t0, t1), 1), timestep, [8, 4, 2, 1])
        return merged[-1]

    # ── public op interface (ours) ────────────────────────────────────────────

    def interpolate(self, img0: Image.Image, img1: Image.Image, factor: int) -> list[Image.Image]:
        if img1.size != img0.size:
            img1 = img1.resize(img0.size)
        t0, size = self._pad(self._to_tensor(img0))
        t1, _ = self._pad(self._to_tensor(img1))
        mids: list[Image.Image] = []
        for i in range(1, factor):
            mid = self._infer_mid(t0, t1, i / factor)
            mids.append(self._to_pil(mid, size))
        return mids
