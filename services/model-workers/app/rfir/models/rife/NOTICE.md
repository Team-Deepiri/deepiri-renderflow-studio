# RIFE 4.6 — provenance & vendoring

RenderFlow uses **RIFE 4.6** (Real-Time Intermediate Flow Estimation) for
frame interpolation in Tier B/C. RIFE is not published as a pip/HuggingFace
library, so its inference code is **vendored** into `_vendor/` rather than
imported as a dependency (avoids runtime code-drift from an upstream repo — see
the loader/registry pattern used for the other models).

## What lives where

| Path | Owner | Notes |
|------|-------|-------|
| `rife_model.py`, `__init__.py` | RenderFlow | Integration glue only (tensor/pad/timestep/PIL). |
| `_vendor/IFNet_HDv3.py`, `_vendor/warplayer.py` | **upstream (MIT)** | The RIFE 4.6 network + backward warp, inference-only. |
| weights `flownet.pkl` | upstream | Under `services/model-workers/models/rife-4.6/`, shipped via Git LFS. |

## Local modifications to vendored files

Kept as close to upstream as possible; deviations, all in `_vendor/`:

- **`IFNet_HDv3.py`** — import changed from `from model.warplayer import warp` to the
  relative `from .warplayer import warp` (flat vendored package).
- **`warplayer.py`** — `warp()` now builds its sampling grid on the **input tensor's
  device** (`tenFlow.device`) instead of a fixed module-level CUDA/CPU `device`
  (fixes a CPU↔MPS device mismatch; lets RIFE run on Apple Silicon GPU), and the
  grid cache is guarded by a `threading.Lock` (thread-safe first population).

## How to vendor (one-time, per checkout / CI cache)

```bash
cd services/model-workers
python scripts/vendor_rife.py            # fetches arch + LICENSE into _vendor/, weights into models dir
```

The script pins an exact upstream commit and a weights revision so the result
is reproducible. Edit the pinned refs at the top of `scripts/vendor_rife.py`.

## Licensing

- Upstream **code**: MIT (attribution preserved in `_vendor/LICENSE`).
- Upstream **weights**: shipped under RIFE's model terms — fine for this
  open-source project; re-check if the licensing context changes.

## Fail-safe behavior

If `_vendor/` isn't populated or the checkpoint is missing/mismatched,
`RIFEModel.load()` raises, `load_model("rife-4.6")` propagates it, and
`ops/rife_interpolate.run()` catches it and uses the **linear-blend fallback** —
so Tier B still produces output, exactly as before this feature. Check the logs
for `RIFE 4.6 loaded on <device>` to confirm real interpolation is active vs.
`rife model ... unavailable ... using blend fallback`.
