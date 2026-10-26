# Local learning report — Sawti 3.0.5

Sawti keeps its private working memory in SQLite. It now also creates a separate, readable JSON report for the operator to copy out and share when requesting improvements. Sharing this report is not a way to install code or grant control of audio applications.

## Use without Terminal commands

1. Install 3.0.5 using the existing guided installer, open Sawti and switch ON.
2. Open **Learning → Open learning folder**. Finder opens the dedicated report folder on the Mac.
3. Copy **Sawti-Learnings.json** wherever you want, or use **Download learning report** to get a fresh copy in the browser's downloads location.
4. Upload that file here with a short description of what worked and what failed. Nothing is uploaded by Sawti itself.

The production location is `~/Library/Application Support/Sawti/learning_reports/Sawti-Learnings.json`. Simulation and cloud/test data use their separate `SAWTI_DATA` folder, so practice history does not overwrite the production report. The app shows the actual folder in Learning.

## Contents and limits

After every saved learning event, Sawti refreshes the report from **all retained v3 event rows**, including history that predates this update. It includes event timestamps, counts, recognised command intents and action IDs, selected mic inputs, measured gain advice, test outcomes, show durations and mastering measurements where available. Structured API failure categories/status codes are recorded without error text. New events carry their Sawti version; older events without a version remain unversioned rather than being attributed to the new build. The header identifies the exporter version, local OS version/architecture and simulation state.

The working event store has a 180-day retention policy applied during database initialisation. This file is a current snapshot, not a permanent archive of every past show. Copy it out periodically if you want an archive. The report does not contain the full private database, learned filename patterns, filename observations or the preserved 2.2 free-text archive. Timestamps can still reveal usage schedules; review the file before sharing it.

Export uses a closed set of recognised event kinds and enum values plus finite numeric/boolean measurements. It excludes programme audio, voice signatures/embeddings, presenter names, chat transcripts, session names, filenames, private paths and raw error messages. Unknown event kinds become `unclassified_event` with their payload omitted. This intentionally keeps the shared report less detailed than local private memory. It does not prove correct routing, track assignments or recording integrity.

## Failure, reset and removal behaviour

The report is written through a temporary file and replaced atomically, with file mode 0600. Report/folder symlinks are rejected. A failed update leaves the previous report intact and the working SQLite history saved; Learning shows the failure and stale downloads are blocked until refresh succeeds. It never starts capture, changes routing or sends transport commands. Writing a snapshot is local file I/O on learning events, not an audio callback operation; production timing still needs Mac qualification.

**Forget everything learned** clears the working learning history and replaces the local report with an empty report. If replacement fails, the app explicitly warns that the old report may remain. Copies already downloaded or moved elsewhere are outside Sawti's control and remain untouched.

The uninstaller can move the known report file to Trash when personal data removal is selected. Reports are retained when only the runtime/app is selected. Unknown files placed beside the report are preserved. An empty report directory may remain after data removal.

Linux tests cover privacy filtering, more than 2,000 events, atomic-write failure, reset failure, symlink protection, file permissions, local download gating and uninstall selection. Finder/browser behaviour on the actual Mac still needs confirmation.
