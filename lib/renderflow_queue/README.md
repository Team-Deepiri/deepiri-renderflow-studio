# Worker queue (in-repo)

This directory lives **inside** `deepiri-renderflow-studio` at `lib/renderflow_queue/`. It is not a separate repository.

Python import path: `renderflow_queue` (`REDIS_KEY_JOBS`, `RedisJobQueue`).

Orchestrator and `services/model-workers` depend on it via Poetry:

```toml
deepiri-renderflow-worker-queue = { path = "../../lib/renderflow_queue", develop = true }
```
