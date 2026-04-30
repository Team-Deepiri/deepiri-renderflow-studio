#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ORCH="$ROOT/services/orchestrator"
cd "$ORCH"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m uvicorn app.main:app --host "${RENDERFLOW_HTTP_HOST:-127.0.0.1}" --port "${RENDERFLOW_HTTP_PORT:-8080}"
fi
exec poetry run uvicorn app.main:app --host "${RENDERFLOW_HTTP_HOST:-127.0.0.1}" --port "${RENDERFLOW_HTTP_PORT:-8080}"
