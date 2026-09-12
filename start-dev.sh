#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cleanup() {
  echo "Stopping dev services..."
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

npx ng serve &

(cd "$ROOT_DIR/services/tts-service" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level debug --reload) &

(cd "$ROOT_DIR/services/translator-service" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 --log-level debug --reload) &

(cd "$ROOT_DIR/services/stt-service" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8002 --log-level debug --reload) &

wait
