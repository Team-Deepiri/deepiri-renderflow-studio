# Deepiri Renderflow Studio

Native animation and post-production studio for video editing, compositing, motion graphics, and 3D workflows.

## Principles

- Native-first desktop architecture (`Tauri` + Rust/C++ core).
- Vulkan-first rendering pipeline.
- Optional AI copilot with full manual/no-AI parity.
- Reuse Deepiri packages as **path/Poetry dependencies** where they exist (e.g. `deepiri-gpu-utils`); keep small Renderflow-only helpers as first-party crates under `packages/`.

## Monorepo Layout

- `apps/desktop-tauri`: desktop shell and editor UI host.
- `core/timeline-engine-rs`: deterministic timeline and playback math.
- `core/render-engine-vulkan`: render graph and GPU orchestration.
- `core/audio-engine-juce`: JUCE integration boundary for audio graph.
- `services/ai-orchestrator-fastapi`: job orchestration and API.
- `services/model-workers-pytorch`: model worker entrypoints.
- `proto/grpc`: gRPC contracts for desktop<->services IPC.
- `infra/postgres/migrations`: SQL schema.
- `lib/renderflow_queue`: in-repo Redis AI job queue (shared orchestrator + workers).
- `vendor/deepiri`: optional legacy snippets only; GPU + queue live in real packages above.

## Getting Started (bootstrap)

Layout: clone **`deepiri-gpu-utils`** next to **`deepiri-renderflow-studio`** (sibling under the same parent) so Poetry path dependencies resolve.

1. Build timeline crate:
   - `cargo test --manifest-path core/timeline-engine-rs/Cargo.toml`
2. Run AI orchestrator (HTTP + gRPC + in-process AI worker):
   - `cd services/ai-orchestrator-fastapi && poetry install`
   - `./scripts/run_orchestrator.sh` (uses `.venv` or `poetry run`)
   - Or: `cd services/ai-orchestrator-fastapi && poetry run uvicorn app.main:app --host 127.0.0.1 --port 8080`
   - HTTP: `http://127.0.0.1:8080/health`, jobs: `POST /v1/jobs`, `GET /v1/jobs/{id}`
   - gRPC: `AiSessionService` on `RENDERFLOW_GRPC_HOST`:`RENDERFLOW_GRPC_PORT` (default `0.0.0.0:50051`)
3. Optional: Redis-backed job queue — set `REDIS_URL=redis://127.0.0.1:6380/0` (see `infra/docker/docker-compose.yml`).
4. Optional: PostgreSQL — set `DATABASE_URL=postgresql://renderflow:renderflow@127.0.0.1:5433/renderflow` after `docker compose -f infra/docker/docker-compose.yml up -d`.
5. Integration smoke: `services/ai-orchestrator-fastapi/.venv/bin/python scripts/smoke_integration.py` (after `poetry install` in the orchestrator)
6. Native engines (no Tauri/GTK): `./scripts/verify_native_engines.sh` — exercises `timeline-engine-rs` and `render-engine-vulkan` (graph schedule + Vulkan `discover()` when an ICD is present).
7. Regenerate gRPC Python stubs after proto edits: `./scripts/gen_proto.sh`
8. Desktop (Tauri + Vite UI): `cd apps/desktop-tauri/ui && npm install && npm run build`, then `cd apps/desktop-tauri/src-tauri && cargo build` — on Linux install WebKitGTK dev packages (e.g. Debian/Ubuntu: `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`, `pkg-config`, `libssl-dev`). The desktop binary links **`timeline-engine-rs`** and **`render-engine-vulkan`** and exposes Tauri commands: `timeline_resolve_active`, `render_graph_schedule`, `vulkan_discover`, `orchestrator_list_projects`, plus existing orchestrator/AI helpers.
9. Model worker CLI: `python3 services/model-workers-pytorch/app/worker.py` — Redis consumer: `cd services/model-workers-pytorch && poetry install && poetry run python -m app.redis_worker`
10. Full stack Docker: run `docker compose` from `infra/docker` (orchestrator build context is the **parent** of this repo so `deepiri-gpu-utils` is included): `docker compose -f infra/docker/docker-compose.yml build orchestrator && docker compose -f infra/docker/docker-compose.yml up -d`

### Desktop → orchestrator

Set `RENDERFLOW_ORCHESTRATOR_URL` (default `http://127.0.0.1:8080`). Tauri commands: `orchestrator_health`, `submit_ai_job`, `get_ai_job`.

## Dependencies

- **Orchestrator:** `services/ai-orchestrator-fastapi/pyproject.toml` — `deepiri-gpu-utils` (Git) + `deepiri-renderflow-worker-queue` (`lib/renderflow_queue`); install with Poetry.
- Optional snippets under `vendor/deepiri/*` should include provenance headers if kept.
