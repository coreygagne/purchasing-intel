#!/bin/bash
# Purchasing Research for Mac: double-click this file in Finder. It sets itself up the first time, then opens
# http://127.0.0.1:8000 in your browser. Keep the Terminal window open while you use the app; close it to stop.
cd "$(dirname "$0")" || exit 1

pause_and_exit() {
  echo
  read -r -p "Press Return to close this window. " _
  exit "${1:-1}"
}

# 0. Updating: if this copy has no keys yet, bring the keys (.env) and saved research (data folder) across
#    from the previous copy in the same place (any folder named purchasing-intel...), newest first.
if [ ! -f .env ]; then
  here="$(pwd -P)"
  old=""
  for d in ../purchasing-intel*/; do
    d="${d%/}"
    [ -f "$d/.env" ] || continue
    [ "$(cd "$d" && pwd -P)" = "$here" ] && continue
    if [ -z "$old" ] || [ "$d/.env" -nt "$old/.env" ]; then old="$d"; fi
  done
  if [ -n "$old" ]; then
    echo "Found your previous copy: $(basename "$old")"
    cp -p "$old/.env" .env && chmod 600 .env && echo "  - copied your keys and settings"
    if [ -d "$old/data" ]; then
      [ -d data ] && mv data "data-replaced-$(date +%Y%m%d-%H%M%S)"
      cp -Rp "$old/data" data && echo "  - copied your saved research"
    fi
    echo "When everything looks right, you can delete the $(basename "$old") folder."
    echo
  fi
fi

# 1. Find Python 3.11 or newer. Apple's built-in /usr/bin/python3 is 3.9 (too old), so it is skipped.
PY=""
for c in python3.14 python3.13 python3.12 python3.11 /usr/local/bin/python3 /opt/homebrew/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && \
     "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is needed and was not found on this Mac."
  echo "Opening the Python download page: click the yellow 'Download Python' button, open the downloaded"
  echo "file and follow the installer. Then double-click 'Start Purchasing Research' again."
  open "https://www.python.org/downloads/macos/"
  pause_and_exit 1
fi

# 1b. Updating: a newer "Download ZIP" in your Downloads folder is copied over this folder (after asking),
#     keeping your keys, saved research and the .venv folder. Then this starter restarts as the new version.
"$PY" -I scripts/update_from_download.py "$(pwd)"
if [ $? -eq 3 ]; then
  echo
  echo "Restarting the updated version..."
  exec bash "./Start Purchasing Research.command"
fi

# 2. First time only: a private Python environment for the app (in the .venv folder)
if [ ! -x ".venv/bin/python" ]; then
  echo "Setting up for the first time. This takes a minute or two..."
  "$PY" -m venv .venv || { echo "Couldn't create the app's Python environment."; pause_and_exit 1; }
fi
echo "Checking the app's packages..."
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt || {
  echo "Setup didn't finish - see the messages above. Check the internet connection and try again."
  pause_and_exit 1
}

# 3. Start the app; it opens the browser by itself when it is ready
PORT="${PORT:-8000}"
export PI_OPEN_BROWSER="http://127.0.0.1:${PORT}"
echo
echo "Purchasing Research is running at http://127.0.0.1:${PORT}"
echo "Keep this window open while you use it. Close it (or press Control-C) to stop the app."
echo
.venv/bin/python -m uvicorn app.main:get_app --factory --host 127.0.0.1 --port "$PORT"
echo "The app has stopped. If you didn't stop it, read the messages above."
pause_and_exit 0
