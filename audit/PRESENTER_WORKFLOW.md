# Presenter-led Podcast workflow: requirements and implementation roadmap

User requirement: select Podcast, sit at Mic 1 and say “Sawti, please test the mics and if all is good count me down and start recording.” Everyday operation must use the application and voice, without Terminal commands.

## Evidence from the studio

The operator reports working live PPM readings and gain guidance, and successful Audition launch. Focusrite Control recognises Scarlett 18i8 USB and reports 48 kHz. These observations do not establish Audition input assignments, track arming, transport control or recorded-file integrity. No direct remote access to this Mac is available in the cloud workspace.

## Current implementation and gaps

| Component | Current code | Gap for the requested workflow |
|---|---|---|
| Podcast mode | Selects the stored source/track profile | Does not orchestrate the full preparation-to-recording sequence |
| Focusrite / Audio MIDI Setup | Read-only discovery and individually approved device actions | No qualified Focusrite Control UI adapter or observed routing verification; retain the existing working configuration |
| Audition tracks | Copies an operator-created .sesx show template | Does not create and verify a complete track layout in the active Audition session |
| Record / Stop | Approved keyboard shortcuts; delayed check for WAV file growth | Cannot observe transport, active session, correct input mapping or per-track recording; shortcuts alone are insufficient for autonomous operation |
| Mic tests | Meter measurements and an operator-stepped pre-test | Requires reliable automatic progression, fresh per-channel evidence and named failure handling |
| Voice commands | Optional local transcription of browser button recordings | No dedicated Scarlett channel 1 wake listener; browser default microphone need not be Mic 1 |
| Responses / countdown | Text replies | No spoken dialogue, timed countdown or cancellation protocol |
| Voice identity | Optional voluntary embeddings; explicitly not authentication | Recognition must never grant unrestricted control or substitute for recording authorisation |

The current chat safety correction recognises combined test/countdown/record requests and offers pre-test only. It does not implement or claim the requested sequence.

## Intended operating contract

Before every Podcast session, Sawti asks how many programme microphones will be used and confirms the answer: one, two or three, never more than three. Input 1 is always the presenter. Inputs 2 and 3 are guest microphones when selected; input 4 is always operator talkback, never a programme recording track. For two microphones, confirm which guest input is occupied instead of silently assuming it. Arm and test only the confirmed programme inputs; test talkback isolation separately. Changing the selection invalidates track verification, mic-test results and any pending countdown. This selection dialogue is a requirement, not a currently implemented feature.

One-time guided commissioning establishes the approved Podcast configuration: Scarlett identity and rate, microphones to record, excluded talkback channels, output monitoring, Audition version, known template, track input/arm map, recording destination and macOS permissions. It verifies a short test take and playback. Existing working routing is preserved.

Selecting Podcast chooses a plan. Any required routing, clock, device or phantom-power change is explained and requires separate explicit approval while idle. Audio MIDI Setup is a macOS utility; Sawti should inspect CoreAudio directly rather than opening or manipulating that window unnecessarily. Digital monitoring controls and analogue gain knobs are distinct: Scarlett 18i8 analogue microphone gain requires a human adjustment.

After the operator explicitly enables hands-free control, a bounded local listener reads the commissioned Scarlett input 1. The original recordings and production monitoring do not depend on that listener. Commands are scoped to a session, expire, and cannot be reused. Programme audio, recorded playback and Sawti's own speech must not trigger transport. Low-confidence or ambiguous speech requires a spoken clarification. Provide visible listening state and a manual control alternative.

The requested utterance authorises one conditional sound-check and recording sequence for that session, without authorising changes to existing routing or interruption of another recording. Recheck idle transport and active session before executing it. A deterministic controller, rather than an LLM's free-form tool calls, enforces:

`idle → preflight → session prepared and verified → sequential mic tests → ready → spoken countdown → record requested → recording verified`

Any missing permission, stale input, failed or skipped test, wrong session, changed device/mode, disk problem or unknown transport blocks progression. Explain the issue and return to a safe state. “Cancel” before recording cancels the pending sequence; it never sends Stop to an existing recording. Once recording begins, stopping requires its own explicit command and verified target. OFF cancels pending actions and stops Sawti services while production recording continues.

During the countdown continuously recheck the same session, transport and device identity. Keep speech out of recorded tracks; check output-to-mic feedback and any loopback path during commissioning. Before announcing “recording,” verify both Audition transport and growing media for every expected track, with the correct channel assignments. File growth alone cannot prove this. An uncertain result must say “recording unverified” and alert the operator without retrying a transport toggle.

## Implementation order and release gates

1. **Qualify an Audition adapter on the actual Mac.** Obtain macOS and Audition versions. Inspect its macOS Accessibility tree read-only. Establish whether session path, track input/arm state, record controls and transport status are observable. Prefer identified controls and menu items with verified postconditions. Do not rely on pixel coordinates, timing alone or unqualified shortcuts. If essential state is inaccessible, retain supervised operation and report the limitation rather than claim hands-free recording.
2. **Commission session preparation.** Reuse the working template mechanism first. Add an app wizard to establish the desired track layout once, then verify its dated copies in Audition. Define a tested format/version boundary before writing session XML. Preserve existing sessions and never replace an active session during recording.
3. **Implement the deterministic sequence.** Add cancellable state transitions, per-run authorisation, fresh evidence, timeouts and an audit trail. Automatically advance microphone tests only after measured pass criteria; ask each participant to speak. Missing participants, uncertain mapping or gain failures block the sequence. Obtain human headphone/privacy confirmation where software cannot observe it.
4. **Add explicit Mic 1 voice and spoken feedback.** Use local English/Arabic recognition with a commissioned input channel and local speech output. Add listening opt-in, expiry, playback rejection, confirmation of ambiguous commands, countdown and cancellation. Keep Qwen for explanation and planning; it cannot bypass the controller's checks.
5. **Mac qualification before release.** Demonstrate the complete presenter workflow and preserve all existing manual controls, meters, installer and uninstall behaviour. Separately qualify Zoom with BlackHole, guest return, mix-minus and talkback exclusion after Podcast is reliable.

Automated adapter and state-machine tests must cover wrong foreground app/session, unknown or already-active transport, absent or unarmed tracks, shortcut changes, permission denial, silent/clipping/swapped inputs, stale meters, low disk space, device removal, cancellation at every stage, repeated commands, delayed transcription, OFF during countdown and ambiguous start results. These tests must prove no transport or routing write occurs when a prerequisite fails.

Physical Mac acceptance must prove isolated recorded tracks, playback integrity, stable long takes, sleep behaviour and that OFF/server crash/uninstall never breaks a recording or the established production audio path. English/Arabic speech, programme playback and speaker output need false-trigger trials. Linux simulation cannot qualify those behaviours.
