# Sawti 2.2 technical audit

Audit date: 25 October 2026. Source baseline: `8818f84`.

## Conclusion

The supplied installer ZIP contains a small local Flask application, not just an installer. Its useful baseline is a read-only diagnostic prototype with manual input capture, deterministic advice, optional local-model chat, and optional voice functions. It is not a production-qualified macOS studio controller. Preserve these components and close the safety gaps before enabling any routing or recording control.

The source was imported without changing any of its 22 original files. Ten generated Python bytecode files were excluded; command launchers were marked executable. A new `.gitignore` excludes environments, runtime databases and local configuration. The source and archive hashes are recorded in `source-manifest.json`. The import review found no obvious credentials or private recordings in the supplied files; this was a targeted review, not a guarantee against every form of embedded sensitive data.

All code-bearing files, profiles, original tests, installer scripts and documentation were inspected. The PNG is a UI reference asset, not evidence of working hardware. New files under `audit/` supply evidence, checks and a cloud-only inspection launcher; application logic and existing tests are unchanged.

## Validation actually performed

Host: Linux, Python 3.12.14. Installed the four core requirements in `.venv`; `pip check` passed. Original dependency declarations use version ranges, with no supplied lockfile. Voice packages and model weights were not installed or exercised.

| Check | Result | Meaning |
| --- | --- | --- |
| Original tests, isolated user data | 12 passed | Profile matching, simple diagnostics, lifecycle basics and metadata patterns work under these tests |
| Added backend audit checks | 18 executed: 10 passed, 8 failed | Confirmed safety/integration gaps listed below; failures remain visible |
| Original UI script in Node VM | 2 executed, both failed | Reproduces browser capture starting while OFF and after a pending permission grant crosses OFF |
| Live local HTTP smoke | 10 requests passed | UI/PNG, default OFF, blocked diagnostic request, ON without capture, rule chat, preflight, OFF and blocking verified |
| Core dependency consistency | Passed | Installed dependencies have no declared conflicts |
| Mac Studio / Scarlett / Audition / Zoom / BlackHole | Not run | No Mac or hardware access is attached |
| Real Qwen3, speech transcription, speaker embeddings and offline operation | Not run | Code paths exist; neither models nor end-to-end behaviour are verified |

The first unmodified test command hit the cloud sandbox's read-only home directory during `sawti.py` import. The audit runner isolates `Path.home()` during import into a temporary directory; the original 12 tests then pass. This is a cloud setup adaptation, not a fix to application storage configuration. The cloud launcher likewise isolates data under `/workspace/.sawti-cloud/data-home`. No environment-wide HOME variable is changed.

Detailed command outcomes and logs are in `results/`. Run from the repository root:

```sh
.venv/bin/python audit/run_checks.py original
.venv/bin/python audit/run_checks.py audit
node --test audit/checks/browser_safety.cjs
.venv/bin/python -m pip check
```

The second and third commands currently exit nonzero. They deliberately assert required behaviour against the unchanged baseline, rather than hiding defects as expected failures. Hardware/process/model substitutes make these audit tests deterministic; they do not validate real hardware, macOS permissions or browser microphone implementations.

## Capability evidence

| Requirement | Genuinely implemented | Simulated, assumed, missing or unverified |
| --- | --- | --- |
| Scarlett 18i8 3rd Gen | `studio/engine.py` enumerates PortAudio devices and can open an input-only stream; NumPy calculates peak/RMS dBFS | Real Mac capture untested. Name/channel-count matching does not establish generation, stable identity, actual physical channel map, gain or 48V. No Focusrite control API |
| Audition multitrack | Process-name detection and manual check instructions | No session inspection, track arming, transport control, record-state detection, recorded-file validation or heartbeat. Running process is not recording readiness |
| Zoom / BlackHole | Device/process presence checks, read-only expected profile and manual mix-minus guidance | No Zoom selection inspection or topology verification. Default Zoom profile captures only four assumed channels; guest return channels are not configured |
| Podcast / Zoom modes | Distinct UI tabs, profile files and mode-specific checks | Tabs do not apply or validate physical routing. Switching the tab does not restart an active stream, so displayed mode can disagree with capture/lifecycle mode |
| Qwen3 through Ollama | Real HTTP `/api/tags` and `/api/chat` paths on loopback port 11439; optional child service; assisted model download | No real inference tested. Family-only tag check accepts the wrong model size. Startup does not wait for readiness or verify port ownership. Local server address alone does not enforce offline-only model execution |
| English / Arabic text | Unicode text input, Arabic keyword triggers and language instruction for optional LLM | Rule replies are English even for Arabic triggers. No comprehensive bilingual/RTL behaviour validation |
| English / Arabic voice | Browser MediaRecorder upload, ffmpeg conversion, optional faster-whisper with `en`/`ar` support | No actual speech tested. No TTS/spoken response implementation. No wake word. STT model constructed per request; optional dependencies/models absent from assisted installer |
| Presenter enrolment | Consent-required registration, stored local embeddings, cosine matching with threshold/margin, delete endpoint; recognition always returns `verified=False` | Embedding execution untested, thresholds uncalibrated, no replay defence or authentication. SQLite data is not separately encrypted. Delete removes rows, not all name-bearing event logs or guaranteed residual bytes |
| Monitoring / preflight | Input metrics, device checks, app-disk free space, manual checks, simple rule advice | Agent badges are labels over deterministic checks, not independent autonomous agents. More detailed health function is imported but never used by endpoints. Disk check targets application disk, not approved recording destination |
| Fault diagnosis / supervised recovery | Suggestions and a standalone read-only alert function | No recovery executor, action broker, scoped approvals, recording guard, state machine or verified post-action outcomes |
| Safe ON/OFF | Starts OFF; blocks backend diagnostic endpoints while OFF; ON does not start meters; stop targets a stored child handle and own monitor | Browser capture bypasses OFF. Requests admitted before OFF can finish after it. No request cancellation, exit cleanup, or full descendant shutdown verification. Production non-interference unverified |
| Installer / daily GUI use | Interactive `.command` scripts create venv, download private Ollama app/model storage and launch browser/server | Terminal remains required for setup and full exit. No signed/notarised app, guided native permissions, bundled Python, voice installation, update/uninstall or integrity/signature check of downloaded Ollama app |

There is no random fabricated telemetry generator in the reviewed source. Empty UI meters use hardcoded channel labels and -120 dBFS placeholders; they are not measured silence. Profile channel labels, expected routing and the reference image are descriptions, not observed studio configuration. Original tests use synthetic data/stubs and therefore prove only the assertions they execute.

## Prioritised findings

### P0 — resolve before claiming safe OFF or enabling live-production use

1. **Browser capture is not gated by power.** `static/index.html` calls `getUserMedia` in `beginAudio` without checking power. `toggleVoice` remains active while OFF. A permission request begun while ON can resolve after OFF and start a new recorder. Both cases are reproduced by `browser_safety.cjs`. The backend gate cannot release browser microphone tracks.
2. **OFF races with admitted operations.** `app.py` checks power once in `before_request`; meter start is not coordinated with `Lifecycle.stop`. An admitted request can open capture after stop returns. A deterministic concurrent-request test reproduces this. Speech/model work already in flight also has no cancellation contract. Add operation generations/cancellation and a shared lifecycle boundary; revalidate immediately before opening resources.
3. **Power endpoint accepts cross-origin form posts.** A request carrying a foreign Origin can turn power OFF. There is no origin, CSRF or session-bound operator control on mutation routes. Loopback binding alone is insufficient. The test proves server acceptance, not an exploit on every browser; private-network browser policies can differ. Apply trusted Host/Origin checks and a local session-bound anti-CSRF mechanism before relying on operator-only mutation.
4. **No recording-state safety boundary exists.** There is no recording/idle/unknown state or common action-authorisation broker. This baseline does not implement routing/recording mutations, which limits current exposure; never add them without fail-closed recording guards and explicit scoped approvals. Capturing an audio device is itself something to qualify for non-interference on the actual Mac.

### P1 — integration gaps and misleading readiness

5. **Stale metering is shown as pass.** `agent_status` checks only `running`; it ignores `last_audio_age` and capture errors. The detailed `studio.health.audit` detects stalled capture but is not called by `/api/agents`. Both defects are reproduced. The UI drops preflight `detail` fields and does not regularly refresh agent/preflight status, obscuring necessary manual qualifications.
6. **Zoom guest capture is not configured.** `profiles/zoom.json` selects an Aggregate by generic name and requires only four inputs. It has no guest return sources. The UI's six placeholder meters do not fix the real four-channel capture. Map actual device identity and channels with an operator; do not guess or change Audio MIDI Setup during a recording.
7. **Model readiness is overstated.** `ollama_status` matches only the family before `:`, so `qwen3:0.6b` satisfies a `qwen3:4b` requirement. Lifecycle sets ON and reports startup immediately after `Popen` without probing readiness. An unrelated listener on 11439 can be contacted after a failed child startup. Require exact model identity, ownership and readiness, preserve startup errors, and verify a real inference.
8. **Shutdown/crash ownership needs qualification.** No shutdown hook invokes `lifecycle.stop` when Flask exits. Child services use a new session and only the direct handle is terminated; runner descendants need verification. Do not replace this with kill-by-name/port or terminate external Ollama. Protect against port conflicts and track only owned processes/resources.
9. **Installer reproducibility/trust incomplete.** HTTPS verification is retained, but Ollama's unversioned ZIP is executed without an explicit publisher-signature/checksum verification step. Python dependencies float within ranges. Download success and `ollama list` are not a real Qwen inference check. Verify Apple signing/notarisation and a trusted pinned release, lock platform dependencies, verify model identity and pre-load optional voice models. Do not disable TLS/signature checks.
10. **Fully offline operation is a goal, not established.** STT loads by model name and may download on first use. Voice dependencies are optional. The local Ollama endpoint is not explicitly constrained against cloud-enabled models. Enforce approved local model choices/offline runtime and test with egress denied after installation. Older README model-install guidance uses default Ollama storage, whereas lifecycle now forces private Sawti storage; only the 2.2 installer populates that path.
11. **Bilingual voice/text incomplete.** Arabic rule triggers return English; there is no TTS. Verify STT/TTS on supported Apple Silicon hardware, Safari/browser recording MIME types, Arabic text direction and a representative bilingual corpus before claiming voice support.

### P2 — hardening and usability

12. **Presenter lifecycle needs privacy controls.** Opt-in and row deletion are implemented, but names also enter event logs; there is no retention policy, encryption layer or complete privacy erasure path. Four seconds after preprocessing is the only sample-length validation. Do not use recognition for permissions. Test unknown speakers, similar voices, replay, revocation and local-only processing.
13. **Local learning is metadata aggregation, not adaptive control.** It scans filenames/paths/timestamps with consent and never reads recording contents. Disabling it does not delete prior observations. Traversal is unbounded before keeping the newest 3,000 files; stale observations persist. UI scan output shows only count/message; learned recommendations are not injected into chat. Add bounds, explicit retention/deletion and accurate UI wording.
14. **Runtime robustness remains limited.** Meter stop suppresses errors and can skip close if stop raises. A failed stream start is not reliably cleaned up; callback/lifecycle concurrency is untested. Model loads, conversion timeouts, malformed requests, stream errors and service crashes need explicit failure handling. Presenter lists are not loaded on power-on; version labels mix 2.0/2.1/2.2; the launcher opens the browser before readiness.
15. **Hardware/vendor assumptions require confirmation.** A substring `Scarlett` plus input count can pass a check labelled 18i8. Documentation refers to Focusrite Control 2, but the appropriate official control software for the exact 3rd Generation unit and target macOS must be verified with Focusrite. No vendor compatibility is established by this audit.

## File-by-file inventory

| Original files | Implemented responsibility / audit boundary |
| --- | --- |
| `app.py` | Flask routes, 5 MiB upload limit, one-time OFF admission check; no persistent operator session or recovery endpoint |
| `sawti.py` | SQLite presenters/events, ffmpeg conversion, optional STT/embeddings, loopback Ollama HTTP, process badges and rule/chat responses |
| `studio/engine.py` | Profiles, device selection, input-only stream, peak/RMS snapshots and manual preflight |
| `studio/lifecycle.py` | On/off flag, own monitor stop, optional dedicated Ollama child; no startup handshake or coordinated request cancellation |
| `studio/health.py` | More detailed read-only alerts, including stalled capture; disconnected from API/UI |
| `studio/learning.py` | Opt-in metadata scanner and naming-frequency summaries; app-relative SQLite storage |
| `studio/__init__.py` | Empty package marker |
| `static/index.html` | Complete browser UI, polling, voice acquisition, enrolment and local learning controls; no TTS |
| `static/reference_design.png` | Reference image served by UI; no executable integration |
| `profiles/local.json`, `profiles/zoom.json` | Assumed expected-state descriptors; neither applies routing |
| `INSTALL_SAWTI.command` | zsh assisted Apple Silicon installer, interactive consent, private model storage and temporary service |
| `START_SAWTI.command`, `start.command` | Terminal-based launchers; older launcher also installs dependencies on each invocation |
| `requirements.txt`, `requirements-voice.txt` | Core and optional voice dependency ranges; no locks or bundled models |
| `tests/test_engine.py` | Three profile/device-selection checks |
| `tests/test_power.py` | Three lifecycle checks; no concurrency or browser coverage |
| `tests/test_learning_health.py` | Three naming/health checks using supplied observations |
| `tests/test_sawti.py` | Three rule/device-status checks; no real speech/model integration |
| `README.md`, `README_INSTALL_FIRST.txt` | Prototype limitations and mixed-version setup guidance; claims require validation above |

## Mac Studio qualification gate

This audit does not validate the Mac. Use an operator-approved test session, never an existing production recording. Begin with read-only observations. Record macOS version, exact Scarlett generation/firmware, installed vendor software, Audition/Zoom/BlackHole versions, aggregate channel order and model digests. Preserve the current routing/presets as evidence without applying changes.

Required checks before production readiness:

- Start/stop/repeat/crash Sawti while recording a disposable multitrack session. Independently inspect captured files and continuity, device identity, rate, channel mapping and unchanged external app/process state. An open port or green badge is insufficient.
- Verify 18i8 channels and actual guest-return channels with isolated signals. Check mix-minus, remote participant audibility and private talkback, with explicit approval for each necessary routing or session change.
- Verify denied microphone/automation permissions, missing device/driver/model, port conflict, stalled callback and disconnected device. Unknown recording state must block disruptive actions.
- Test exact local Qwen3 inference and bilingual speech/text with network unavailable, approved caches present and no remote execution. Calibrate consented speaker matching and unknown-speaker rejection; demonstrate deletion and retention policy.
- Validate guided installation, application signing/notarisation, permission denial/retry, model download integrity, insufficient disk space, upgrade, uninstall and complete exit without Terminal.

See `ROADMAP.md` for implementation order and acceptance criteria. These failures are diagnosed baseline defects/feature gaps; the Linux inspection workflow works, but the macOS application is not production-ready.
