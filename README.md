# Sawti 3.0 (صوتي): studio agents for IMI podcasts

Sawti prepares the studio, runs the sound check, opens the right Audition session, watches levels during the
show and masters the episode. The person running the show presses a few buttons. Sawti handles the technical
setup.

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
  *Fix everything I can*.

Save the session. In Sawti, open **Prepare › Save the show template** and drag the .sesx file into the box.
Press **Use as show template**. From then on, Sawti creates a dated copy of this template for every show.

---

## Every show

Open **Sawti** from the Desktop and press **Switch Sawti ON**. Choose **Podcast** or **Zoom Show**. Then follow
the tabs:

| Tab | What you do | What Sawti does |
|---|---|---|
| **1 · Prepare** | Press **Fix everything I can**. Tick the blue items after checking them. Press **Open in Audition**. | Sets 48 kHz, creates or repairs the Zoom audio devices, keeps the Mac awake, prepares today's session with the right name and folder, and opens it in Audition. |
| **2 · Pre-test** | Press **Start pre-test** and follow the instructions (each person talks, then talkback, the Zoom guest, then a 10-second test recording). | Checks that every voice arrives on the right input at the right level and tells you which knob to turn and by how much. Catches swapped cables, talkback leaking into recordings, silent mics and macOS permission blocks. |
| **3 · Live** | Press **Go live**, then **● Record**. | Watches every mic and warns you if one gets too quiet, too loud or clips. It refuses any device change while you are live. |
| **4 · After the show** | Press **End show**, then **Mix & master selected tracks**. | Levels each speaker, closes mics that only pick up someone else, mixes, and masters to **−16 LUFS / −1 dBTP**. The originals are never changed. |

**Ask Sawti** (right side) understands English and Arabic: *"check the studio"*, *"how are the levels?"*,
*"صوتي، هل برنامج أوديشن يعمل؟"*. Answers come with buttons, so you can act straight away.

**To close Sawti:** press **Quit** on the page. Closing the browser tab or a Terminal window does not leave
anything running in the background.

---

## How Sawti learns
* It learns **when shows usually happen**. About 45 minutes before a predicted show it runs the checks, applies
  approved fixes and prepares the session, then tells you what it did.
* It learns **how you name sessions** (for example `IMI_Talks_2026-10-25`) and where you save them.
* When you apply the same fix **twice**, it offers to do that fix automatically from then on. You can switch
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
  knob to turn and by how many dB. It confirms the result in the sound check. The optional *inline leveler*
  (Settings) can ride levels in software, but it is **off by default**. Test it outside live shows first.
* **Focusrite Control 2 has no public interface for other apps.** Routing is stored in the Scarlett, so save a
  preset per show in Focusrite Control 2. Sawti's pre-test proves the result (for example, that talkback is not
  on any recorded mic).
* **Audition has no automation interface on macOS.** Sawti uses your template files and presses Record or Stop
  with keystrokes after you confirm.
* **Zoom does not reveal which audio devices it is using.** Sawti shows the exact settings to choose and asks
  you to confirm once per day.
* Sawti is an in-house tool and is not notarised by Apple, so step 2 of the setup is needed.

Technical details for IT: **TECHNICAL.md**. What changed since 2.2: **CHANGES.md**.
