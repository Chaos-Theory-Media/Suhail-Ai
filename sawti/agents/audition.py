"""Audition agent: session templates, preparing today's session (right tracks, inputs and armed state come
from the template), opening it, and Record / Stop by keystroke with confirmation.

Adobe offers no supported scripting API for Audition on macOS, so Sawti works with Audition's own files:
the operator sets the tracks up once and saves it as the show template; Sawti copies that template into a
dated, correctly named session folder for every show and opens it. Recorded takes then land in that folder.
"""
import datetime
import glob
import os
import plistlib
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import Action, finding

AGENT = "Audition"
_bundle_cache = {}


# ------------------------------------------------------------------ app discovery
def find_app():
    if "app" in _bundle_cache:
        return _bundle_cache["app"]
    cands = []
    try:
        r = subprocess.run(["/usr/bin/mdfind", "kMDItemCFBundleIdentifier == 'com.adobe.Audition*'"],
                           capture_output=True, text=True, timeout=5)
        cands += [x for x in r.stdout.splitlines() if x.endswith(".app")]
    except (OSError, subprocess.TimeoutExpired):
        pass
    cands += sorted(glob.glob("/Applications/Adobe Audition*/Adobe Audition*.app"), reverse=True)
    app = None
    for c in cands:
        try:
            with open(os.path.join(c, "Contents", "Info.plist"), "rb") as f:
                bid = plistlib.load(f).get("CFBundleIdentifier")
            app = dict(path=c, bundle_id=bid or "com.adobe.Audition", name=Path(c).stem)
            break
        except OSError:
            continue
    _bundle_cache["app"] = app
    return app


# ------------------------------------------------------------------ session files
def parse_sesx(path):
    """Best-effort read of an Audition session: sample rate, tracks (name, mono/stereo, armed, input)."""
    root = ET.parse(str(path)).getroot()
    session = root.find(".//session")
    rate = session.get("sampleRate") if session is not None else None
    tracks = []
    for el in root.iter():
        tag = el.tag.lower()
        if tag != "audiotrack":
            continue
        name_el = el.find(".//trackParameters/name")
        if name_el is None:
            name_el = el.find(".//name")
        armed = None
        ctype = None
        inputs = []
        for sub in el.iter():
            for k, v in sub.attrib.items():
                kl = k.lower()
                if kl in ("recordarmed", "armed", "recordenabled"):
                    armed = v.lower() == "true"
                if kl == "audiochanneltype" and sub is not el:
                    ctype = v
            if "input" in sub.tag.lower():
                inputs.append({k: v for k, v in sub.attrib.items()})
        tracks.append(dict(name=(name_el.text or "").strip() if name_el is not None else "", channels=ctype,
                           armed=armed, inputs=inputs))
    return dict(path=str(path), sample_rate=int(float(rate)) if rate else None, tracks=tracks)


def template_info(studio, mode):
    t = (studio.settings("templates") or {}).get(mode)
    if not t or not Path(t).is_file():
        return None
    try:
        return parse_sesx(t)
    except (ET.ParseError, OSError) as exc:
        return dict(path=t, error=f"Template could not be read: {exc}", tracks=[])


def adopt_template(studio, mode, source):
    """Copy an Audition session the operator set up into Sawti's template store for this show type."""
    from .. import paths
    src = Path(source).expanduser()
    if not src.is_file() or src.suffix.lower() != ".sesx":
        raise ValueError("Choose an Audition session file (.sesx).")
    info = parse_sesx(src)
    if not info["tracks"]:
        raise ValueError("That session has no audio tracks.")
    dst = paths.templates_dir() / f"{mode}_template.sesx"
    shutil.copy2(src, dst)
    t = studio.settings("templates") or {}
    t[mode] = str(dst)
    studio.put_setting("templates", t)
    studio.learn("template_saved", mode=mode, tracks=len(info["tracks"]))
    return info


def today_session(studio, mode):
    s = studio.state.get("session")
    if s and s.get("mode") == mode and s.get("date") == datetime.date.today().isoformat() and Path(s["path"]).exists():
        return s
    return None


def prepare_session(studio, mode=None, title=None):
    mode = mode or studio.mode
    tpl = (studio.settings("templates") or {}).get(mode)
    if not tpl or not Path(tpl).is_file():
        raise RuntimeError("No Audition template saved for this show yet. Set up the tracks in Audition once, "
                           "save the session, then choose it under Audition › Save as show template.")
    existing = today_session(studio, mode)
    if existing:
        return f"Today's session is ready: {existing['name']}"
    from . import learning
    name = title or learning.suggest_name(studio, mode)
    root = Path(studio.settings("recording_root")).expanduser()
    folder = root / str(datetime.date.today().year) / name
    n = 2
    while folder.exists() and any(folder.iterdir()):
        folder = root / str(datetime.date.today().year) / f"{name}_{n}"
        n += 1
    folder.mkdir(parents=True, exist_ok=True)
    sesx = folder / f"{folder.name}.sesx"
    shutil.copy2(tpl, sesx)
    studio.state["session"] = dict(mode=mode, path=str(sesx), folder=str(folder), name=folder.name,
                                   date=datetime.date.today().isoformat(), prepared=time.time())
    studio.save_state()
    studio.learn("session_prepared", mode=mode, name=folder.name, folder=str(root))
    return f"Prepared {folder.name} from the {mode} template."


def open_session(studio):
    s = today_session(studio, studio.mode)
    if not s:
        prepare_session(studio)
        s = today_session(studio, studio.mode)
    app = find_app()
    if studio.audio.simulated:
        studio.sim_apps.add("adobe audition")
        return f"(simulation) Opened {s['name']} in Audition."
    if app:
        subprocess.run(["/usr/bin/open", "-b", app["bundle_id"], s["path"]], check=False, timeout=15)
    else:
        subprocess.run(["/usr/bin/open", s["path"]], check=False, timeout=15)
    studio.learn("session_opened", mode=studio.mode)
    return f"Opening {s['name']} in Audition. Check the armed tracks show the right inputs."


# ------------------------------------------------------------------ transport (keystrokes)
def _keystroke(studio, script_keys):
    app = find_app()
    bid = app["bundle_id"] if app else "com.adobe.Audition"
    script = (f'tell application id "{bid}" to activate\n'
              'delay 0.4\n'
              f'tell application "System Events" to {script_keys}')
    r = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        if "1002" in r.stderr or "1719" in r.stderr or "not allowed" in r.stderr.lower():
            studio.accessibility_ok = False
            raise RuntimeError("macOS blocked the keystroke. Allow Terminal (or Sawti) under Privacy & Security › "
                               "Accessibility, then try again.")
        raise RuntimeError(r.stderr.strip() or "Audition did not respond.")
    studio.accessibility_ok = True


def _wavs(folder):
    return {p: p.stat().st_size for p in Path(folder).rglob("*.wav")} if folder and Path(folder).exists() else {}


def record(studio):
    s = today_session(studio, studio.mode)
    before = _wavs(s["folder"]) if s else {}
    if studio.audio.simulated:
        studio.go_live(source="sawti")
        return "(simulation) Recording started."
    _keystroke(studio, "keystroke space using shift down")  # Audition: Shift+Space = Record
    studio.go_live(source="sawti")

    def verify():
        time.sleep(6)
        after = _wavs(s["folder"]) if s else {}
        grew = any(after.get(p, 0) > before.get(p, 0) for p in after)
        studio.notify("Recording confirmed: new audio is being written." if grew else
                      "I pressed Record but no new audio appeared in the session folder. Check Audition now.",
                      "ok" if grew else "fail")
    if s:
        threading.Thread(target=verify, daemon=True).start()
    return "Record pressed in Audition."


def stop(studio):
    if not studio.audio.simulated:
        _keystroke(studio, "keystroke space")  # Space = Stop
    studio.end_live()
    return "Stop pressed in Audition."


def check(studio, mode, apps):
    from .mac import app_running
    F = []
    info = template_info(studio, mode)
    if not info:
        F.append(finding("template", AGENT, "warn", "No Audition template saved for this show",
                         "Set the tracks up once in Audition (inputs, mono/stereo, armed), save the session, then "
                         "choose it under Audition › Save as show template. Sawti reuses it for every show."))
    elif info.get("error"):
        F.append(finding("template", AGENT, "fail", "Show template cannot be read", info["error"]))
    else:
        need = len(studio.profile(mode).get("audition_tracks", []))
        armed = [t for t in info["tracks"] if t["armed"]]
        if len(info["tracks"]) < need:
            F.append(finding("template_tracks", AGENT, "warn",
                             f"Template has {len(info['tracks'])} tracks; this show needs {need}",
                             "Add the missing tracks in Audition and save the template again."))
        elif any(t["armed"] is not None for t in info["tracks"]) and len(armed) < need:
            F.append(finding("template_armed", AGENT, "warn", f"Only {len(armed)} tracks are armed for recording",
                             "Arm the tracks (R button) in Audition and save the template again."))
        else:
            F.append(finding("template", AGENT, "ok", f"Template ready: {len(info['tracks'])} tracks"
                             + (f" at {info['sample_rate'] // 1000} kHz" if info.get("sample_rate") else "")))
        if info.get("sample_rate") and info["sample_rate"] != 48000:
            F.append(finding("template_rate", AGENT, "warn", "Template session is not 48 kHz",
                             "Create the template as a 48 kHz session."))
        s = today_session(studio, mode)
        if not s:
            F.append(finding("session", AGENT, "warn", "Today's session is not prepared", "",
                             "prepare_session", "Prepare it"))
        else:
            F.append(finding("session", AGENT, "ok", f"Today's session: {s['name']}"))
    if not app_running(apps, "adobe audition"):
        if info and not info.get("error"):
            F.append(finding("audition_open", AGENT, "warn", "Adobe Audition is not open", "",
                             "open_session", "Open today's session"))
        else:
            F.append(finding("audition_open", AGENT, "warn", "Adobe Audition is not open",
                             "Open Audition to set up the show template."))
    return F


ACTIONS = [
    Action("prepare_session", "Prepare today's session", lambda st: prepare_session(st), safe=True, live_safe=True,
           agent=AGENT),
    Action("open_session", "Open session in Audition", open_session, safe=True, live_safe=False, agent=AGENT),
    Action("record", "Record in Audition", record, live_safe=True, agent=AGENT),
    Action("stop", "Stop recording", stop, live_safe=True, agent=AGENT),
]
