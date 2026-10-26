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
from ..commissioning import require_plan, template_key, template_path

AGENT = "Audition"
_bundle_cache = {}


# ------------------------------------------------------------------ app discovery
def find_app():
    from ..applications import discover
    cached = _bundle_cache.get('app')
    if cached and Path(cached['path']).is_dir():
        return cached
    app = discover('audition')
    # A missing app must be discoverable after installation; do not cache None.
    if app:
        _bundle_cache['app'] = app
    return app


def open_application(studio):
    if studio.audio.simulated:
        studio.sim_apps.add('adobe audition')
        return '(simulation) Adobe Audition opened.'
    if any('audition' in name.lower() for name in studio.running_apps()):
        return 'Adobe Audition is already running; its current session was left unchanged.'
    app = find_app()
    if not app:
        raise RuntimeError('Adobe Audition was not found in Applications. Install/open it once with Creative Cloud, then retry.')
    studio.open_app(app['path'])
    return ('Requested launch of %s. Sawti did not request a session or recording command. '
            'Check any workspace restored by Audition.') % app['name']


# ------------------------------------------------------------------ session files
def parse_sesx(path):
    """Best-effort read of an Audition session: sample rate, tracks (name, mono/stereo, armed, input)."""
    if Path(path).stat().st_size > 8 * 1024 * 1024:
        raise ValueError('The session template exceeds the 8 MiB inspection limit.')
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
    t = template_path(studio, mode)
    if not t or not Path(t).is_file():
        return None
    try:
        return parse_sesx(t)
    except (ET.ParseError, OSError, ValueError) as exc:
        return dict(path=t, error=f"Template could not be read: {exc}", tracks=[])


def adopt_template(studio, mode, source):
    """Copy an Audition session the operator set up into Sawti's template store for this show type."""
    from .. import paths
    key = template_key(studio, mode)
    src = Path(source).expanduser()
    if not src.is_file() or src.suffix.lower() != ".sesx":
        raise ValueError("Choose an Audition session file (.sesx).")
    info = parse_sesx(src)
    if not info["tracks"]:
        raise ValueError("That session has no audio tracks.")
    if mode == 'local' and len(info['tracks']) != len(studio.mic_plan['inputs']):
        raise ValueError('Template audio-track count must match the confirmed programme microphones. '
                         'Input 4 must not be a recording track. Sawti has not changed the template.')
    dst = paths.templates_dir() / (key.replace(':', '_').replace(',', '-') + '_template.sesx')
    shutil.copy2(src, dst)
    t = studio.settings("templates") or {}
    t[key] = str(dst)
    studio.put_setting("templates", t)
    studio.learn("template_saved", mode=mode, tracks=len(info["tracks"]))
    return info


def today_session(studio, mode):
    s = studio.state.get("session")
    if mode == 'local' and (not studio.mic_plan or not s or s.get('microphone_plan') != studio.mic_plan):
        return None
    if s and s.get("mode") == mode and s.get("date") == datetime.date.today().isoformat() and Path(s["path"]).exists():
        return s
    return None


def prepare_session(studio, mode=None, title=None):
    mode = mode or studio.mode
    plan = require_plan(studio, mode)
    tpl = template_path(studio, mode)
    if not tpl or not Path(tpl).is_file():
        raise RuntimeError("No Audition template saved for this show yet. Set up the tracks in Audition once, "
                           "save the session, then choose it under Audition › Save as show template.")
    info = parse_sesx(tpl)
    if plan and len(info['tracks']) != len(plan['inputs']):
        raise RuntimeError('The template track count does not match the confirmed microphones. Save a matching template first.')
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
                                   microphone_plan=plan,
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
    if not s:
        raise RuntimeError('Prepare and verify the target session in Audition before recording. No keystroke was sent.')
    before = _wavs(s["folder"]) if s else {}
    if studio.audio.simulated:
        studio.go_live(source="sawti")
        return "(simulation) Recording started."
    studio.go_live(source="sawti")
    _keystroke(studio, "keystroke space using shift down")  # qualified shortcut must be checked on the target Mac

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
        if len(info["tracks"]) != need:
            F.append(finding("template_tracks", AGENT, "warn",
                             f"Template has {len(info['tracks'])} tracks; this show needs {need}",
                             "Save a matching template for the confirmed microphone selection; exclude talkback."))
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
                             "Open Audition to set up the show template.", 'open_audition', 'Open Adobe Audition'))
    return F


ACTIONS = [
    Action('open_audition', 'Open Adobe Audition', open_application, agent=AGENT,
           impact='Requests Audition launch, which may activate audio or restore its own workspace. '
                  'Sawti does not request a session. Check all recording is idle.'),
    Action("prepare_session", "Prepare today's session", lambda st: prepare_session(st), safe=True, live_safe=True,
           agent=AGENT),
    Action("open_session", "Open session in Audition", open_session, live_safe=False, agent=AGENT,
           impact="Activates Audition and opens a different session. Existing work may be interrupted."),
    Action("record", "Record in Audition", record, live_safe=True, agent=AGENT,
           impact="Sends a Record keystroke to Audition. Check focus, shortcuts and active session first."),
    Action("stop", "Stop recording", stop, live_safe=True, agent=AGENT,
           impact="Sends Space to Audition; this can STOP a recording or toggle playback. Check Audition first."),
]
