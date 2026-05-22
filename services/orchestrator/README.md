# Renderflow AI orchestrator (FastAPI + gRPC)

## Setup (Poetry)

From this directory:

```bash
poetry install
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Dependencies in `pyproject.toml`:

- **`deepiri-gpu-utils`** — from **Git** (`https://github.com/Team-Deepiri/deepiri-gpu-utils.git`, branch `main`). `poetry.lock` pins the commit. Bump with:

  ```bash
  poetry update deepiri-gpu-utils
  ```

  To pin one revision, use `rev = "…"` instead of `branch = "main"`, then `poetry lock`.

- **`deepiri-renderflow-worker-queue`** — **path** to `../../lib/renderflow_queue` (inside **this** repo: `deepiri-renderflow-studio/lib/renderflow_queue`). Import in code: `from renderflow_queue import …`.

For offline GPU work, temporarily set `deepiri-gpu-utils` to a local path and run `poetry lock`.

## Docker

Build context is the **`deepiri-renderflow-studio`** repo root so `lib/renderflow_queue` resolves. See `../../infra/docker/Dockerfile.orchestrator` (`poetry install` in the image).

## Legacy pip

`requirements.txt` is PyPI-only. The image does **not** rely on it for Deepiri deps; use Poetry in Docker as in the Dockerfile.

## Health Endpoints

- `GET /health`: liveness check for process availability. Returns `200` with `{"status":"ok"}` when the API process is up.
- `GET /ready`: readiness check with dependency status for Postgres and Redis.

`/ready` response shape:

```json
{
  "status": "ready",
  "mode": "dev",
  "dependencies": {
    "postgres": {
      "status": "disabled",
      "configured": false,
      "detail": "DATABASE_URL not set or PostgreSQL pool unavailable"
    },
    "redis": {
      "status": "ok",
      "configured": true,
      "detail": "Redis reachable"
    }
  }
}
```

Dependency statuses:

- `ok`: configured and reachable
- `disabled`: not configured
- `degraded`: configured but currently unreachable (fallback/partial behavior may still allow serving)
- `failed`: configured and required but unavailable

## Readiness Mode

`READINESS_MODE` controls how dependency states map to HTTP readiness.

- `dev` (default): permissive mode. `ok`, `disabled`, and `degraded` are treated as ready (`200`). `failed` returns `503`.
- `prod`: strict mode. all dependencies must be `ok` to return ready (`200`); otherwise `/ready` returns `503`.
