#!/usr/bin/env bash
# Start Purchasing Research on http://127.0.0.1:8000 (Linux / macOS).
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  # Python 3.11+ (on a Mac, Apple's /usr/bin/python3 is 3.9, so look for newer installs first)
  PY=""
  for c in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      PY="$c"; break
    fi
  done
  [ -n "$PY" ] || { echo "Python 3.11 or newer is needed: https://www.python.org/downloads/" >&2; exit 1; }
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
# A newer "Download ZIP" in ~/Downloads is copied over this folder (after asking), keeping .env, data and .venv
rc=0; python -I scripts/update_from_download.py "$(pwd)" || rc=$?
if [ "$rc" -eq 3 ]; then echo "Restarting the updated version..."; exec bash "$0" "$@"; fi
pip install -q -r requirements.txt
# The app reads .env itself; only HOST/PORT are needed here (read without executing .env as shell).
env_value() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' || true; }
HOST="${HOST:-$(env_value HOST)}"; HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-$(env_value PORT)}"; PORT="${PORT:-8000}"
echo "Purchasing Research: http://${HOST}:${PORT}"
# On a Mac, open the browser once the app is up (not on Linux, where there may be no desktop)
if [ "$(uname)" = "Darwin" ] && [ -z "${PI_OPEN_BROWSER:-}" ]; then export PI_OPEN_BROWSER="http://127.0.0.1:${PORT}"; fi
exec uvicorn app.main:get_app --factory --host "$HOST" --port "$PORT"
