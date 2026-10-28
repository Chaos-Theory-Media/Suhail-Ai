# QA addendum for Sawti 3.0.1

The notes below describe the original 3.0 design and are superseded where they conflict with [the QA report](audit/qa/REPORT.md). Real hardware, Swift helper compilation, Gatekeeper behaviour and audio continuity have not been tested here. Read-only inspection and simulation work on Linux.

- `sawti/safety.py` provides single-use, expiring action approvals tied to current device/mode/session state. A fresh idle attestation is required for audio changes; Stop requires explicit interruption approval. LIVE never proves external recording state.
- Audio-impact actions are excluded from bulk fixes, learned automation and power-on. Simulation starts no real Ollama/caffeinate processes. Real inline output is blocked pending qualification.
- Presenter speech (3.1.0) is an opt-in additive output, separate from the blocked inline leveler. It uses exact-device CoreAudio mapping to the confirmed USB Playback 3–4 headset pair, file-only native synthesis and per-session operator isolation tests. See [private voice qualification](audit/presenter-voice/README.md); production audio must remain independent of this output.
- Browser capture checks OFF before/after permissions, releases tracks on OFF/page exit, and discards cancelled samples. Other tabs synchronise power on their next status poll; this is not a hardware mute.
- Own processes use process-group shutdown and stale-PID identity checks. An occupied AI port is refused; only owned, ready local Qwen3 is contacted.
- New exports get unique directories; original recordings and previous exports are preserved. Post jobs may finish in the background after OFF; Quit terminates the application. In-flight speech/model results are discarded after power changes. OFF is a lifecycle control, not a guarantee that every Python computation is instantly preempted.
- Migration backs up the incompatible 2.2 event database and preserves presenter rows. Backups and legacy event tables may contain old private prompts; retain/review them locally, never commit them.
- `requirements-cloud.lock` pins the tested Linux/CI dependencies. macOS dependency locking and installer acceptance remain outstanding.
- Installer retains quarantine metadata, verifies uv checksums, checks Ollama signature/Gatekeeper, and preloads optional voice models. These macOS operations were statically reviewed, not executed here.

3.2.0 adds the optional M1 Ultra model profile in `sawti/models.py`, installer-only downloads in `helpers/install_models.py`, and an isolated offline specialist process in `helpers/model_worker.py`. Qwen3 4B remains supported; the recommended exact tag is `qwen3:30b-a3b-q4_K_M`. Native MLX speech, BGE-M3 dense retrieval and BGE reranking use a separate pinned Python 3.12 environment. Enhanced tasks are serial and blocked during Live pending Mac performance qualification. `sawti/knowledge.py` stores operator-imported version-labelled reference passages; reference answers expose no action tools/buttons. No wake listener, autonomous recording or verified Audition state is added. See [model compatibility and acceptance](audit/models/README.md).

3.2.1 adds `sawti/template_catalog.py`: explicit bounded .sesx discovery with volatile IDs bound to power/mode/microphone plan. Search and inspection perform no application, transport or routing writes. Adoption uses an inspected content digest, an immutable byte snapshot, an atomic private template replacement and explicit idle/empty-template attestations. Known recorded content is rejected; old Sawti preparation/checks/private-speech qualification are invalidated. Original sessions and media remain in place. Actual Mac search permissions, file layouts and input mappings remain unqualified. See [template picker](audit/template-picker/README.md).

Original design notes (historical claims require the qualifications above):

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
