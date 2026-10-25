# Sawti 3.0: technical notes (IT / DevOps)

## Layout
```
app.py                    entry point (python app.py [--simulate]); serves http://127.0.0.1:8765
launch.sh                 starts Sawti detached (nohup) if not running, then opens the browser
INSTALL_SAWTI.command     installer / repair (idempotent)     UNINSTALL_SAWTI.command
SIMULATE_SAWTI.command    training mode on :8766 with separate data
helpers/sawti-audio.swift CoreAudio helper, compiled on the Mac at install time
sawti/
  studio.py               orchestrator: agents, actions registry, live guard, scheduler, notices
  agents/devices.py       Scarlett, BlackHole, aggregate "Sawti Show Input", multi-output "Sawti Zoom Speaker"
  agents/mac.py           disk at recording folder, keep-awake, TCC permission detection, apps, CPU/memory
  agents/audition.py      template adoption (.sesx parse), dated sessions, open, Record/Stop keystrokes
  agents/levels.py        live coaching thresholds
  agents/pretest.py       guided sound check state machine
  agents/post.py          QC, auto-mix, mastering jobs
  agents/learning.py      schedule prediction, naming, auto-fix promotion, gain habits, auto-prep tick
  agents/chat.py          bilingual intent router + Ollama tool calling (think:false)
  dsp.py                  BS.1770-4 loudness, true peak (4x), limiter, mastering, auto-mix, live leveler
  meter.py                live metering (PortAudio), digital-silence detection, simulator
  coreaudio.py            RealAudio (helper + sounddevice) / SimAudio
  lifecycle.py            private Ollama + caffeinate, pid files, signal handlers
  server.py               Flask API + security
  store.py                SQLite (settings, events, presenters, observations), 180-day retention
profiles/                 local.json, zoom.json (channels resolved automatically)
static/                   index.html, app.css, app.js (no inline script; strict CSP)
tests/                    36 unit/integration tests (simulation mode + real-Mac code path with fakes)
```

## Data locations
`~/Library/Application Support/Sawti/`: `venv/`, `runtime/` (uv, Python, Ollama.app), `models/` (Qwen),
`bin/sawti-audio`, `sawti.sqlite3`, `templates/`, `run/` (logs, pid files), `simulation/` (training data).
Recordings go to `~/Music/Sawti Recordings/<year>/<session>/` by default (configurable).

## Network
Installer only: GitHub (uv, Ollama release), the Python package index, astral/python-build-standalone, and the
Ollama model registry. At runtime Sawti makes no internet connections: the API listens on 127.0.0.1:8765
and the private Ollama on 127.0.0.1:11439.

## Security model
* Binds to loopback only. Requests must carry `Host: 127.0.0.1:8765` or `localhost:8765` (DNS-rebinding defence).
* Every non-GET request needs the `X-Sawti: 1` header, and any `Origin` must be local. A cross-site page cannot add the
  header without a CORS pre-flight, which Sawti does not answer.
* CSP `script-src 'self'`, no inline handlers, and the UI renders data with textContent only.
* The helper only destroys devices whose UID starts with `com.imi.sawti.`.
* Chat text is not logged. Only the detected intent is stored. Events expire after 180 days.
* Voice signatures (optional) are stored unencrypted in SQLite. Use FileVault and get consent.

## Audio facts used
* Scarlett 18i8 3rd gen exposes 18 inputs at 48 kHz. In "Sawti Show Input" the sub-devices are ordered
  [Scarlett, BlackHole 2ch], so the Zoom guests arrive on inputs 19–20. Sawti computes this from the
  aggregate's sub-device list, so a different interface also works.
* Drift correction is enabled on BlackHole inside the aggregate. The Scarlett is the clock.
* Episode standard: −16 LUFS integrated, −1 dBTP (true peak, 4x oversampled). Mono sources are delivered as
  dual-mono stereo.
* Live coaching window for raw tracks: speech −26 … −14 LUFS short-term (target −20), peaks < −6 dBFS,
  clip ≥ −0.5 dBFS.

## Tests
```
~/Library/Application\ Support/Sawti/venv/bin/python -m unittest discover -s tests -v
```
Verified in a Linux container on Python 3.12 and 3.13 (all 36 pass). Loudness matches pyloudnorm to 0.001 LU
and reads the EBU 1 kHz −23 dBFS reference as −23.0 LUFS.

## First-run validation on the studio Mac (not possible in the build container)
1. `"$HOME/Library/Application Support/Sawti/bin/sawti-audio" list` prints JSON that includes the Scarlett.
2. Zoom Show › Fix everything I can → "Sawti Show Input" and "Sawti Zoom Speaker" appear in Audio MIDI Setup.
3. Start meters: each mic moves only its own meter; Zoom guest audio shows on "Zoom guests".
4. Accessibility granted → Record and Stop work. Sawti confirms new audio within 6 seconds.
5. Test the inline leveler only on a non-live session, recording from BlackHole 16ch.
