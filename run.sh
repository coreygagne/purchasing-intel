#!/usr/bin/env bash
# Start Purchasing Research on http://127.0.0.1:8000 (Linux / macOS).
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q -r requirements.txt
# The app reads .env itself; only HOST/PORT are needed here (read without executing .env as shell).
env_value() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' || true; }
HOST="${HOST:-$(env_value HOST)}"; HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-$(env_value PORT)}"; PORT="${PORT:-8000}"
echo "Purchasing Research: http://${HOST}:${PORT}"
# On a Mac, open the browser once the app is up (not on Linux, where there may be no desktop)
if [ "$(uname)" = "Darwin" ] && [ -z "${PI_OPEN_BROWSER:-}" ]; then export PI_OPEN_BROWSER="http://127.0.0.1:${PORT}"; fi
exec uvicorn app.main:get_app --factory --host "$HOST" --port "$PORT"
