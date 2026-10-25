#!/bin/zsh
# Sawti 3.0.2 installer for Apple-silicon Macs (macOS 14 Sonoma or newer).
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
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
step() { print "\n\033[1m▶ $1\033[0m"; }
ok()   { print "  ✓ $1"; }
warn() { print "  ! $1"; }
fail() { print "\n✖ $1\n  Setup stopped; earlier completed steps may remain. Full log: $LOG"; read "?Press Return to close."; exit 1; }
yes_no() { local a; read "a?$1 [y/n]: "; [[ "$a" == [yY]* ]]; }

print "────────────────────────────────────────────"
print " Sawti 3.0.2 · studio agents · installer"
print "────────────────────────────────────────────"
[[ "$(uname -s)" == "Darwin" ]] || fail "This installer is for macOS."
[[ "$(uname -m)" == "arm64" ]] || fail "An Apple-silicon Mac (M1 or newer) is required."
MACOS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
(( MACOS_MAJOR >= 14 )) || fail "macOS 14 Sonoma or newer is required (this Mac has $(sw_vers -productVersion))."

# Keep Gatekeeper/quarantine verification intact. The operator uses the macOS
# approval UI; the installer must not remove trust metadata recursively.
yes_no "Have you checked that all production recording is stopped and the studio is idle?" || exit 0
for active_port in 8765 8766; do
  if lsof -nP -iTCP:$active_port -sTCP:LISTEN >/dev/null 2>&1; then
    fail "Quit Sawti before updating its runtime. Port $active_port is occupied; no process was stopped."
  fi
done

print "\nThis will download about 3–4 GB (Python, libraries, local AI) the first time."
WANT_AI=1; WANT_VOICE=0
yes_no "Install the local AI assistant (Qwen3 4B, about 2.6 GB, recommended)?" || WANT_AI=0
yes_no "Install offline voice commands (speech-to-text, about 1.5 GB more)?" && WANT_VOICE=1

# ---------------------------------------------------------------- Python (no system Python needed)
step "Python and libraries"
UV="$RUNTIME/uv/uv"
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python" UV_CACHE_DIR="$SUPPORT/cache/uv"
export PIP_CACHE_DIR="$SUPPORT/cache/pip" HF_HOME="$SUPPORT/cache/huggingface"
if [[ ! -x "$UV" ]]; then
  TMP=$(mktemp -d)
  if curl --fail --location --retry 2 --silent --show-error \
      "https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz" -o "$TMP/uv-aarch64-apple-darwin.tar.gz" \
     && curl --fail --location --retry 2 --silent --show-error \
      "https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz.sha256" -o "$TMP/uv.sha256" \
     && (cd "$TMP" && shasum -a 256 -c uv.sha256) \
     && tar -xzf "$TMP/uv-aarch64-apple-darwin.tar.gz" -C "$TMP"; then
    mkdir -p "$RUNTIME/uv" && mv "$TMP"/uv-aarch64-apple-darwin/uv* "$RUNTIME/uv/" && ok "Python manager installed"
  else
    warn "Could not download and verify the Python manager; the downloaded artifact will not be used. Trying system Python."
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
    spctl --assess --type execute "$TMP/Ollama.app" 2>/dev/null || fail "macOS did not approve Ollama's publisher/notarisation."
    rm -rf "$OLLAMA_APP"
    mv "$TMP/Ollama.app" "$OLLAMA_APP"
    rm -rf "$TMP"; TMP=""
    ok "Ollama installed privately for Sawti"
  else
    ok "Ollama already installed for Sawti"
  fi
  codesign --verify --deep --strict "$OLLAMA_APP" 2>/dev/null || fail "Installed Ollama signature is invalid."
  spctl --assess --type execute "$OLLAMA_APP" 2>/dev/null || fail "Installed Ollama did not pass Gatekeeper assessment."
  if lsof -nP -iTCP:11439 -sTCP:LISTEN >/dev/null 2>&1; then
    warn "Sawti's AI port is busy (Sawti may be running). Quit Sawti and run the installer again to download the model."
  else
    OLLAMA_NO_CLOUD=1 OLLAMA_HOST="127.0.0.1:11439" OLLAMA_MODELS="$MODELS" "$OLLAMA_BIN" serve >"$SUPPORT/run/installer-ollama.log" 2>&1 &
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
      && {
        "$VENV/bin/python" -c 'import sys; from faster_whisper import WhisperModel; WhisperModel("small", device="cpu", compute_type="int8", download_root=sys.argv[1]); from resemblyzer import VoiceEncoder; VoiceEncoder()' "$MODELS/whisper" \
          && ok "Voice packages and models cached; offline operation still needs a studio test." \
          || warn "Voice model preloading failed. Voice is not ready for offline use."
      } || warn "Voice features failed to install; Sawti works without them."
  else
    warn "Voice needs ffmpeg (install Homebrew, then run this installer again). Skipped."
  fi
fi

# ---------------------------------------------------------------- Sawti app
step "Sawti app"
APPDIR="$HOME/Applications"; mkdir -p "$APPDIR"
APP="$APPDIR/Sawti.app"
STAGED_APP="$APPDIR/Sawti-install-$RANDOM.app"
osacompile -o "$STAGED_APP" \
  -e 'set appPath to POSIX path of (path to me)' \
  -e 'set launcher to do shell script "/bin/cat " & quoted form of (appPath & "Contents/Resources/launcher-path")' \
  -e 'do shell script quoted form of launcher & " > /dev/null 2>&1 &"' \
  || fail "Could not create the Sawti app."
mkdir -p "$STAGED_APP/Contents/Resources"
print -r -- "$HERE/launch.sh" > "$STAGED_APP/Contents/Resources/launcher-path"
plutil -replace NSMicrophoneUsageDescription -string "Sawti measures audio locally; optional voice recordings are processed locally." "$STAGED_APP/Contents/Info.plist"
plutil -replace NSAppleEventsUsageDescription -string "Sawti sends Record and Stop keystrokes only after a specific operator approval." "$STAGED_APP/Contents/Info.plist"
plutil -replace CFBundleIdentifier -string "com.imi.sawti" "$STAGED_APP/Contents/Info.plist"
plutil -replace CFBundleName -string "Sawti" "$STAGED_APP/Contents/Info.plist"
codesign --force --deep --sign - "$STAGED_APP" >/dev/null 2>&1 || fail "Could not sign the local launcher."
if [[ -e "$APP" ]]; then
  mv "$APP" "$APPDIR/Sawti-backup-$(date +%Y%m%d-%H%M%S)-$RANDOM.app" || fail "Could not preserve the previous Sawti app."
fi
mv "$STAGED_APP" "$APP" || fail "Could not activate the new launcher."
if [[ ! -e "$HOME/Desktop/Sawti.app" && ! -L "$HOME/Desktop/Sawti.app" ]]; then
  ln -s "$APP" "$HOME/Desktop/Sawti.app"
else
  warn "Existing Desktop/Sawti.app retained. The installed app is in ~/Applications."
fi

# Standalone uninstaller: native dialogs and a stdlib-only engine bundled with
# the app, so it can still run when Sawti packages or source files are broken.
UNINSTALL_APP="$APPDIR/Uninstall Sawti.app"
if [[ -e "$UNINSTALL_APP" ]]; then
  EXISTING_ID=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$UNINSTALL_APP/Contents/Info.plist" 2>/dev/null || true)
  [[ "$EXISTING_ID" == "com.imi.sawti.uninstall" ]] || fail "An unrelated Uninstall Sawti.app exists; preserve it before installing."
  mv "$UNINSTALL_APP" "$APPDIR/Sawti-backup-uninstaller-$(date +%Y%m%d-%H%M%S)-$RANDOM.app" || fail "Could not preserve the previous uninstaller."
fi
osacompile -o "$UNINSTALL_APP" \
  -e 'set resourcePath to (POSIX path of (path to me)) & "Contents/Resources/"' \
  -e 'set sourceRoot to do shell script "/bin/cat " & quoted form of (resourcePath & "source-root")' \
  -e 'do shell script "/usr/bin/osascript -l JavaScript " & quoted form of (resourcePath & "uninstall-ui.js") & " " & quoted form of sourceRoot & " " & quoted form of (resourcePath & "uninstall.py")' \
  || fail "Could not create the standalone uninstaller."
mkdir -p "$UNINSTALL_APP/Contents/Resources"
cp "$HERE/helpers/uninstall.py" "$HERE/helpers/uninstall-ui.js" "$UNINSTALL_APP/Contents/Resources/" || fail "Could not copy uninstaller resources."
print -r -- "$HERE" > "$UNINSTALL_APP/Contents/Resources/source-root"
plutil -replace CFBundleIdentifier -string "com.imi.sawti.uninstall" "$UNINSTALL_APP/Contents/Info.plist"
plutil -replace CFBundleName -string "Uninstall Sawti" "$UNINSTALL_APP/Contents/Info.plist"
codesign --force --deep --sign - "$UNINSTALL_APP" >/dev/null 2>&1 || fail "Could not sign the local uninstaller."
if [[ ! -e "$HOME/Desktop/Uninstall Sawti.app" && ! -L "$HOME/Desktop/Uninstall Sawti.app" ]]; then
  ln -s "$UNINSTALL_APP" "$HOME/Desktop/Uninstall Sawti.app"
fi
"$VENV/bin/python" -I "$HERE/helpers/uninstall.py" register --source "$HERE" --home "$HOME" >/dev/null \
  || fail "Could not save the uninstall inventory."
ok "Standalone uninstaller and component inventory ready"
chmod +x "$HERE"/*.command "$HERE/launch.sh"

print "\n────────────────────────────────────────────"
print " ✅ Sawti is installed."
print "    Open it from the Desktop (Sawti) or ~/Applications."
print "    For training without hardware: SIMULATE_SAWTI.command"
print "    The first time Sawti meters audio, macOS asks for microphone access — click Allow."
print "────────────────────────────────────────────"
"$HERE/launch.sh"
read "?Press Return to close this window."
