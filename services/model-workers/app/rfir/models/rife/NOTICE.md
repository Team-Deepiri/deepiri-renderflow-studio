# RIFE 4.6 — provenance & vendoring

RenderFlow uses **RIFE 4.6** (Real-Time Intermediate Flow Estimation) for
frame interpolation in Tier B/C. RIFE isn't published as a pip/HuggingFace
library, so its inference code is **vendored** into `_vendor/` (committed to the
repo) rather than imported as a dependency — this avoids runtime code-drift from
an upstream repo, matching the loader/registry pattern used for the other models.

## What lives where

| Path | Owner | Notes |
|------|-------|-------|
| `rife_model.py`, `__init__.py` | RenderFlow | Integration glue only (tensor/pad/timestep/PIL). |
| `_vendor/IFNet_HDv3.py`, `_vendor/warplayer.py` | **upstream (MIT)** | The RIFE 4.6 network + backward warp, inference-only. **Committed.** |
| `models/rife-4.6/flownet.pkl` | upstream | The ~20 MB checkpoint, shipped via **Git LFS**. |

## How it ships

Both the code and the weights live in the repo, so a fresh clone runs with no manual setup:

- **Architecture** — `_vendor/IFNet_HDv3.py` + `_vendor/warplayer.py` are
  committed, copied verbatim from the official RIFE 4.6 PyTorch release (with the two integration-only tweaks noted below).
- **Weights** — `services/model-workers/models/rife-4.6/flownet.pkl` is tracked
  by **Git LFS** (`.gitattributes`), so `git clone` / `git pull` fetch it
  automatically. If a checkout shows a small text pointer instead of the real
  ~20 MB file (git-lfs not installed), run:

  ```bash
  git lfs install && git lfs pull
  ```

The loader (`_load_rife`) resolves weights from
`services/model-workers/models/rife-4.6/` by default, overridable via
`$RENDERFLOW_MODELS_DIR` — consistent with the other model loaders.

## Local modifications to vendored files

Kept as close to upstream as possible; the only deviations, both in `_vendor/`:

- **`IFNet_HDv3.py`** — import changed from `from model.warplayer import warp` to
  the relative `from .warplayer import warp` (flat vendored package layout).
- **`warplayer.py`** — `warp()` builds its sampling grid on the **input tensor's
  device** (`tenFlow.device`) instead of a fixed module-level CUDA/CPU `device`
  (fixes a CPU↔MPS mismatch; lets RIFE run on Apple Silicon GPU), and the grid
  cache is guarded by a `threading.Lock` (thread-safe first population).

## Licensing

- Upstream **code**: MIT (Practical-RIFE, hzwer). Attribution is recorded here;
  include the upstream MIT license text alongside `_vendor/` for full compliance.
- Upstream **weights**: shipped under RIFE's model terms — acceptable for this
  open-source project; re-check if the licensing context changes (e.g. commercial
  distribution).

## Fail-safe behavior

If the vendored arch is missing, or the LFS weights weren't pulled (pointer stub)
or the checkpoint is unreadable/mismatched, `RIFEModel.load()` raises,
`load_model("rife-4.6")` propagates it, and `ops/rife_interpolate.run()` catches
it and uses the **linear-blend fallback** — so Tier B/C still produces output.
Check the logs to tell which path ran: `RIFE 4.6 loaded on <device>` +
`rife_interpolate: real RIFE …` means the real model is active;
`rife model … unavailable … using blend fallback` means it fell back.
