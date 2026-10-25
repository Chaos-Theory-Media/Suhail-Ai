# 3.0.3: first Mac integration feedback

The operator reported that Sawti loaded, but ON did not open Focusrite/Audition, the Scarlett was not detected, and its rate appeared unset even though Focusrite Control recognised the interface at 48 kHz. Those are operator observations, not readings from this cloud machine. The operator subsequently confirmed Audio MIDI Setup lists **Scarlett 18i8 USB**. The actual failing CoreAudio/PortAudio query remains unknown until Mac diagnostics are supplied.

Corrections:

- Added **Open studio apps**, separate **Open Focusrite Control** and **Open Adobe Audition**, and **Show device diagnostics** controls in Prepare. ON still starts only Sawti's services; app launches require individual idle confirmation and cannot run as learned/bulk fixes or during LIVE.
- Scarlett 18i8 3rd Generation targets the original **Focusrite Control**, not Control 2. App discovery checks actual installed bundles in system/user Applications and Spotlight fallback; it does not silently substitute Control 2.
- Audition discovery recognises `com.adobe.AdobeAudition` as well as other Adobe Audition bundle identifiers and direct/nested app locations. Missing discoveries are not cached forever.
- Opening Audition no longer requires first saving a template. **Open in Audition** still opens/prepares a session; **Open Adobe Audition** requests only the application launch. Audition can restore its own workspace, which the operator must check.
- OS launch errors and partial batch failures are returned as errors instead of an unconditional success message. Existing running apps are left alone.
- A bounded, cached, read-only `system_profiler SPAudioDataType -json` fallback observes macOS device names/channels/current reported rates when the compiled helper is missing or returns zero. It never sets a rate and does not claim capture is available without a PortAudio index. Native observations have explicit rate provenance.
- Audio helper and PortAudio errors are retained and displayed. PortAudio refresh failures are no longer swallowed. A failed query is distinct from an empty valid device list. Renamed Scarlett devices can match their original UID. A partial helper inventory no longer hides a Scarlett visible to PortAudio/native inventory.
- Zero, unavailable or default-only rates are **unverified**, with no proposed rate-setting action. A verified 48 kHz observation produces no rate-change suggestion. Sawti does not claim that an unobserved hardware rate is unset.
- The on-screen diagnostic summary includes query success/errors, device names, channel counts, verified rates and capture indexes. It omits device UIDs/serial identifiers, recording content, presenter data, settings and credentials.

Validation: 19 new regression tests passed, then the complete Python suite passed (120 tests), JavaScript checks passed (14), and the live HTTP smoke passed (25 requests). Actual results/exit codes are in `results/`. App discovery and OS launches use substitute bundles/process calls in these tests; there is no claim that this cloud environment launched real Mac applications or read the physical Scarlett.

## Updating without changing audio settings

With production recording stopped, Quit the existing Sawti page/server. Extract the 3.0.3 ZIP into a new persistent folder. Double-click **START_SAWTI.command in that new folder**, rather than the older Desktop shortcut, to use the existing installed Python/model runtime with the updated source. No model reinstall is needed for these Python/UI changes. A later idle-session installer run refreshes the Desktop launcher and uninstall inventory to the new location.

Switch ON, open Prepare, and choose **Show device diagnostics**. Share that text to diagnose the Mac-side query failure. If Focusrite already reports 48 kHz, leave the sample rate and routing unchanged. Do not reset/rebuild audio devices just to clear a Sawti warning. Also check read-only whether Scarlett appears in Audio MIDI Setup and supply its exact displayed name and the macOS version.

The initial blank-launch report was followed by the operator confirming Sawti loaded. Its original cause was not established; this release does not claim a proven fix to that earlier launcher symptom.
