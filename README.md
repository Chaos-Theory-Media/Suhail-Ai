# Sawti 3.2.1 (صوتي): studio agents for IMI podcasts

**Saved Audition template dropdown (3.2.1):** Prepare → **Find saved .sesx files** → choose a saved session → inspect its tracks/rate → confirm it is an empty template → **Use selected as show template**. Searching is read-only. Only explicit adoption changes Sawti’s template copy; it preserves the original and does not open Audition or change routing. [Search locations, safety checks and limits](audit/template-picker/README.md).

**Start here: [Two-person podcast — illustrated operator guide](docs/two-person-podcast/README.md)** · [Printable PDF](docs/two-person-podcast/Sawti-3.2-Two-Person-Podcast-Guide.pdf). Presenter on Mic 1, guest on Mic 2; step-by-step preparation, sound check, recording and saving.

**Enhanced local AI preview (3.2.0):** The installer offers an M1 Ultra / 128 GB profile: Qwen3-30B-A3B Q4_K_M, MLX Whisper large-v3-turbo, BGE-M3 embeddings and BGE reranker v2 M3. The working audio environment stays separate from specialist dependencies. Settings shows downloads and offers a synthetic inference check. Import version-labelled local references and use **Ask manuals** for a combined, cited answer. Enhanced inference is held during Sawti Live until actual Mac performance is qualified. This is a compatibility-checked integration preview, not a hardware-qualified production release. [Setup, compatibility evidence and limitations](audit/models/README.md).

**Presenter voice and character preview (3.1.0):** Sawti appears as an animated golden microphone with glasses, blue eyes, curls and red lipstick. A text welcome appears at launch. Optional native macOS speech uses the operator-confirmed **Scarlett USB Playback 3–4 → presenter outputs 3–4** path, with other outputs unassigned; no default-speaker/browser fallback is permitted. Spoken welcome/replies require the in-app private-headset test and isolation attestations for the current powered session. Actual Mac playback and recording exclusion remain unqualified in the cloud. See [setup, privacy tests and limitations](audit/presenter-voice/README.md).

**Direct chat answers (3.0.7):** Ask “What is your name?”, “How do I use Sawti?” or “How do I record a Zoom interview?” for a direct answer or short numbered guide, in English or Arabic. Educational questions do not run studio checks or propose transport actions. Local AI instructions now answer first without repeating the question or describing their reasoning; explicit reasoning markers are filtered. Actual Qwen response quality still needs confirmation on the Mac.

**Mic selector fix (3.0.6):** Status polling now preserves your pending microphone choice until you explicitly confirm it. Reloading shows the confirmed plan; OFF, mode changes and a new powered session still clear stale choices. Finish recording, quit Sawti, extract this update into a permanent Documents folder and run **INSTALL_SAWTI.command** to update the launcher. Refresh the Sawti browser page after launching the new version.

**Share learning for upgrades (3.0.5):** Sawti automatically maintains `Sawti-Learnings.json` in its `learning_reports` folder. Use **Learning → Open learning folder** or **Download learning report** to copy it out and upload it here. It contains all retained structured events (180-day working history), with private fields removed. No audio, voice signatures, names, chat text or private paths are exported. Nothing uploads automatically. See [learning report details](audit/learning-report/README.md).

**Podcast commissioning (3.0.4):** Prepare asks which 1–3 programme mics are in use. Mic 1 is always presenter; input 4 is talkback only. Confirm while idle, then save/use a matching Audition template for that arrangement. Pre-test covers the selected programme mics and talkback. This does not automatically configure or verify Audition inputs. New in-app readiness and read-only control inspection report the remaining hands-free recording gaps. See [update and Mac qualification steps](audit/commissioning/README.md).

**Studio app/device fixes (3.0.3):** Prepare now has **Open studio apps** and **Show device diagnostics**. Scarlett 18i8 3rd Generation uses **Focusrite Control**. Unread rates are reported as **unverified**, not unset. See [Mac integration feedback and update steps](audit/studio-apps/README.md).

**Clean uninstall:** The current installer also creates **Uninstall Sawti.app** on the Desktop and in Applications. It reviews components, preserves recordings, and moves identified Sawti files to Trash. See [clean uninstall and its validation limits](audit/uninstall/README.md).

**QA status:** Linux tests and simulation are validated; Mac Studio hardware and installer qualification are pending. See [the QA report](audit/qa/REPORT.md). The original 3.0 upload is preserved at tag `sawti-3.0-upload`, and 2.2 at `sawti-2.2-baseline`.

Audio-impact actions now require an individual, 30-second, single-use operator approval and an explicit check that production recording is idle. Stop requires specific approval to interrupt. Power-on and learned fixes cannot change sample rates, routing or Audition transport. Sawti cannot observe Audition recording state; LIVE is an operator marker.

Sawti prepares the studio, runs the sound check, opens the right Audition session, watches levels during the
show and masters the episode. The person running the show presses a few buttons. Sawti assists with setup; the operator verifies the result before production use.

Built for: Mac Studio (Apple silicon, macOS 14+), Focusrite Scarlett 18i8, Adobe Audition, Zoom, BlackHole.

---

## First-time setup (about 20 minutes, once per Mac)

1. Unzip the folder and move **Sawti_3_0_Mac** into **Documents**. Keep it there. If you move it later, run the
   installer again.
2. Double-click **INSTALL_SAWTI.command**.
   macOS will block it the first time because it comes from the internet. Then:
   **System Settings › Privacy & Security** › scroll down › **Open Anyway** next to INSTALL_SAWTI › enter
   the Mac password. You only do this once.
3. Answer the two questions (local AI: yes; voice commands: optional). Wait until you see **✅ Sawti is installed**.
4. If the installer says Apple's *Command Line Tools* are needed, click **Install** in the Apple window,
   wait for it to finish, and run INSTALL_SAWTI.command again. Sawti needs these tools to create audio devices.
5. The first time Sawti meters audio, macOS asks for **microphone access**. Click **Allow**.
   The first time Sawti presses Record, macOS asks for **Accessibility**. Allow **Sawti** (or Terminal).

### Make the Audition template (once per show type)
In Sawti's **Prepare**, confirm the Podcast microphones for this session first. Templates are stored separately for each arrangement; OFF or changing mode clears the confirmation. Reconfirming starts a new plan and invalidates previous tests. Existing session files are preserved.

In Audition, create a **48 kHz multitrack session**:
* **Podcast:** one **mono** track per confirmed programme mic, named *Mic 1* and the selected guest mics, with the corresponding Scarlett inputs, all armed (R). Never add input 4 as a programme recording track. Sawti checks track count, but actual input mapping and talkback exclusion still need verification in Audition.
* **Zoom Show:** the same, plus a **stereo** track *Zoom guests* whose input is the last two channels of
  **Sawti Show Input**. Create that device first: switch Sawti ON, choose Zoom Show, press
  *Create it*, then review and approve the individual device change while all recording is idle.

Save the session. In Sawti, open **Prepare › Save the show template** and drag the .sesx file into the box.
Press **Use as show template**. From then on, Sawti creates a dated copy of this template for every show.

---

## Every show

Open **Sawti** from the Desktop and press **Switch Sawti ON**. Choose **Podcast** or **Zoom Show**. Then follow
the tabs:

| Tab | What you do | What Sawti does |
|---|---|---|
| **1 · Prepare** | Press **Run non-audio fixes**. Review individual device changes separately. Tick the blue items after checking them. Press **Open in Audition**. | Offers sample-rate and device changes for individual approval, prepares a dated session, and opens it only after operator review. |
| **2 · Pre-test** | Press **Start pre-test** and follow the instructions (each person talks, then talkback, the Zoom guest, then a 10-second test recording). | Checks that every voice arrives on the right input at the right level and tells you which knob to turn and by how much. Reports possible swapped inputs, silent signals and suspicious levels. Talkback privacy, permissions and actual recording paths still need operator verification. |
| **3 · Live** | Press **Go live**, then **● Record**. | Watches every mic and warns you if one gets too quiet, too loud or clips. It refuses any device change while you are live. |
| **4 · After the show** | Press **End show**, then **Mix & master selected tracks**. | Levels each speaker, closes mics that only pick up someone else, mixes, and masters to **−16 LUFS / −1 dBTP**. The originals are never changed. |

**Ask Sawti** (right side) understands English and Arabic: *"check the studio"*, *"how are the levels?"*,
*"صوتي، هل برنامج أوديشن يعمل؟"*. Answers come with buttons, so you can act straight away.

**To close Sawti:** press **Quit** on the page. Closing the browser tab releases voice capture and attempts to mute private speech, but leaves the control server running; use OFF/Quit for authoritative cancellation. Terminal signals have cleanup handlers, but an uncatchable crash still requires qualification.

---

## How Sawti learns
* It learns **when shows usually happen**. Automatic preparation is OFF by default. If explicitly enabled, it may prepare a session in the current mode; it never switches modes, changes devices or sends recording keystrokes automatically.
* It learns **how you name sessions** (for example `IMI_Talks_2026-10-25`) and where you save them.
* When you apply the same non-audio fix **twice**, it can offer that fix automatically. Audio-impact actions are never eligible. You can switch
  this off again in **Learning**.
* It remembers **gain habits**, for example *"Mic 2 usually needs about 6 dB more"*, and tells you before the
  guests arrive.
* Sawti never records, deletes or changes routing on its own while a show is live. Everything it learns stays
  on this Mac. To erase it, use **Learning › Forget everything learned**.

## Training without the studio
**SIMULATE_SAWTI.command** opens a simulated studio on a separate page (port 8766). The simulation has a quiet
mic, a hot mic and devices at the wrong sample rate, so new team members can practise. It keeps its own data,
so practice runs don't affect what Sawti learns about real shows.

## What Sawti cannot do (hardware and vendor limits)
* **The gain knobs on the Scarlett 18i8 are analogue**, so no software can turn them. Sawti tells you which
  knob to turn and by how many dB. It confirms the result in the sound check. The inline leveler DSP remains available in simulation. **Real inline output is blocked until qualified**, because stopping Sawti must not break a production audio path.
* **Focusrite Control has no verified control integration in Sawti for other apps.** Routing is stored in the Scarlett, so save a
  preset per show in Focusrite Control. Sawti's pre-test observes monitored inputs; it does not prove Audition track routing or Zoom talkback privacy. Verify those manually.
* **Audition has no automation interface on macOS.** Sawti uses your template files and presses Record or Stop
  with keystrokes after you confirm.
* **Zoom does not reveal which audio devices it is using.** Sawti shows the exact settings to choose and asks
  you to confirm once per day.
* Sawti is an in-house tool and is not notarised by Apple, so step 2 of the setup is needed.

Technical details for IT: **TECHNICAL.md**. What changed since 2.2: **CHANGES.md**.

## Clean uninstall

Open **Uninstall Sawti** from the Desktop or Applications, or double-click **UNINSTALL_SAWTI.command** from the current source folder. Stop recording first, select the components, review the plan, then confirm. No Terminal commands need to be typed.

Recordings are preserved. Shared BlackHole/FFmpeg/Homebrew/Apple tools are retained. Removing unused Sawti virtual devices is optional and needs a separate approval. Review the final report, then empty Trash to reclaim space. Actual Mac Studio uninstall qualification is pending; see the linked guide before using it on a studio installation.
