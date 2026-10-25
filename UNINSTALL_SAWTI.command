#!/bin/zsh
# Removes Sawti. Recordings are never touched.
SUPPORT="$HOME/Library/Application Support/Sawti"
print "Sawti uninstaller — your recordings are NOT deleted."
read "a?Have you checked all production recording is stopped and the studio is idle? [y/n]: "; [[ "$a" == [yY]* ]] || exit 0
for port in 8765 8766; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    print "Port $port is occupied. Quit Sawti manually before uninstalling; no listener was stopped."
    read "?Press Return to close."
    exit 1
  fi
done
sleep 1
print "Audio devices and routing are retained: another application may still use them."
rm -rf "$HOME/Applications/Sawti.app" "$HOME/Desktop/Sawti" "$HOME/Desktop/Sawti.app"
read "a?Delete Sawti's data (local AI model, learned habits, templates, settings)? [y/n]: "
if [[ "$a" == [yY]* ]]; then
  # Never recursively remove a folder that may contain production recordings.
  if [[ -x "$SUPPORT/venv/bin/python" ]] && "$SUPPORT/venv/bin/python" - "$SUPPORT" <<'SAWTI_SCAN'
import os, sys
from pathlib import Path
media = {'.wav', '.aif', '.aiff', '.flac', '.sesx', '.mp3', '.m4a'}
def inaccessible(error):
    raise error
try:
    for root, dirs, files in os.walk(sys.argv[1], onerror=inaccessible):
        if any(Path(name).suffix.lower() in media for name in files):
            sys.exit(1)
except OSError:
    sys.exit(1)
SAWTI_SCAN
  then
    rm -rf "$SUPPORT" && print "Sawti data removed."
  else
    print "Data retained: audio/session files were found or complete inspection was unavailable. Archive and review: $SUPPORT"
  fi
fi
print "Done. You can now delete the Sawti folder."
read "?Press Return to close."
