# Deepiri Renderflow Studio

Native animation and post-production studio for video editing, compositing, motion graphics, and 3D workflows.
<img width="1853" height="911" alt="image" src="https://github.com/user-attachments/assets/08834bcb-3afa-42cf-b051-cc7a93e53c4e" />

---

## Principles

- Native-first desktop architecture (`Tauri` + Rust/C++ core).
- Vulkan-first rendering pipeline.
- Optional AI copilot with full manual/no-AI parity.
- Reuse Deepiri packages as **path/Poetry dependencies** where they exist (e.g. `deepiri-gpu-utils`); keep small Renderflow-only helpers as first-party crates under `packages/`.

---

## Monorepo Layout

- `apps/desktop-tauri`: desktop shell and editor UI host.
- `core/timeline-engine-rs`: deterministic timeline and playback math.
- `core/render-engine-vulkan`: render graph and GPU orchestration.
- `core/audio-engine-juce`: JUCE integration boundary for audio graph.
- `services/orchestrator`: job orchestration and API.
- `services/model-workers`: model worker entrypoints.
- `proto/grpc`: gRPC contracts for desktop<->services IPC.
- `infra/postgres/migrations`: SQL schema.
- `lib/renderflow_queue`: in-repo Redis AI job queue (shared orchestrator + workers).
- `vendor/deepiri`: optional legacy snippets only; GPU + queue live in real packages above.

---

## Getting Started (bootstrap)

Layout: clone **`deepiri-gpu-utils`** next to **`deepiri-renderflow-studio`** (sibling under the same parent) so Poetry path dependencies resolve.

1. Build timeline crate:
   - `cargo test --manifest-path core/timeline-engine-rs/Cargo.toml`
2. Run AI orchestrator (HTTP + gRPC + in-process AI worker):
   - `cd services/orchestrator && poetry install`
   - `./scripts/run_orchestrator.sh` (uses `.venv` or `poetry run`)
   - Or: `cd services/orchestrator && poetry run uvicorn app.main:app --host 127.0.0.1 --port 8080`
   - HTTP: `http://127.0.0.1:8080/health`, jobs: `POST /v1/jobs`, `GET /v1/jobs/{id}`, `GET /v1/jobs`, `POST /v1/jobs/{id}/cancel|retry|accept|reject`, `GET /v1/jobs/worker/stats`
   - gRPC: `AiSessionService` on `RENDERFLOW_GRPC_HOST`:`RENDERFLOW_GRPC_PORT` (default `0.0.0.0:50051`)
3. Optional: Redis-backed job queue — set `REDIS_URL=redis://127.0.0.1:6380/0` (see `infra/docker/docker-compose.yml`).
4. Optional: PostgreSQL — set `DATABASE_URL=postgresql://renderflow:renderflow@127.0.0.1:5433/renderflow` after `docker compose -f infra/docker/docker-compose.yml up -d`.
5. Integration smoke: `services/orchestrator/.venv/bin/python scripts/smoke_integration.py` (after `poetry install` in the orchestrator)
6. Native engines (no Tauri/GTK): `./scripts/verify_native_engines.sh` — exercises `timeline-engine-rs` and `render-engine-vulkan` (graph schedule + Vulkan `discover()` when an ICD is present).
7. Regenerate gRPC Python stubs after proto edits: `./scripts/gen_proto.sh`
8. Desktop (Tauri + Vite UI): `cd apps/desktop-tauri/ui && npm install && npm run build`, then `cd apps/desktop-tauri/src-tauri && cargo build` — on Linux install WebKitGTK dev packages (e.g. Debian/Ubuntu: `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`, `pkg-config`, `libssl-dev`). The desktop binary links **`timeline-engine-rs`** and **`render-engine-vulkan`** and exposes Tauri commands: `timeline_resolve_active`, `render_graph_schedule`, `vulkan_discover`, `orchestrator_list_projects`, plus existing orchestrator/AI helpers.
9. Model worker CLI: `python3 services/model-workers/app/worker.py` — Redis consumer: `cd services/model-workers && poetry install && poetry run python -m app.redis_worker`
10. Full stack Docker: run `docker compose` from `infra/docker` (orchestrator build context is the **parent** of this repo so `deepiri-gpu-utils` is included): `docker compose -f infra/docker/docker-compose.yml build orchestrator && docker compose -f infra/docker/docker-compose.yml up -d`

---

### Desktop → orchestrator

Set `RENDERFLOW_ORCHESTRATOR_URL` (default `http://127.0.0.1:8080`). Tauri commands: `orchestrator_health`, `submit_ai_job`, `get_ai_job`, `rfir_preview_tier_a`.

---

## RFIR (AI video generation)

RenderFlow's optional AI copilot generates short clips via the **RenderFlow Inference Runtime (RFIR)** — a compiled, tier-routed engine that mixes cheap keyframe+motion synthesis (Tier A/B) with sparse diffusion (Tier C/D), rather than diffusing every frame. See [docs/specs/rfir-inference-engine-design.md](docs/specs/rfir-inference-engine-design.md) for the full design.

RFIR is **fully open-source** — no paid generation API is called. Model weights are downloaded once from HuggingFace and run locally (CUDA or Apple Silicon MPS).

### Architecture: orchestrator dispatches, model-workers executes

`services/orchestrator` and `services/model-workers` are **separate Poetry projects that both use the top-level package name `app`** — the orchestrator cannot `import app.rfir` in-process (Python resolves `app` to whichever package loaded first, not a merged namespace). Because of this, **all RFIR planning, compiling, and execution happens inside `services/model-workers`' `redis_worker.py` process**, never in the orchestrator:

```
1. POST /v1/jobs          (orchestrator: guardrails, job_store.create, status=queued)
2. enqueue_job()           orchestrator pushes {prompt, budget, guardrail_verdict, project}
                            onto Redis (REDIS_KEY_JOBS) — no RFIR import needed here
3. redis_worker.py          model-workers blpop's the job, refuses if guardrail_verdict
   (model-workers)          != "allow", then runs planner -> builder -> fusion ->
                            memory_plan -> executor.run_graph() entirely in its own process
4. JobStatusReporter        model-workers writes {state, stage, artifacts, metrics} to a
                            Redis key per job (renderflow:ai_jobs:status:{job_id})
5. _rfir_status_loop()      orchestrator polls that key and mirrors it into job_store,
   (orchestrator)           emitting the same SSE events as the legacy stub pipeline
6. GET /v1/jobs/{id}        status=review, metadata.output_path points at the real MP4
   POST .../accept          creates the video asset as usual
```

When `RENDERFLOW_RFIR_ENABLED=true` **and** `REDIS_URL` is set, the orchestrator's own worker loop does **not** consume `REDIS_KEY_JOBS` itself — model-workers' `redis_worker.py` is the sole consumer, avoiding two processes racing to pop the same queue. If RFIR is enabled but no `REDIS_URL` is configured, there's no channel to model-workers and the orchestrator logs a warning and falls back to the legacy in-process stub pipeline (fake stage data, no real generation).

### Running both processes locally

```bash
docker compose -f infra/docker/docker-compose.yml up -d redis   # REDIS_URL=redis://127.0.0.1:6380/0

# Terminal 1 — orchestrator
cd services/orchestrator
REDIS_URL=redis://127.0.0.1:6380/0 RENDERFLOW_RFIR_ENABLED=true \
  poetry run uvicorn app.main:app --host 127.0.0.1 --port 8080

# Terminal 2 — model worker (the actual RFIR executor)
cd services/model-workers
REDIS_URL=redis://127.0.0.1:6380/0 poetry run python -m app.redis_worker
```

Then `POST /v1/jobs` as usual — job status will progress `queued` → `preparing` → `running` → `review`, with `metadata.output_path` pointing at a real MP4 once model-workers finishes.

### Enabling RFIR

| Variable | Default | Description |
|----------|---------|-------------|
| `RENDERFLOW_RFIR_ENABLED` | `false` | Turn on the CFSV/RFIR pipeline (off = legacy stub pipeline) |
| `RENDERFLOW_MODELS_DIR` | `./models` | Local directory for downloaded model weights |
| `RENDERFLOW_MODELS_MAX_BYTES` | unset | Cap on the weights directory. After each job, least-recently-used unpinned models are evicted until the tree fits. Unset means never evict |
| `RENDERFLOW_RFIR_MAX_GPU_SEC` | `120` | Per-job GPU time budget |
| `RENDERFLOW_RFIR_MAX_TIER` | `C` | Highest tier allowed (`A`, `B`, `C`, or `D`) |
| `RENDERFLOW_RFIR_T2I_MODEL` | `flux-schnell-fp16` | Keyframe model id from `models/registry.py` (e.g. `sdxl-turbo-fp16` for smaller/faster local dev) |
| `RENDERFLOW_RFIR_GEN_RES` | `512x288` | Internal generation resolution |
| `RENDERFLOW_RFIR_T2I_STEPS` | `4` | FLUX/SDXL keyframe steps |
| `RENDERFLOW_RFIR_T2V_STEPS` | `10` | Sparse T2V steps (Tier C/D) |
| `RENDERFLOW_RFIR_LTC_WINDOW` | `16` | Latent Temporal Cache window size |
| `RENDERFLOW_RFIR_LTC_OVERLAP` | `4` | LTC window overlap (frames) |
| `RENDERFLOW_RFIR_DISABLE_COMPILE` | unset | Set to `1` to disable `torch.compile` (debugging) |
| `RENDERFLOW_CHECKPOINT_DIR` | `/tmp/rfir-checkpoints` | Shot-boundary checkpoint storage (local path or `s3://...`) |
| `RENDERFLOW_RENDER_OUTPUT_DIR` | `../orchestrator/data/render_outputs` (model-workers side) | Where finished MP4s/artifacts are written — must be reachable by the orchestrator for local single-machine dev |

### Model weights

All models are open-source (Apache 2.0 / MIT / OpenRAIL++) — see `services/model-workers/app/rfir/models/registry.py` for the full manifest and licenses. Weights are **not** committed to git.

Disk is a **working set, not a prepaid catalog**. A compiled RFIR graph names every model role it will invoke before any GPU work starts, so the executor fetches exactly those roles and leaves the rest alone. A machine that only renders Tier A stills never stores the video model.

Approximate sizes (fp16):

| Model | Role | Size | When |
|---|---|---|---|
| FLUX.1-schnell **or** SDXL-Turbo | keyframes | ~12 GB / ~6 GB | default — **one**, never both |
| Qwen2.5-3B GGUF Q4 | shot planner | ~2 GB | default |
| NSFW image detection | safety | ~330 MB | default |
| Depth Anything V2 Small | depth | ~200 MB | default |
| RIFE 4.6 | Tier B interpolation | ~100 MB | in-repo (LFS) |
| SAM2 hiera-tiny | subject masks | ~150 MB | first Tier C job |
| CogVideoX-2B | sparse video + VAE | ~10 GB | first Tier C/D job |

Expected disk:

- **Default install (`core` + `t2i`): ~14 GB** with FLUX, ~8 GB with SDXL-Turbo
- **Full stack, all tiers exercised: ~24 GB**
- The first Tier C/D job pauses to fetch CogVideoX, then it is cached

Pre-fetch with:

```bash
export RENDERFLOW_MODELS_DIR=$HOME/renderflow-models
python scripts/download_rfir_models.py              # core + t2i (default)
python scripts/download_rfir_models.py --pack all   # everything up front
python scripts/download_rfir_models.py --dry-run    # show the plan, download nothing
```

Set `RENDERFLOW_MODELS_MAX_BYTES` to cap the tree — after each job, least-recently-used unpinned models are evicted until it fits. The small always-on models (planner, depth, RIFE, safety) are pinned and never evicted. On 8 GB-class GPUs (including most MacBooks), prefer SDXL-Turbo over FLUX via `RENDERFLOW_RFIR_T2I_MODEL=sdxl-turbo-fp16`.

### Platform notes

- **CUDA**: full feature set — AWQ/NF4 quantization, CUDA graph capture, `torch.compile`.
- **Apple Silicon (MPS)**: fp16 inference works for all ops; no `bitsandbytes`/`autoawq` quantization support (CUDA-only), so models run unquantized (more memory, fine with unified memory). CUDA graph capture (§5.2) is a no-op on MPS — there is no Metal equivalent in PyTorch.
- **CPU**: fp32 fallback, functional but slow — useful for testing the compile graph/pipeline without a GPU.

### Worker metrics (optional)

The model worker can expose Prometheus-style metrics (`rfir_gpu_seconds_total`, `rfir_tier_count`, `rfir_jobs_total`, `rfir_cost_usd_total`) via `app.rfir.metrics.serve_metrics(port)`, scraped at `/metrics`.

Disk working set (see [Model weights](#model-weights)): `rfir_model_disk_bytes` (gauge), `rfir_model_fetch_bytes_total`, `rfir_model_hit_roles_total`, `rfir_model_miss_roles_total`. Each job also logs one JSON line with `roles`, `hot_bytes`, `miss_bytes` and `rho_hat` — the measured share of the old prepaid catalog that job actually needed resident. A healthy Tier A worker sits well below 1.0 and its fetch counter stops growing once its roles are warm.

---

## Dependencies

- **Orchestrator:** `services/orchestrator/pyproject.toml` — `deepiri-gpu-utils` (Git) + `deepiri-renderflow-worker-queue` (`lib/renderflow_queue`); install with Poetry.
- Optional snippets under `vendor/deepiri/*` should include provenance headers if kept.

---

## License

See [LICENSE.md](LICENSE.md)
