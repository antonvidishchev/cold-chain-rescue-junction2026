#!/usr/bin/env bash
# Run backend and frontend together. Ctrl-C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

(cd "$ROOT/backend" && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &
BACK=$!
(cd "$ROOT/frontend" && npm run dev) &
FRONT=$!

trap 'kill $BACK $FRONT 2>/dev/null' INT TERM EXIT
wait
