# Sawti 3.0.2 clean uninstall

The installer now creates **Uninstall Sawti.app** in `~/Applications` and a Desktop shortcut, alongside the normal Sawti app. The source folder also provides `UNINSTALL_SAWTI.command`, which opens the same native review dialogs. No Terminal commands need to be typed.

## Operator flow

1. Stop all production recording and confirm the studio is idle. The dialog explicitly warns that older inline builds may carry production audio.
2. The uninstaller stops only processes whose saved PID, precise birth time, user and executable identity match. Unknown/hung processes require manual closure in Activity Monitor. It never force-kills Audition, Zoom, Focusrite, external Ollama or an unverified process.
3. Select components: apps/shortcuts/backups; private Python/Ollama/models/caches/logs; personal settings/presenters/templates/learning; optional unchanged source files; optional unused Sawti virtual devices.
4. Review the exact proposed paths. **Review list** opens the complete JSON plan in a text editor. Cancel remains available. Cancelling after step 2 leaves Sawti stopped but installed.
5. Approve **Move to Trash**. Audio-device removal requires an additional, separate confirmation naming the devices.
6. Read the completion report. Items are moved to this user's Trash, not permanently erased. Empty Trash only after reviewing preserved files to reclaim disk space. Personal data in Trash remains recoverable until then; this is not secure erasure.

Private removal covers Sawti's runtime, Python environment, Qwen models, private voice caches, installed helper, local databases, logs, owned launcher backups and verified Desktop symlinks. The optional personal-data choice includes presenter signatures and known saved show templates.

For maintainers: `install-source-manifest.json` is generated from Git membership by `helpers/build_source_manifest.py`. Stage new files, regenerate the manifest, and run its `--check` command before packaging. Never replace it with a directory scan; that could claim pre-existing user files as application source.

Recordings, configured recording locations, unknown files, unknown sessions, edited source files, Git checkouts and pre-existing user files are retained. Source ownership comes from a packaged checksum inventory, never a directory scan that claims everything it finds. Existing legacy installations without that inventory cannot automatically remove their source files or unverified Finder aliases; the report identifies retained items for manual review.

New voice-model and package caches live in private Sawti locations. Legacy shared Hugging Face caches, pre-existing Ollama, BlackHole drivers, FFmpeg, Homebrew, Apple Command Line Tools and macOS permission grants are **not removed**. Other applications may depend on them. This is a complete cleanup of identified Sawti-owned components, not a rollback of the Mac's shared software or previous studio routing.

## Safety and recovery

- No default input/output, sample rate, Focusrite preset or existing routing is restored or changed automatically.
- The optional device cleanup recognises only `com.imi.sawti.show-input` and `com.imi.sawti.zoom-speaker`. The trusted helper must report them inactive, non-default and unreferenced. Unknown state is a refusal, not permission. It repeats these checks immediately before destruction. Physical Scarlett and BlackHole drivers are never destroyed.
- Symlink targets are not traversed or deleted. Cleanup refuses symlinked ancestor paths, path traversal and arbitrary removal paths injected into a plan file.
- File moves use rename into a unique Trash directory, without cross-volume copy/delete fallback. Concurrent changes or permissions failures retain the affected items and are reported.
- A private report journal is established before mutation, updated after moves and completed under `~/Documents/Sawti Uninstall Reports/`. Reports contain paths/outcomes, not database contents or credentials.
- Partial failures retain the uninstaller, helper and inventory where available for retry. Removed items remain in Trash. No destructive automatic rollback is attempted.
- The cleanup engine imports Python's standard library, not Flask, NumPy, sounddevice or the application. The native launcher tries the private interpreter, system Python and managed-runtime fallback. If no working interpreter exists, it refuses cleanup rather than deleting blindly.

For an already installed older version, download the complete current source ZIP. Its `.command` uninstaller can perform conservative legacy cleanup without starting Sawti. Run the updated installer only while the studio is idle if you want the new bundled uninstaller, ownership inventory and private caches registered for future use. Do not assume an old unregistered source folder or shared cache is exclusively owned by Sawti.

## Verification and remaining Mac gate

The test suite exercises cleanup only in temporary fake home directories. Uninstall-specific tests cover inventory, user files present before installation, source edits, recordings/sessions, custom recording destinations, consent, symlink/path attacks, corrupt PID records, stale identity, private cleanup, personal-data retention, audio-device refusal, partial failure/retry and repeatability. The native-dialog script is executed with UI substitutes to test cancellation, scoped review, explicit device confirmation, missing interpreters and shell quoting.

Recorded Linux results: **101 Python tests passed**, including **30 uninstall-specific tests**; **14 JavaScript checks passed** (7 browser and 7 native-dialog substitute checks); **25 live HTTP checks passed**; zsh syntax passed. A subsequent standalone CLI smoke also exercised registration, preview and cleanup in a fake home with site packages disabled.

Results and actual exit codes are in `results/`. The broader application suite, browser checks, HTTP smoke and zsh syntax checks are rerun for this release. A macOS CI job was added to compile the Swift helper and JXA script and run fake-home cleanup tests. GitHub Actions status could not be read through the current API access (Forbidden); no hosted build result is claimed.

**Not yet verified on the Mac Studio:** native dialog rendering, standalone app creation/signing, libproc birth identity, actual CoreAudio activity/default/reference queries, self-removal of the running uninstaller and its private interpreter, Trash permissions and macOS privacy prompts. Do not treat Linux/fake-home tests as proof of those behaviours.

Mac acceptance must use a disposable user account/test installation with the studio idle. Verify preview and cancellation first, then test retaining personal data, complete private cleanup, active/default device refusal, recording preservation, a broken Flask environment, an unknown process, and retry after a simulated file permission failure. Confirm shared audio software and routing are unchanged before relying on emergency cleanup.
