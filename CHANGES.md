# 3.2.1 Saved Audition template discovery and dropdown

- Add explicit read-only discovery of saved .sesx files in standard local locations, plus a specific-folder option, with bounded traversal and permission/limit reporting. Unsaved Audition windows are not a file catalogue.
- Add a dropdown and preview showing track names, saved arm flags and sample rate. A saved session is not automatically an empty template. Known clips/media references, changed source content, stale microphone plans and mismatched track counts block adoption.
- Require idle and empty-template attestations for dropdown and manual-path adoption. Copy a validated byte snapshot atomically, including safe reuse of Sawti’s current stored template. Invalidate old Sawti session preparation, checks and private-speech qualification without opening Audition, sending transport commands or deleting existing episodes.
- Keep OFF responsive during scans/source reads and discard stale results. Extend uninstall’s narrow generated-template allowlist to all supported microphone arrangements while preserving original/unknown sessions.
- Preserve manual path entry and existing two-person instructions. Real Mac folder permissions and actual Audition 26.3 files still require qualification.

# 3.2.0 Enhanced local models for the M1 Ultra (Mac qualification preview)

- Offer Qwen3-30B-A3B Q4_K_M instead of the former fixed Qwen3 4B, retaining the existing model and requiring downloaded model details/tool support before activating the upgrade. Changing the selection in Settings requires OFF. Use bounded 8K context, disabled thinking, one loaded Ollama model and one parallel request.
- Add isolated, pinned Apple Silicon specialist dependencies: MLX Whisper large-v3-turbo, BGE-M3 embeddings and BGE reranker v2 M3. Download only during installation; resolve immutable Hugging Face revisions and use local paths/offline mode during everyday operation. Keep the working audio venv separate.
- Add model inventory and synthetic inference checks. Serialise enhanced tasks, cancel the owned specialist process on OFF, discard obsolete results, and hold enhanced inference during Live pending actual Mac performance qualification. Built-in level/recording-status answers remain available.
- Add private local PDF/text/Markdown reference import, version labels, multilingual dense retrieval plus reranking, and an Ask manuals answer with source labels and no action tools/buttons. No manufacturer manuals are bundled. Reference capacity and lack of scanned-PDF OCR are explicit.
- Extend clean uninstall to owned specialist processes/runtime/models and imported reference copies. Preserve original documents, shared Ollama and recordings.
- Apple Silicon dependency resolution and Linux regression/safety tests are evidence of integration compatibility, not Mac inference, language accuracy, recording integrity or audio-isolation qualification. See `audit/models/README.md`.

# 3.1.0 Operator-commissioned presenter voice and animated character

- Add the original SVG golden-microphone character with large glasses, blue eyes, curls, red lips, an automatic text welcome, blinking/breathing motion and speaking-state mouth animation. Respect reduced-motion preferences.
- Add opt-in local macOS speech, synthesized to temporary files and played through an exact Scarlett UID/index at its verified current rate. Native CoreAudio channel mapping connects only the operator-confirmed USB Playback 3–4 pair. No default output, browser speech, system device change or routing setter is used. English and optional Arabic voices are chosen from the installed catalogue.
- Require idle commissioning, an explicitly approved test phrase and operator attestations covering headphones, recording exclusion, loopback exclusion and acoustic bleed. Qualification is in memory and is revoked by OFF, mode/mic-plan/device changes or failures. Spoken welcome occurs after enabling, not unconditionally at launch.
- Coordinate test admission with Go Live/Record/pre-test; cancel synthesis/output on OFF. Protect live PortAudio streams from reinitialisation while an owned speech output exists. Failure to close output blocks speech reuse until restart.
- Add direct fresh-level and unknown-recording-state answers. A LIVE marker never becomes proof that Audition recorded anything. Log speech outcome metadata without retaining spoken text, voice names or device identity in the learning report.
- Hardware and recording-isolation tests must be completed on the actual Mac; cloud tests use substitutes. Continuous Mic 1 listening, autonomous countdown and verified Audition transport remain outstanding.

# 3.0.7 Direct conversational help in English and Arabic

- Add concise identity and practical system/Podcast/Zoom/Stop guides. Common educational questions work without Ollama and do not query hardware, switch modes or propose transport commands. Accept the common “Swati” spelling and the reported “recroding” typo in help questions.
- Distinguish how-to recording questions from direct Record/Stop commands; preserve current studio-check and troubleshooting intents.
- Instruct Qwen to answer first without paraphrasing the question, listing unrelated capabilities/limits or narrating reasoning. Keep thinking disabled, bound generation and remove explicitly marked reasoning blocks, including partial markers. Ordinary operating advice remains intact.
- Include current manual verification requirements in built-in guides and the AI prompt. Retain all operator approvals and proposal-only AI tools. Add help examples to the chat prompts and new intent IDs to the redacted learning report.

# 3.0.6 Preserve microphone selection during status updates

- Fix the one-second status refresh clearing unconfirmed microphone choices. Pending choices now survive normal polling, including edits to an existing confirmed plan.
- Populate the selector from an existing confirmed plan on reload and synchronise a new confirmed plan from another tab. OFF, mode and power-session changes invalidate stale drafts.
- After confirmation, immediately display the accepted plan and discard older pending status responses. OFF or mode change during the confirmation dialog prevents a stale submission. Selection still needs explicit confirmation and never changes routing or Audition tracks.
- Regression tests execute the actual UI script with DOM/network substitutes; real Safari validation remains necessary.

# 3.0.5 Local learning report for upgrade feedback

- Automatically refresh a redacted JSON report after each saved learning event and on learning reset. Export all retained events, rather than the default 2,000-row query window. New events include the Sawti version.
- Add Learning buttons to open the dedicated local folder in Finder or download a fresh copy. No automatic upload, network transfer, audio capture or routing change is introduced.
- Export closed-set event tokens and numeric measurements; exclude names, paths, filenames, voice signatures, chat text and raw error messages. Include structured API failure categories for QA feedback.
- Write the report atomically with private permissions. A failed report write preserves SQLite history, marks the report stale and blocks stale downloads. A failed reset explicitly warns that an old report may remain.
- Treat the report as optional personal data during uninstall; preserve unrelated files in its folder. Independently copied reports are untouched.

# 3.0.4 Podcast commissioning and autonomy evidence

- Confirm one to three programme microphones in Prepare. Mic 1 is presenter; input 4 is talkback only. Selected inputs drive the Podcast profile and pre-test. Zoom retains its separate existing profile.
- Keep templates per mic arrangement, enforce matching audio-track count, and bind dated sessions to the current confirmation. Reconfirming, OFF and mode changes invalidate the old plan while preserving recordings and session files.
- Invalidate prior approvals and manual sound-check confirmations when changing the plan; stop only Sawti capture without opening apps, changing devices or restarting a stream.
- Add actual OS/app build readback and an honest readiness report. Add explicit bounded read-only Audition Accessibility inspection; no activation, clicking, keystrokes or transport commands. OFF remains responsive and discards late inspection results.
- Automated coverage includes microphone bounds, talkback exclusion from the plan, wrong templates, stale session bindings, permission failures and bounded inspection. Real Mac qualification, input/arm verification, hands-free Mic 1 listening, spoken countdown and autonomous transport remain outstanding.

# 3.0.3 studio application and device diagnostics

Corrects Focusrite Control compatibility, adds explicit studio-application launch controls independent of session templates, supports actual Audition bundle identifiers, surfaces OS/device query errors and distinguishes unverified rates from a hardware mismatch. See [audit/studio-apps/README.md](audit/studio-apps/README.md) for evidence and Mac follow-up steps.

# 3.0.2 clean uninstall

Adds a bundled native review UI, standalone cleanup engine, component inventory, private cache locations, verified process shutdown, optional guarded removal of unused Sawti virtual devices, recoverable Trash moves and partial-failure reports/retry. Recordings, unknown/edited files and shared tools are retained. See [audit/uninstall/README.md](audit/uninstall/README.md) for scope and Mac validation limits.

# 3.0.1 QA improvements

See [audit/qa/REPORT.md](audit/qa/REPORT.md) for evidence, limitations and remaining release gates. The original 3.0 claims below are retained as historical design notes; they are not independent validation.

Safety changes include individually approved audio actions, non-audio bulk/learned fixes, coordinated OFF/capture lifecycle, browser microphone cleanup, owned-process identity checks, refusal of unverified AI services, and blocking real inline output pending qualification. Migration preserves 2.2 data; exports use unique folders; silence/readiness messages now reflect uncertainty. Arabic rule responses, input validation, regression tests, HTTP smoke and CI were added.

# Sawti 3.0: changes from 2.2

## Every QA defect and its fix

| # | 2.2 defect | 3.0 fix | Proven by |
|---|---|---|---|
| 1 | Installer rejected every Python except 3.11/3.12 (macOS ships 3.9; current downloads are 3.13/3.14) | Installer brings its own Python 3.12 through uv, so no Python install is needed. Falls back to the system Python 3.10–3.13 | installer dry run |
| 2 | "Right-click › Open" no longer works on macOS Sequoia | README explains Privacy & Security › Open Anyway. The installer then clears quarantine for the folder and creates a Sawti app | — |
| 3 | Ctrl+C or closing Terminal left the private Ollama running (several GB of RAM) | Signal and exit handlers stop every Sawti-owned process. Pid files clean up after a crash. Sawti runs in the background with a Quit button | `test_lifecycle` (SIGINT, SIGHUP, SIGTERM, crash) |
| 4 | Most suggested prompts answered wrongly; "صوتي" triggered the mic answer | Wake word removed before matching; ordered word-pattern intents; answers built from live checks, with action buttons | `test_chat` (26 prompts, EN+AR) |
| 5 | Zoom guests never metered; channel numbers had to be edited in JSON | Channels resolved automatically from the aggregate layout (Zoom guests on inputs 19–20) | `test_zoom_devices_created_and_guest_channels_mapped` |
| 6 | Meter start failure showed only "Request failed" | Real reason returned and shown | `test_meter_failure_reports_reason` |
| 7 | macOS permission block looked like dead mics | Digital-silence detection, with a button that opens the right Settings page | `test_permission_block_detected` |
| 8 | Static mockup always showed "Mic 1: No audio detected" | Removed; live meters with per-mic coaching instead | UI walkthrough |
| 9 | Richer health checks were never used | All agents feed one check list with Fix buttons | — |
| 10 | Voice buttons shown but not installed | Voice is an installer option; buttons appear only when installed; models cached | — |
| 11 | Disk check looked at the app's drive | Checks the drive holding the recording folder and shows hours left | — |
| 12 | Sample rate "check" read the default only | Reads the device's actual nominal rate through CoreAudio, with a Set to 48 kHz fix | `test_fix_all_repairs_sample_rate` |
| 13 | Other websites could switch Sawti on/off and start scans; no Host check | Host allow-list, required X-Sawti header, Origin check, strict CSP | `test_server` |
| 14 | Presenter name could run script in the page; names with "/" could not be deleted | DOM built with textContent; presenters addressed by id | `test_presenter_delete_by_id_handles_any_name` |
| 15 | Chat prompts logged forever; learning scan could crawl a whole home folder | Only intents logged, 180-day retention; scan refuses home/system folders, with time and file limits | `test_folder_scan_refuses_home` |
| 16 | Qwen called without disabling thinking; 50 s timeouts | `think:false`, tool calling, 40 s cap, falls back to built-in agents | — |
| 17 | Versions 2.0/2.1/2.2 mixed; two start scripts; temp file leak; tests not hermetic | One version (3.0.0); one launcher; temp files removed; tests use an isolated data folder and simulation | 36 tests |
| 18 | Mobile layout overflowed by 9 px | Fixed | UI walkthrough (0 px) |

## New capabilities
* **Devices agent:** creates and repairs *Sawti Show Input* (Scarlett + BlackHole) and *Sawti Zoom Speaker*
  (multi-output), and sets 48 kHz. All through a small CoreAudio helper.
* **Audition agent:** show templates, dated and correctly named sessions, open in Audition, Record/Stop with
  confirmation, and a check that audio is really being written.
* **Pre-test wizard:** per-mic sound check with dB coaching, swapped-cable detection, talkback isolation, Zoom
  guest return, and a check of the test recording.
* **Live mode:** level watching with alerts, keep-awake, and a guard that blocks device changes on air.
* **Post-production:** BS.1770 loudness QC, auto-mix (levelling plus closing mics that only carry bleed), and
  mastering to −16 LUFS / −1 dBTP.
* **Optional inline leveler:** a live gain rider plus limiter feeding BlackHole 16ch. Off by default.
* **Learning:** show-time prediction with automatic preparation in advance, learned naming, fixes promoted to
  automatic after two repeats (switchable), and gain-habit tips.
* **Simulation mode** for training and demos.
