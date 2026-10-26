# Sawti 3.0.4: Podcast commissioning and autonomy evidence

## Target reported by the operator

Mac Studio Apple M1 Ultra, 128 GB; reported OS “macOS Golden Gate 27.0.1”; Adobe Audition 26.3.0.79; Audio MIDI Setup 3.9; original Focusrite Control and Scarlett 18i8 3rd Generation. Focusrite reports 48 kHz. These are operator reports, not remotely verified hardware or compatibility results. No exact Focusrite Control version has been supplied.

The application reads the actual OS product version/build and app bundle version/build locally. It does not infer compatibility from a marketing name or replace existing audio settings to match this target. Audio MIDI Setup is a utility: reading CoreAudio does not require opening its window. Existing local Qwen/Ollama models remain unchanged; more memory alone cannot provide verified application control.

## Implemented in this update

- Explicit per-powered-session Podcast mic selection: [1], [1,2], [1,3] or [1,2,3]. Input 1 is presenter; input 4 is talkback, never an eligible programme input. Zoom commissioning remains separate.
- Matching profile, meter coaching and pre-test programme selection. Talkback remains separately monitored and tested. Unselected guest microphones do not block their own mic-test step because no such step is generated.
- Separate templates per selected arrangement. A three-track template cannot be silently adopted or copied for a one-mic plan. The existing legacy three-mic template remains supported for three-mic selection. Track count checks do not prove input assignments or armed state.
- Plan-bound dated sessions. A new confirmation, OFF or mode change invalidates the old plan. Existing session/media files are preserved; new preparation creates another folder when necessary. Changing the plan cancels pre-test, invalidates approvals and stops Sawti meters without reopening capture, launching apps or changing production audio. Confirm all recording is idle before changing the plan.
- Readiness report with actual detected versions and explicit blockers. It never claims full autonomy, since the transport adapter, hands-free input listener, spoken dialogue and countdown remain unqualified or absent.
- Explicit bounded read-only Audition Accessibility inspection. It only inspects an already-running Audition, never clicks, activates, types, reads text/value fields or sends transport commands. Denied permission, timeout and absence are reported. Output may include window/session names; inspect locally before sharing. No automatic upload occurs. Finding a Record button does not establish its safe use or current transport state.

## Install and collect Mac evidence without Terminal commands

1. Finish any recording, quit Sawti and keep the current working source folder as a fallback.
2. Download the tagged 3.0.4 ZIP, extract it into a new permanent folder under Documents, and double-click **INSTALL_SAWTI.command** to update the Desktop launcher and standalone uninstaller to this source inventory. Reuse the existing local runtime/models. Do not delete the earlier source until the new launch works.
3. Open Sawti, switch ON and select Podcast. Under Prepare choose the programme microphones and confirm while idle. Save/select the matching template, then prepare the dated session. Template creation and Audition input/arm verification still require the operator.
4. Use **Hands-free recording readiness → Show readiness report**. Check the actual OS/app versions shown.
5. With Audition already open, use **Inspect Audition controls**. macOS may request Accessibility/Automation access for the host app. This is read-only inspection; approve only the expected host. If denied, retain supervised operation and inspect the reported error. No recording is started.
6. Review the report for private window/session names, then share the version/readiness information and control-inspection result to qualify the next adapter. Do not reset routing, sample rate or the working Focusrite configuration for this test.

## Remaining work and release gate

See [the presenter workflow requirements](../PRESENTER_WORKFLOW.md). The target is an explicitly authorised per-session voice sequence, with independently verified idle transport, active session, correct armed inputs, fresh mic tests, cancellable countdown and verified recording on every selected track. Unknown state blocks progression. Stop and routing changes remain separately authorised. OFF must leave production audio independent of Sawti.

No physical Mac, Audition 26.3.0.79, Focusrite UI or OS 27.0.1 qualification was possible in the Linux cloud. The JXA reader has executable substitute tests and a macOS compile check in CI; substitute tests do not prove the real Accessibility tree or permission behaviour. Actual Mac validation is required before adding control actions to this reader or claiming autonomous recording.
