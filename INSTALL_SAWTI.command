#!/bin/zsh
# Sawti 3.0 installer for Apple-silicon Macs (macOS 14 Sonoma or newer).
# Safe to run again at any time: it repairs or updates what is missing and keeps settings and learning.
#
# Installs, all inside ~/Library/Application Support/Sawti (nothing in /Applications is changed):
#   * its own Python (via uv) and libraries       * the Sawti audio helper (compiled here from helpers/)
#   * a private Ollama + Qwen3 4B (optional)      * offline voice features (optional)
#   * the "Sawti" app in ~/Applications and an alias on the Desktop
set -u
HERE="${0:A:h}"
SUPPORT="$HOME/Library/Application Support/Sawti"
RUNTIME="$SUPPORT/runtime"
BIN="$SUPPORT/bin"
MODELS="$SUPPORT/models"
VENV="$SUPPORT/venv"
LOG="$SUPPORT/install.log"
MODEL="qwen3:4b"
mkdir -p "$RUNTIME" "$BIN" "$MODELS" "$SUPPORT/run"
exec > >(tee -a "$LOG") 2>&1

TMP=""
SERVER_PID=""
cleanup() {
  [[ -n "$SERVER_PID" ]] && { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; SERVER_PID=""; }
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT INT TERM
step() { print "\n\033[1m▶ $1\033[0m"; }
ok()   { print "  ✓ $1"; }
warn() { print "  ! $1"; }
fail() { print "\n✖ $1\n  Nothing else was changed. Full log: $LOG"; read "?Press Return to close."; exit 1; }
yes_no() { local a; read "a?$1 [y/n]: "; [[ "$a" == [yY]* ]]; }

print "────────────────────────────────────────────"
print " Sawti 3.0 · studio agents · installer"
print "────────────────────────────────────────────"
[[ "$(uname -s)" == "Darwin" ]] || fail "This installer is for macOS."
[[ "$(uname -m)" == "arm64" ]] || fail "An Apple-silicon Mac (M1 or newer) is required."
MACOS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
(( MACOS_MAJOR >= 14 )) || fail "macOS 14 Sonoma or newer is required (this Mac has $(sw_vers -productVersion))."

# Files from a downloaded ZIP are quarantined; clear it for this folder so the other scripts open normally.
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null && ok "Sawti folder approved for this Mac"

print "\nThis will download about 3–4 GB (Python, libraries, local AI) the first time."
WANT_AI=1; WANT_VOICE=0
yes_no "Install the local AI assistant (Qwen3 4B, about 2.6 GB, recommended)?" || WANT_AI=0
yes_no "Install offline voice commands (speech-to-text, about 1.5 GB more)?" && WANT_VOICE=1

# ---------------------------------------------------------------- Python (no system Python needed)
step "Python and libraries"
UV="$RUNTIME/uv/uv"
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python" UV_CACHE_DIR="$SUPPORT/cache/uv"
if [[ ! -x "$UV" ]]; then
  TMP=$(mktemp -d)
  if curl --fail --location --retry 2 --silent --show-error \
      "https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz" -o "$TMP/uv.tgz" \
     && tar -xzf "$TMP/uv.tgz" -C "$TMP"; then
    mkdir -p "$RUNTIME/uv" && mv "$TMP"/uv-aarch64-apple-darwin/uv* "$RUNTIME/uv/" && ok "Python manager installed"
  else
    warn "Could not download the Python manager; trying the Mac's own Python."
  fi
  rm -rf "$TMP"; TMP=""
fi
if [[ -x "$UV" ]]; then
  if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12)' 2>/dev/null; then
    rm -rf "$VENV"
    "$UV" python install 3.12 || fail "Could not install Python 3.12."
    "$UV" venv --python 3.12 "$VENV" || fail "Could not create Sawti's Python environment."
  fi
  "$UV" pip install --python "$VENV/bin/python" -r "$HERE/requirements.txt" || fail "Library installation failed (check the internet connection)."
else
  PY=$(command -v python3 || true)
  [[ -n "$PY" ]] && "$PY" -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 13)' 2>/dev/null \
    || fail "No suitable Python found. Connect to the internet and run this installer again."
  [[ -x "$VENV/bin/python" ]] || "$PY" -m venv "$VENV" || fail "Could not create Sawti's Python environment."
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  "$VENV/bin/python" -m pip install -r "$HERE/requirements.txt" || fail "Library installation failed."
fi
"$VENV/bin/python" -c 'import flask, numpy, scipy, sounddevice, soundfile, psutil' || fail "Libraries did not load."
ok "Python $("$VENV/bin/python" -c 'import platform; print(platform.python_version())') ready"

# ---------------------------------------------------------------- audio helper (CoreAudio)
step "Sawti audio helper (creates and repairs audio devices)"
if xcrun --find swiftc >/dev/null 2>&1; then
  if xcrun swiftc -O -swift-version 5 "$HERE/helpers/sawti-audio.swift" -o "$BIN/sawti-audio.new" 2>>"$LOG"; then
    mv "$BIN/sawti-audio.new" "$BIN/sawti-audio"
    "$BIN/sawti-audio" list | grep -q '"ok":true' && ok "Audio helper ready" || warn "Audio helper built but could not list devices."
  else
    warn "The audio helper did not compile (details in the log). Sawti will still check everything, but cannot create devices."
  fi
else
  warn "Apple's Command Line Tools are needed to build the audio helper."
  xcode-select --install >/dev/null 2>&1
  warn "Click Install in the window that just opened, wait for it to finish, then run this installer again."
fi

# ---------------------------------------------------------------- BlackHole (Zoom shows)
step "BlackHole (needed for Zoom shows)"
if system_profiler SPAudioDataType 2>/dev/null | grep -q "BlackHole 2ch"; then
  ok "BlackHole 2ch installed"
else
  warn "BlackHole 2ch is not installed. Zoom shows need it."
  if command -v brew >/dev/null 2>&1 && yes_no "Install BlackHole 2ch now with Homebrew (asks for the Mac password)?"; then
    brew install --cask blackhole-2ch && ok "BlackHole 2ch installed (restart the Mac if it does not appear)"
  else
    warn "Ask IT to install 'BlackHole 2ch' from existential.audio. Podcast shows work without it."
  fi
fi

# ---------------------------------------------------------------- local AI
if (( WANT_AI )); then
  step "Local AI (private Ollama on port 11439, model $MODEL)"
  OLLAMA_APP="$RUNTIME/Ollama.app"
  OLLAMA_BIN="$OLLAMA_APP/Contents/Resources/ollama"
  if [[ ! -x "$OLLAMA_BIN" ]]; then
    TMP=$(mktemp -d)
    curl --fail --location --retry 2 --progress-bar \
         "https://github.com/ollama/ollama/releases/latest/download/Ollama-darwin.zip" -o "$TMP/Ollama.zip" \
      || curl --fail --location --retry 2 --progress-bar "https://ollama.com/download/Ollama-darwin.zip" -o "$TMP/Ollama.zip" \
      || fail "Could not download Ollama."
    unzip -q "$TMP/Ollama.zip" -d "$TMP" || fail "The Ollama download is damaged."
    [[ -x "$TMP/Ollama.app/Contents/Resources/ollama" ]] || fail "Unexpected Ollama package layout."
    codesign --verify --deep --strict "$TMP/Ollama.app" 2>/dev/null || fail "Ollama's code signature did not verify."
    rm -rf "$OLLAMA_APP"
    mv "$TMP/Ollama.app" "$OLLAMA_APP"
    rm -rf "$TMP"; TMP=""
    ok "Ollama installed privately for Sawti"
  else
    ok "Ollama already installed for Sawti"
  fi
  if lsof -nP -iTCP:11439 -sTCP:LISTEN >/dev/null 2>&1; then
    warn "Sawti's AI port is busy (Sawti may be running). Quit Sawti and run the installer again to download the model."
  else
    OLLAMA_HOST="127.0.0.1:11439" OLLAMA_MODELS="$MODELS" "$OLLAMA_BIN" serve >"$SUPPORT/run/installer-ollama.log" 2>&1 &
    SERVER_PID=$!
    READY=0
    for i in {1..40}; do curl -fs --max-time 2 http://127.0.0.1:11439/api/tags >/dev/null 2>&1 && { READY=1; break; }; sleep 0.5; done
    (( READY )) || fail "The local AI service did not start (see $SUPPORT/run/installer-ollama.log)."
    if OLLAMA_HOST="127.0.0.1:11439" "$OLLAMA_BIN" list | grep -q "^$MODEL"; then
      ok "$MODEL already downloaded"
    else
      print "  Downloading $MODEL (one time)…"
      OLLAMA_HOST="127.0.0.1:11439" "$OLLAMA_BIN" pull "$MODEL" || fail "Model download failed."
      ok "$MODEL downloaded"
    fi
    cleanup
  fi
fi

# ---------------------------------------------------------------- voice (optional)
if (( WANT_VOICE )); then
  step "Offline voice commands"
  if ! command -v ffmpeg >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then brew install ffmpeg || warn "ffmpeg install failed."; fi
  fi
  if command -v ffmpeg >/dev/null 2>&1; then
    if [[ -x "$UV" ]]; then "$UV" pip install --python "$VENV/bin/python" -r "$HERE/requirements-voice.txt"
    else "$VENV/bin/python" -m pip install -r "$HERE/requirements-voice.txt"; fi \
      && ok "Voice features installed (the speech model downloads on first use)" || warn "Voice features failed to install; Sawti works without them."
  else
    warn "Voice needs ffmpeg (install Homebrew, then run this installer again). Skipped."
  fi
fi

# ---------------------------------------------------------------- Sawti app
step "Sawti app"
APPDIR="$HOME/Applications"; mkdir -p "$APPDIR"
APP="$APPDIR/Sawti.app"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script quoted form of \"$HERE/launch.sh\" & \" > /dev/null 2>&1 &\"" \
  || fail "Could not create the Sawti app."
plutil -replace NSMicrophoneUsageDescription -string "Sawti measures microphone levels for the studio checks. Audio is never recorded or sent anywhere." "$APP/Contents/Info.plist"
plutil -replace NSAppleEventsUsageDescription -string "Sawti presses Record and Stop in Adobe Audition when you ask it to." "$APP/Contents/Info.plist"
plutil -replace CFBundleIdentifier -string "com.imi.sawti" "$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "Sawti" "$APP/Contents/Info.plist"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1
osascript -e "tell application \"Finder\" to make alias file to (POSIX file \"$APP\") at desktop" >/dev/null 2>&1 \
  && ok "Sawti app in ~/Applications, alias on the Desktop" || ok "Sawti app in ~/Applications"
chmod +x "$HERE"/*.command "$HERE/launch.sh"

print "\n────────────────────────────────────────────"
print " ✅ Sawti is installed."
print "    Open it from the Desktop (Sawti) or ~/Applications."
print "    For training without hardware: SIMULATE_SAWTI.command"
print "    The first time Sawti meters audio, macOS asks for microphone access — click Allow."
print "────────────────────────────────────────────"
"$HERE/launch.sh"
read "?Press Return to close this window."
