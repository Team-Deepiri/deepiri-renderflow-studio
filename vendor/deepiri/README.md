# Deepiri Vendored Modules

Optional snippets copied from Deepiri packages when a **published or path dependency is not wired yet**.

## Current layout

- `helox/`, `synapse/`: placeholders / future adapters.
- `sugarglider/`: reserved.

## Not vendored (use real packages)

- **GPU detection:** install [`deepiri-gpu-utils`](../../../deepiri-gpu-utils) (Poetry path dep in the orchestrator).
- **Renderflow Redis job queue:** first-party [`lib/renderflow_queue`](../../lib/renderflow_queue), shared by the orchestrator and model workers.

Do not re-copy `deepiri-gpu-utils` or queue helpers here; sync upstream by bumping the path dependency or version in `services/ai-orchestrator-fastapi/pyproject.toml`.
