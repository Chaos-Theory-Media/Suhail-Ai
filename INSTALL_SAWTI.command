#!/bin/zsh
# Sawti 2.2: first-run assisted installer for Apple silicon Macs.
set -e
cd "${0:A:h}"
SUPPORT="$HOME/Library/Application Support/Sawti"
OLLAMA_APP="$SUPPORT/runtime/Ollama.app"
OLLAMA_BIN="$OLLAMA_APP/Contents/Resources/ollama"
MODELS="$SUPPORT/models"
PORT="127.0.0.1:11439"
print "Sawti 2.2 local AI setup"
print "This installs Python dependencies, Ollama and Qwen3 4B on THIS Mac."
print "Ollama comes from https://ollama.com/download/Ollama-darwin.zip"
print "Qwen3 4B is downloaded from Ollama's model registry."
print "No existing Ollama installation, Focusrite or Audition settings will be changed."
read "REPLY?Download and install these components? [yes/NO]: "
[[ "$REPLY" == "yes" ]] || { print "Installation cancelled."; exit 0; }
[[ "$(uname -s)" == "Darwin" ]] || { print "Mac only"; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || { print "Apple Silicon Mac required"; exit 1; }
command -v python3 >/dev/null || { print "Python 3.11 or 3.12 must be installed first."; exit 1; }
PY_MINOR=$(python3 -c 'import sys;print(sys.version_info.major,sys.version_info.minor,sep=".")')
case "$PY_MINOR" in 3.11|3.12) ;; *) print "Python 3.11 or 3.12 required; found $PY_MINOR"; exit 1;; esac
mkdir -p "$SUPPORT/runtime" "$MODELS"
if [[ ! -x "$OLLAMA_BIN" ]]; then
 print "Downloading Ollama from the official provider..."
 TMP=$(mktemp -d)
 trap 'rm -rf "$TMP"' EXIT
 curl --fail --location --retry 2 --show-error --progress-bar 'https://ollama.com/download/Ollama-darwin.zip' -o "$TMP/Ollama.zip"
 unzip -q "$TMP/Ollama.zip" -d "$TMP"
 [[ -x "$TMP/Ollama.app/Contents/Resources/ollama" ]] || { print "Unexpected Ollama archive layout"; exit 1; }
 mv "$TMP/Ollama.app" "$OLLAMA_APP"
fi
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -r requirements.txt
print "Preparing isolated Sawti model service..."
# Refuse to use or kill a service not created by this installer.
if lsof -nP -iTCP:11439 -sTCP:LISTEN >/dev/null 2>&1; then
 print "Port 11439 is already occupied. Stop the existing Sawti instance first."; exit 1
fi
export OLLAMA_HOST="$PORT" OLLAMA_MODELS="$MODELS"
"$OLLAMA_BIN" serve > "$SUPPORT/installer-ollama.log" 2>&1 &
SERVER_PID=$!
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
READY=0
for i in {1..30}; do
 if curl -fsS --max-time 2 "http://$PORT/api/tags" >/dev/null 2>&1; then READY=1; break; fi
 sleep 1
done
[[ $READY == 1 ]] || { print "Ollama could not start. See $SUPPORT/installer-ollama.log"; exit 1; }
print "Downloading Qwen3 4B (one-time download, several GB)..."
"$OLLAMA_BIN" pull qwen3:4b
"$OLLAMA_BIN" list | grep -q 'qwen3:4b' || { print 'Qwen model verification failed'; exit 1; }
print "Qwen3 4B verified in private Sawti model storage."
cleanup
trap - EXIT INT TERM
print "Setup complete. Launch START_SAWTI.command and switch Sawti ON."
read "DONE?Press Return to close the installer."
