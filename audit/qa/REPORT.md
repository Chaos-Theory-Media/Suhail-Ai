# Sawti 3.0.1 QA/QC report

## Outcome and scope

Reviewed all 46 files in `Sawti_3_0_Mac.zip`, including Python agents, browser UI, Swift helper, profiles, tests, installer/launcher/uninstaller and documentation. Preserved the upload at Git tag **`sawti-3.0-upload`** and the prior source/audit at **`sawti-2.2-baseline`**. `audit/3.0-upload-manifest.json` records the archive and original file hashes. No obvious credentials or private recordings were found in the targeted import review. No attached document was treated as authority to execute installer commands.

This is a code audit, corrective implementation and Linux/simulation qualification. It is **not Mac Studio, hardware, installer or production qualification**. No existing audio routing, production session, microphone or recording was changed in this work.

The uploaded 3.0 passed its 36 supplied tests on Python 3.12 before changes. This did not establish production safety: those tests permitted automatic sample-rate changes and did not exercise the browser OFF or database upgrade defects. Tests that encoded unsafe behaviour were changed to require individual operator approvals; the original tests remain available in the upload tag. No assertions were disabled or marked expected-failure.

## Checks and evidence

See [`results/commands.json`](results/commands.json) and adjacent logs for actual commands and exit codes.

| Check | Result | What it establishes |
| --- | --- | --- |
| Supplied upload before edits | 36 Python tests passed | Baseline on this Linux environment, including simulated DSP and fake Mac adapters |
| Revised Python suite | 71 tests, all passed | Existing behaviours plus approvals, concurrency, migration, export preservation, validation, uncertainty and consent regressions |
| Actual browser script in a Node VM | 7 tests, all passed | OFF/pending permission cleanup, stale response handling, simulator isolation and recorder-error cleanup with DOM/media substitutes |
| Live HTTP workflow | 25 requests passed | Real server/HTTP security boundary, OFF gate, Arabic rule chat, one-use action approvals, simulated Zoom mapping, live guard and shutdown |
| Independent FFmpeg measurement | Passed within 0.3 LU/dB on the tested synthetic programme | A second implementation agrees on this fixture; not exhaustive BS.1770/true-peak conformance |
| Core dependency consistency | `pip check` passed | No declared conflicts in the installed Linux environment |
| zsh installer/launcher/uninstaller syntax | Passed | Syntax only; no macOS installer step was executed |

Python: 3.12.14. Linux dependencies are pinned in `requirements-cloud.lock`. The independent FFmpeg test ran here; it is explicitly skipped if FFmpeg is unavailable elsewhere. No skips or expected failures occurred in this recorded Python run. An Ubuntu CI workflow was added to run these checks; a GitHub-hosted CI result is not claimed until that workflow executes.

Reproduce from the checkout root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cloud.lock
.venv/bin/python -m unittest discover -s tests -v
node --test tests/browser_safety.cjs
.venv/bin/python tests/http_smoke.py
zsh -n INSTALL_SAWTI.command launch.sh START_SAWTI.command SIMULATE_SAWTI.command UNINSTALL_SAWTI.command
```

Cloud simulation uses `SAWTI_DATA` and `SAWTI_INSTALL` pointing to isolated writable directories. It does not modify HOME or require the old 2.2 import patch. `audit/v2.2/` is historical evidence, not the current test runner.

## Confirmed issues corrected

| Priority | Uploaded behaviour | Correction / evidence |
| --- | --- | --- |
| P0 | Device/rate/rebuild actions marked safe for bulk fixes, learning and power-on | Audio-impact actions are ineligible for automation, including legacy saved approvals. Tests verify rates and device membership remain unchanged |
| P0 | Record/Stop only had browser confirmation; direct API bypassed it | Server-issued 30-second, one-use action review bound to device/mode/session/live state, explicit operator confirmation and idle attestation. Stop explicitly authorises interruption. No approval can be used for another action or replayed |
| P0 | Sawti LIVE flag treated as recording safety boundary | Actual recording state is always `unknown`; UI explains the distinction. Device changes require the operator to check all apps are idle even outside LIVE. LIVE still blocks device changes |
| P0 | Capture start admitted before OFF could finish after it | Audio operations and OFF share an operation lock; waiting mutation requests detect a changed power epoch. OFF stops admitted capture before returning and invalidates approvals |
| P0 | Browser voice capture ignored OFF and late permission grants | Checks before/after permission, cancellation generation, track release on OFF/page exit, bounded recording, no cancelled uploads, status synchronization and stale-response rejection |
| P0 | Inline leveler makes production recording depend on Sawti staying on | Real duplex output is blocked pending Mac qualification; DSP and simulation are retained. Capture-only monitoring and offline processing remain available |
| P0 | Post names could escape their directory; existing outputs/source aliases could be overwritten | Validate output basenames, allocate a unique export directory per job, reject direct DSP source/symlink/hardlink output aliases. Tests preserve source bytes and a prior export |
| P1 | 2.2 `events(date,category,message)` schema incompatible with 3.0 `events(ts,kind,data)` | Backup before migration, preserve presenters/embeddings and legacy event archive, initialise new event table. Unknown schemas fail conservatively. Backup remains local and private |
| P1 | Stale process cleanup relied on a PID and command substring | Require saved process birth time, complete command and user identity; only an owned session/process group is signalled. Marker-only legacy metadata cannot kill a process. Occupied AI ports are refused rather than reused |
| P1 | Startup/OFF race could publish stale AI readiness; leaked log handle | Coordinate lifecycle readiness with owned child identity/on-state, close parent log descriptors, target own process group on normal shutdown, request exact local Qwen3 with cloud mode disabled |
| P1 | Simulation could start real AI/awake services and expose real microphone functions | Disable real managed services and voice processing in simulation; separate training data remains supported |
| P1 | Digital silence labelled a proven macOS permission block | Report source/routing/permission as possible causes; never infer analogue gain or 48V from silence |
| P1 | Skipped pre-test steps counted as ready; inactive recording check could crash | Require every step to pass for readiness, validate navigation, abort sound check if capture fails, block stale observations and avoid certifying recording paths from file count |
| P1 | Talkback advice claimed it was never recorded and the pre-test proved isolation | Treat profile wiring as expected, not measured fact. Explain the distinction between monitored input observations, Audition tracks and Zoom privacy. Audio changes invalidate prior manual confirmations |
| P1 | Wrong BlackHole variant/name-only device fallback and missing aggregate members could yield wrong channels | Require the requested channel variant and UID; reject unknown subdevice offsets and ambiguous PortAudio names. Refuse capture at unverified/guessed default rates, distinguish helper observations, and verify rate-change readback |
| P1 | Meter stream startup/stop failures leaked resources; stalled samples lacked a health finding | Close allocated streams even on start/stop errors; add stale-data findings and suppress coaching from stale measurements |
| P1 | Settings coercion accepted `"false"` as true, malformed maps crashed, partial invalid updates persisted | Strict input types, bounded names, atomic settings commit, live audio-setting guard and approved local model restriction |
| P1 | Arabic prompt routing worked, but built-in responses were English | Add Arabic rule responses and preserve uncertainty. Technical findings/device names can still be English; comprehensive localization remains pending |
| P1 | Installer removed quarantine recursively and ran unverified uv download | Retain quarantine metadata, verify official uv checksums before use, require Ollama code-signature and Gatekeeper checks, preserve previous launcher, stage new launcher and handle signals without continuing setup |
| P1 | Optional STT could download on first daily use | Preload optional speech/embedding models during installer; STT runtime requires local cached files. Actual Mac downloads/offline behaviour remain untested |
| P1 | Uninstaller could destroy devices used by other applications and delete uninspected media | Retain all audio devices, refuse while service ports are occupied, require idle confirmation, preserve data if media/session files exist or traversal cannot be completed |
| P2 | Oversized event JSON was truncated into invalid JSON | Store structured JSON intact; regression test confirms later learning reads it |

The browser confirmation is an explicit operator statement, **not an independent sensor of idle recording**. A local process running as the same user can invoke APIs; this is not a hardened multi-user authentication system. The LLM and voice recognition cannot grant approvals: their tools remain read-only observations or proposed action buttons, not direct mutation execution.

## What is implemented, simulated and still missing

| Area | Implementation present | Remaining qualification / gap |
| --- | --- | --- |
| Scarlett / CoreAudio | Swift helper source, read-only enumeration, nominal-rate query, approved aggregate/rate actions, input capture | Helper not compiled here; 18i8 generation, channel map, clock/drift settings, actual rate readback and device-loss behaviour need the named Mac/hardware. Broad Scarlett name matching is not generation verification |
| Audition | `.sesx` template parsing/copying, dated session folders, approved open/Record/Stop keystrokes, recent-file observations | No supported transport/session-state integration demonstrated. Keystrokes depend on focus and shortcut configuration. Template relative media references and real record destination need manual verification |
| Zoom / BlackHole | Simulated 18+2 input layout, approved aggregate creation and device findings | No proof of the actual Mac aggregate ordering, output topology or Zoom-selected devices. Remote participant, echo and talkback privacy tests remain required |
| Monitoring / pre-test | Actual NumPy/SciPy analysis code, simulated input generator, freshness/level checks, manual findings, guided steps | Input metrics do not prove hardware knobs, 48V, routing, consent or track identity. Quiet speech/bleed thresholds need studio calibration |
| Post-production | Real file QC, offline automix/master DSP, unique exports and asynchronous jobs | Synthetic tests are not listening evaluation or full loudness conformance. Long-show memory/CPU, channel alignment, stereo preservation and a representative professional corpus need qualification. Do not process a growing production take |
| Agent/recovery layer | Explicit registry of deterministic specialist checks/actions, approval boundary, learning/scheduling, optional LLM proposals | Not an autonomous self-healing system. No verified transactional CoreAudio repair/rollback or external recording-state sensor. Recovery after a partially failed approved mutation requires operator inspection |
| Local Qwen3 | Owned loopback Ollama API path and exact model name check | Actual Qwen weights/inference, approved model digest, model resource budget and network-denied operation were not tested. Runtime talks only to the owned ready service; installation still requires network |
| English / Arabic | Text input, rule routing/replies, optional Whisper and embeddings code | No TTS/spoken responses. Real Arabic/English audio, Safari MIME support, accents, long utterances and full RTL/accessibility are untested. Some technical detail strings remain English |
| Presenter recognition | Consent-required local rows/embeddings, similarity/margin code and deletion | No real embedding quality/replay tests, calibrated thresholds or encryption at rest beyond OS/account controls. Deletion removes active rows, not forensic SQLite remnants or pre-upgrade backups |
| Installer / app | zsh assisted installer, private runtime/model locations, AppleScript launcher, GUI power/quit, safer trust/upgrade/uninstall behaviour | No Mac execution, signed/notarised distribution, stable TCC identity, macOS dependency lock or pinned external runtime releases. Native guided installer and clean-Mac acceptance still needed |
| ON/OFF | Default OFF, coordinated capture/owned-service shutdown, no routing changes on activation, browser capture cancellation | Not a hardware mute. Other tabs release voice capture on their next status sync. Long offline jobs may finish after OFF; bounded speech work may finish internally but its result is discarded. SIGKILL, descendant processes and audio continuity require real-Mac qualification |

## Source map

- `sawti/studio.py`, `safety.py`, `lifecycle.py`, `server.py`: orchestration, approvals, services and HTTP boundary.
- `sawti/coreaudio.py`, `helpers/sawti-audio.swift`, `profiles/*.json`: real/simulated adapters and expected wiring.
- `sawti/meter.py`, `dsp.py`, `agents/levels.py`, `agents/pretest.py`: signal analysis, DSP and guided observations.
- `agents/devices.py`, `mac.py`, `audition.py`: deterministic diagnostics and explicitly approved operations.
- `agents/learning.py`, `store.py`: local metadata, schedules, settings, consent and migration.
- `agents/chat.py`, `voice.py`: rule/LLM advice and optional local voice code; no TTS.
- `agents/post.py`: background jobs and fresh export directories.
- `static/*`: local browser UI; no external script/CDN dependency.
- `.command` scripts, `launch.sh`, `app.py`: installation and runtime entry points.
- `tests/*`, `.github/workflows/qa.yml`: automated verification; fake adapters are explicitly identified.

## Next release gates on the Mac Studio

1. In an approved non-production session, record exact macOS/app/driver/firmware/model versions and read-only routing/device snapshots. Verify the Scarlett **18i8 3rd Generation** physically and identify its supported Focusrite software; the source's Focusrite Control 2 assumption is unverified.
2. Compile/run the Swift helper. Validate aggregate order, master clock/drift correction, channel indices and multi-output behaviour. Individually authorise any mutation after checking all recording is idle. Never apply setup changes to an existing production take.
3. Qualify Audition focus/shortcuts, template media references, track arm/input mapping, actual recorded files, Zoom guest return, mix-minus and private talkback with a consenting remote participant.
4. During a disposable multitrack recording, test Sawti ON/OFF/Quit/signals, permission denial and device disconnection. Inspect capture continuity and unchanged routing. **Do not enable inline output** until a separate design/qualification proves an acceptable production-safe lifecycle.
5. Preload approved local models, deny network, run real Qwen inference and a fixed bilingual speech corpus. Calibrate unknown-speaker rejection with voluntary enrolment. Specify TTS, retention, encryption and deletion requirements before claiming complete bilingual voice support.
6. Test a fresh supported Mac installation, Gatekeeper/TCC prompts, unavailable network, checksum failure, disk exhaustion, upgrade/uninstall, long-session resource load and daily operation without Terminal. Produce an operator-reviewed acceptance record before production deployment.

These are outstanding acceptance gates, not passing tests or a production-readiness claim.
