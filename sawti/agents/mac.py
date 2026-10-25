"""Mac Studio agent: disk space where recordings go, sleep prevention, microphone/automation permissions,
the apps the show needs, CPU and memory."""
import shutil
from pathlib import Path

from . import Action, finding

AGENT = "Mac"


def app_running(names, *needles):
    return any(any(n in p for n in needles) for p in names)


def _existing(path):
    p = Path(path).expanduser()
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def disk(path, channels=4):
    usage = shutil.disk_usage(str(_existing(path)))
    bytes_per_hour = 48000 * 3 * max(1, channels) * 3600  # 24-bit
    return usage.free, usage.free / bytes_per_hour


def check(studio, mode, meter, apps):
    F = []
    root = studio.settings("recording_root")
    free, hours = disk(root, 6 if mode == "zoom" else 4)
    gb = free / 1024 ** 3
    sev = "fail" if gb < 5 else "warn" if hours < 3 else "ok"
    F.append(finding("disk", AGENT, sev, f"{gb:.0f} GB free where recordings are saved (≈{hours:.0f} h of show)",
                     f"Recording folder: {root}" if sev == "ok" else
                     f"Free space on the drive holding {root}, or choose another recording folder in Settings."))
    if studio.lifecycle.awake.running():
        F.append(finding("awake", AGENT, "ok", "Mac will not sleep during the show"))
    else:
        F.append(finding("awake", AGENT, "warn" if studio.live else "info", "Mac may go to sleep during a long show",
                         "", "keep_awake", "Keep the Mac awake"))
    if meter.get("running") and meter.get("digital_silence"):
        F.append(finding("mic_permission", AGENT, "fail", "All inputs report digital silence; cause unverified",
                         "Silence can come from a muted/disconnected source, routing, or microphone permissions. "
                         "Check the signal path and Privacy & Security › Microphone; do not assume a cause.",
                         "open_mic_privacy", "Open microphone settings"))
    classic_running = any(Path(name).name.lower().replace(' ', '') == 'focusritecontrol' for name in apps)
    if not classic_running:
        F.append(finding("focusrite_app", AGENT, "info", "Focusrite Control is closed",
                         "Scarlett 18i8 3rd Generation uses the original Focusrite Control, not Focusrite Control 2. "
                         "Opening the app does not authorise a routing/preset change.", "open_focusrite", "Open Focusrite Control"))
    if mode == "zoom" and not app_running(apps, "zoom.us", "zoom workplace"):
        F.append(finding("zoom_app", AGENT, "warn", "Zoom is not open", "", "open_zoom", "Open Zoom"))
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().available / 1024 ** 3
        if cpu > 85:
            F.append(finding("cpu", AGENT, "warn", f"Mac is busy ({cpu:.0f}% CPU)",
                             "Close video apps, browser tabs and exports before recording."))
        if mem < 2:
            F.append(finding("memory", AGENT, "warn", f"Low free memory ({mem:.1f} GB)",
                             "Close apps you do not need for the show."))
    except Exception:
        pass
    if studio.accessibility_ok is False:
        F.append(finding("accessibility", AGENT, "warn", "Sawti cannot press Record in Audition yet",
                         "Allow 'Terminal' (or 'Sawti') under Privacy & Security › Accessibility.",
                         "open_accessibility", "Open Accessibility settings"))
    return F


def keep_awake(studio):
    studio.lifecycle.keep_awake(True)
    return "The Mac will stay awake while Sawti is on."


def open_mic_privacy(studio):
    studio.open_url("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
    return "Opened Privacy & Security › Microphone."


def open_accessibility(studio):
    studio.open_url("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
    return "Opened Privacy & Security › Accessibility."


def open_focusrite(studio):
    if studio.audio.simulated:
        studio.sim_apps.add('focusrite control')
        return '(simulation) Focusrite Control opened.'
    if any(Path(name).name.lower().replace(' ', '') == 'focusritecontrol' for name in studio.running_apps()):
        return 'Focusrite Control is already running; its settings were left unchanged.'
    from ..applications import discover
    app = discover('focusrite')
    if not app:
        raise RuntimeError('The original Focusrite Control was not found. Scarlett 18i8 3rd Generation requires '
                           'Focusrite Control from Focusrite’s official downloads, not Control 2.')
    studio.open_app(app['path'])
    return 'Requested launch of Focusrite Control. No routing, preset or sample-rate command was sent.'


def open_studio_apps(studio):
    from . import audition
    tasks = [('Focusrite Control', open_focusrite), ('Adobe Audition', audition.open_application)]
    if studio.mode == 'zoom':
        tasks.append(('Zoom', open_zoom))
    results = []
    failures = []
    for name, fn in tasks:
        try:
            results.append(fn(studio))
        except (RuntimeError, OSError) as exc:
            failures.append('%s: %s' % (name, exc))
    if failures:
        raise RuntimeError('Some studio applications could not open. ' + ' '.join(results + failures))
    return ' '.join(results)


def open_zoom(studio):
    studio.open_app("zoom.us")
    return "Opening Zoom."


def open_audio_midi(studio):
    studio.open_app("Audio MIDI Setup")
    return "Opening Audio MIDI Setup."


ACTIONS = [
    Action("keep_awake", "Keep the Mac awake", keep_awake, safe=True, live_safe=True, agent=AGENT),
    Action("open_mic_privacy", "Open microphone settings", open_mic_privacy, live_safe=True, agent=AGENT),
    Action("open_accessibility", "Open Accessibility settings", open_accessibility, live_safe=True, agent=AGENT),
    Action("open_focusrite", "Open Focusrite Control", open_focusrite, agent=AGENT,
           impact='Opens the original Focusrite Control. Check recording is idle; no preset or routing changes are requested.'),
    Action('open_studio_apps', 'Open studio applications', open_studio_apps, agent=AGENT,
           impact='Opens Focusrite Control and Audition (also Zoom in Zoom mode). Their audio engines may activate. '
                  'Check recording is idle. No session, transport, sample-rate or routing changes are requested.'),
    Action("open_zoom", "Open Zoom", open_zoom, agent=AGENT,
           impact="Starts Zoom, which may activate its configured microphone and speaker devices."),
    Action("open_audio_midi", "Open Audio MIDI Setup", open_audio_midi, live_safe=True, agent=AGENT),
]
