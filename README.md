# Deepiri Renderflow Studio

Native animation and post-production studio for video editing, compositing, motion graphics, and 3D workflows.

## Principles

- Native-first desktop architecture (`Tauri` + Rust/C++ core).
- Vulkan-first rendering pipeline.
- Optional AI copilot with full manual/no-AI parity.
- Reuse Deepiri internals by vendoring/adapting code instead of direct imports.

## Monorepo Layout

- `apps/desktop-tauri`: desktop shell and editor UI host.
- `core/timeline-engine-rs`: deterministic timeline and playback math.
- `core/render-engine-vulkan`: render graph and GPU orchestration.
- `core/audio-engine-juce`: JUCE integration boundary for audio graph.
- `services/ai-orchestrator-fastapi`: job orchestration and API.
- `services/model-workers-pytorch`: model worker entrypoints.
- `proto/grpc`: gRPC contracts for desktop<->services IPC.
- `infra/postgres/migrations`: SQL schema.
- `vendor/deepiri`: copied/adapted Deepiri modules.

## Getting Started (bootstrap)

1. Build timeline crate:
   - `cargo test --manifest-path core/timeline-engine-rs/Cargo.toml`
2. Run AI orchestrator:
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -r services/ai-orchestrator-fastapi/requirements.txt`
   - `uvicorn app.main:app --app-dir services/ai-orchestrator-fastapi --reload`
3. Run model worker:
   - `python services/model-workers-pytorch/app/worker.py`

## Vendoring Policy

Deepiri code under `vendor/deepiri/*` must include:
- origin module path,
- source commit/hash where available,
- adaptation notes for Renderflow.
