# Renderflow Studio — module boundaries

## Python orchestrator (`services/orchestrator`)

| Area | Location | Responsibility |
|------|----------|----------------|
| Dependency management | **`pyproject.toml` (Poetry)** | PyPI deps + **`deepiri-gpu-utils`** (Git) + **`deepiri-renderflow-worker-queue`** (path → `lib/renderflow_queue`). |
| HTTP surface | `app/api/routers/*.py` | Route handlers; thin delegation. |
| Request/response models | `app/api/schemas/studio.py` | Pydantic models. |
| GPU / accelerator | **`deepiri_gpu_utils`** | Installed from `deepiri-gpu-utils` repo. |
| AI job Redis queue | **`renderflow_queue`** (import name) | `RedisJobQueue`, `REDIS_KEY_JOBS` — source in **`lib/renderflow_queue/`** inside this repository. |
| Studio domain | `app/services/studio.py`, `app/memory_store.py`, `app/db_repos.py` | Projects, timeline, scenes, render jobs. |
| AI jobs | `app/job_store.py`, `app/worker_loop.py`, `app/stage_runner.py` | Job lifecycle. |
| gRPC | `app/grpc_service.py`, `app/gen/` | Generated stubs. |
| Media | `app/media/ffmpeg.py` | ffprobe helpers. |

**Rules**

- No `sys.path` hacks for Deepiri GPU code: use **`deepiri-gpu-utils`** via Poetry.
- Queue contract is **first-party** under **`deepiri-renderflow-studio/lib/renderflow_queue/`**; orchestrator and **`services/model-workers`** depend on the same Poetry path package.

## In-repo Python library (`lib/renderflow_queue/`)

| Piece | Role |
|-------|------|
| `deepiri-renderflow-worker-queue` (distribution name) | Editable path dep; import **`renderflow_queue`**. |

## Rust core (`core/`)

| Crate | Role |
|-------|------|
| `timeline-engine-rs` | Timebase, sequences, clip queries. |
| `render-engine-vulkan` | Vulkan discovery, render graph scheduling. |

## Desktop (`apps/desktop-tauri`)

| Rust module | Role |
|-------------|------|
| `commands/orchestrator.rs` | HTTP client to the orchestrator. |
| `commands/engine.rs` | Local timeline + Vulkan helpers. |

## Docker

Orchestrator image uses repo-root `COPY . /app` so `lib/renderflow_queue` path deps resolve. See `infra/docker/Dockerfile.orchestrator`.
