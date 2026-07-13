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
| `_vendor/` | **upstream (MIT)** | IFNet + warp + Model wrapper, fetched by the script below. Empty in VCS until vendored. |
| weights `flownet.pkl` | upstream | Placed under `$RENDERFLOW_MODELS_DIR/rife-4.6/`, downloaded/cached — never committed. |

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
