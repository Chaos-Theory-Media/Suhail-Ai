#!/bin/zsh
# Starts Sawti in the background (if it is not already running) and opens it in the browser.
# Used by Sawti.app, START_SAWTI.command and SIMULATE_SAWTI.command. Closing a Terminal window does not stop it;
# use Quit in the Sawti page.
HERE="${0:A:h}"
SUPPORT="$HOME/Library/Application Support/Sawti"
PY="$SUPPORT/venv/bin/python"
PORT="${SAWTI_PORT:-8765}"
URL="http://127.0.0.1:$PORT"

if curl -fs --max-time 1 "$URL/api/app" >/dev/null 2>&1; then
  open "$URL"; exit 0
fi
if [[ ! -x "$PY" ]] || ! "$PY" -c 'import flask, numpy, scipy, sounddevice, soundfile' >/dev/null 2>&1; then
  osascript -e 'display dialog "Sawti is not installed yet, or needs a repair.\n\nOpen the Sawti folder and run INSTALL_SAWTI.command." buttons {"OK"} default button 1 with title "Sawti" with icon caution' >/dev/null 2>&1
  echo "Sawti is not installed yet. Run INSTALL_SAWTI.command."
  exit 1
fi
mkdir -p "$SUPPORT/run"
cd "$HERE" || exit 1
nohup "$PY" "$HERE/app.py" "$@" >> "$SUPPORT/run/sawti.log" 2>&1 &
for i in {1..60}; do
  curl -fs --max-time 1 "$URL/api/app" >/dev/null 2>&1 && break
  sleep 0.25
done
open "$URL"
