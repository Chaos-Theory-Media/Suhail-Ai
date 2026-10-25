# Sawti 3.0.2 (صوتي): studio agents for IMI podcasts

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
In Audition, create a **48 kHz multitrack session**:
* **Podcast:** three **mono** tracks named *Mic 1, Mic 2, Mic 3*, inputs Scarlett 1, 2, 3, all armed (R).
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

**To close Sawti:** press **Quit** on the page. Closing the browser tab releases its voice capture but leaves the control server running; use Quit for complete exit. Terminal signals have cleanup handlers, but an uncatchable crash still requires qualification.

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
* **Focusrite Control 2 has no public interface for other apps.** Routing is stored in the Scarlett, so save a
  preset per show in Focusrite Control 2. Sawti's pre-test observes monitored inputs; it does not prove Audition track routing or Zoom talkback privacy. Verify those manually.
* **Audition has no automation interface on macOS.** Sawti uses your template files and presses Record or Stop
  with keystrokes after you confirm.
* **Zoom does not reveal which audio devices it is using.** Sawti shows the exact settings to choose and asks
  you to confirm once per day.
* Sawti is an in-house tool and is not notarised by Apple, so step 2 of the setup is needed.

Technical details for IT: **TECHNICAL.md**. What changed since 2.2: **CHANGES.md**.

## Clean uninstall

Open **Uninstall Sawti** from the Desktop or Applications, or double-click **UNINSTALL_SAWTI.command** from the current source folder. Stop recording first, select the components, review the plan, then confirm. No Terminal commands need to be typed.

Recordings are preserved. Shared BlackHole/FFmpeg/Homebrew/Apple tools are retained. Removing unused Sawti virtual devices is optional and needs a separate approval. Review the final report, then empty Trash to reclaim space. Actual Mac Studio uninstall qualification is pending; see the linked guide before using it on a studio installation.
