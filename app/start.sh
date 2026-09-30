#!/usr/bin/env bash
# Build the frontend (if needed) and serve RAJAR Pulse on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-$HOME/opt/anaconda3/envs/aiEnv/bin/python}"
if [ ! -d app/frontend/dist ] || [ "${REBUILD:-0}" = "1" ]; then
  (cd app/frontend && npm install --no-audit --no-fund && npm run build)
fi
exec "$PY" -m uvicorn app.backend.main:app --port "${PORT:-8000}"
