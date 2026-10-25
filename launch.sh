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
SAWTI_PID=$!
READY=0
for i in {1..60}; do
  kill -0 "$SAWTI_PID" 2>/dev/null || break
  curl -fs --max-time 1 "$URL/api/app" >/dev/null 2>&1 && { READY=1; break; }
  sleep 0.25
done
if (( ! READY )); then
  print "Sawti did not become ready. Review $SUPPORT/run/sawti.log; no other process was stopped."
  exit 1
fi
open "$URL"
