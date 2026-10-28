# Sawti 3.2.1: saved Audition template dropdown

User request: list `.sesx` templates already saved in Audition and let the operator select one inside Sawti.

## Install the update

Finish all recording, quit Sawti and install the 3.2.1 source update using the existing installer. Refresh the browser page after launching it. This feature needs no new AI models. If your AI and voice packages are already installed, choose No to those optional installation questions to retain them without re-downloading; the installer does not remove them or reset the selected chat model.

## Operator workflow

1. Save a clean, empty two-person session/template in Audition. Mic 1 is presenter, Mic 2 is the guest (or Mic 3 if that is the confirmed arrangement), input 4 is talkback only. Keep the original file in its existing location.
2. In Sawti, switch ON, select Podcast and confirm the programme microphones. Under Prepare → **Choose an existing Audition template**, click **Find saved .sesx files**.
3. Select the file from the **Saved sessions / templates** dropdown. Duplicate filenames are distinguished by their folder. The preview displays saved audio-track names, saved arm flags and sample rate. These fields are best-effort XML inspection, not observation of the active Audition session or verification of physical inputs.
4. Check that the selected file is a clean, empty reusable template and tick the acknowledgement. Click **Use selected as show template**, then review the idle confirmation. Sawti copies the inspected file into its own template store for the current microphone arrangement. Neither discovery nor adoption opens Audition or sends routing/transport commands.
5. Enter the episode name → **Prepare session** → **Open in Audition**. Opening is a separate, explicitly approved action. Verify the active session, inputs, arms and talkback exclusion in Audition before recording.

The manual path field and **Use as show template** button remain available. They now require the same idle/empty-template confirmation and reject known recorded content.

## What is searched

Search runs only on an explicit button click. On a real Mac, standard roots are:

- `~/Library/Preferences/Adobe/Audition`
- `~/Library/Application Support/Adobe/Audition`
- Sawti’s own `templates` folder
- `~/Documents`
- `~/Music`
- The configured recording root

Simulation searches only its private Sawti template folders by default. An explicitly supplied folder is searched by itself. Use **Search a different folder** for another saved location, an external drive, or a narrower scan. Finder’s Option+Command+C copies the selected folder path; no Terminal command is required.

Search is bounded to 5,000 entries, 150 `.sesx` files, seven subdirectory levels and a four-second traversal budget, with cancellation checks between operations. These bounds do not guarantee an OS filesystem call will return within four seconds, especially on an unavailable/network/cloud-backed drive. Scans and source inspection release the studio request lock so OFF can still proceed. Incomplete searches and permission/availability problems are reported. Hidden entries, symbolic links and linked folders are skipped. Unsaved Audition windows and non-`.sesx` template formats are not included. Mac folder access may require permission. Built-in templates stored elsewhere in an application bundle are not automatically enumerated.

Discovery lists saved **sessions**, not a guaranteed catalogue of empty templates. Existing episode files use the same extension. Files are parsed only after selection. Templates saved in an unknown Audition-version layout may require manual inspection or a fresh saved template.

## Adoption safety

- Search and preview cannot start/stop recording, launch Audition, change sample rate, change routing or replace files.
- Choice IDs are volatile and bound to the current power epoch, mode and microphone-plan UUID. New searches invalidate old choices. Mode/mic/power changes invalidate selections, including a switch between two-mic arrangements with the same count. UI polling preserves a pending selection within the same context.
- Preview returns a SHA-256 digest. Adoption re-reads at most 8 MiB into a byte snapshot and requires the same digest. Changed or removed source files require a new inspection.
- Nonregular files and final-component symlinks are rejected. XML with the wrong root, invalid XML, no audio tracks or a mismatched Podcast audio-track count is rejected. The XML parser does not validate channel assignments against CoreAudio.
- Known `audioClip`, `videoClip`, `clip` or populated `file` elements block adoption. This is deliberately conservative; unknown schemas or indirect media references are not proof of emptiness. The operator’s empty-template attestation and Audition inspection remain necessary.
- Both dropdown and manual-path API adoption require explicit idle and empty-template attestations and are blocked while Sawti is LIVE. Sawti still cannot observe recordings started manually outside its interface; the operator must check all recording applications.
- A validated byte snapshot is written to a private temporary file and atomically replaces the matching Sawti template copy. Re-adopting the current stored copy is supported. The source is not modified (when the source is already the destination, identical bytes are safely rewritten).
- Adoption clears Sawti’s old prepared-session pointer, manual confirmations and active pre-test, revokes old action approvals and mutes/revokes Sawti’s own private-speech setup. Existing episode files, media and the session currently open in Audition remain untouched. Prepare a new episode before recording.
- Original filenames, folder paths and XML are not added to the redacted learning export. `template_saved` retains existing mode/track-count metadata only.
- Clean uninstall’s narrow generated-template allowlist includes all supported one-, two- and three-mic copy filenames. Selecting data removal moves these copies to Trash. Original sessions elsewhere, unknown `.sesx` files, and recording roots remain protected.

## Verification boundary

Automated tests use isolated files, simulation and a substituted browser DOM. They cover search scope, limits, permission failures, stale IDs/context/content, recorded-media rejection, track-count mismatch, source preservation, approval/idle gates, OFF during scans/source reads, adoption invalidation, same-file adoption, UI selection persistence and late responses. Real HTTP tests exercise discovery → preview → adopt → prepare without opening a real studio application.

The actual Mac Studio is not connected to this environment. Discovery under real macOS privacy permissions, saved Audition 26.3 XML layouts, Safari/native dropdown appearance, and real input/arm mapping are **not qualified** by these tests. No hands-free recording capability is added.

Final cloud validation: **229 Python tests, 40 JavaScript checks and 66 live HTTP checks passed**. Shell syntax and whitespace checks passed. Raw results are in `results/`; no actual Mac qualification is implied.
