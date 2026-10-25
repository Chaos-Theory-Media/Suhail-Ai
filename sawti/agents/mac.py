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
        F.append(finding("mic_permission", AGENT, "fail", "macOS is blocking the microphones for Sawti",
                         "Every input is exact digital silence — that is a permission block, not the gain knobs. "
                         "Allow 'Terminal' (or 'Sawti') under Privacy & Security › Microphone, then press Start again.",
                         "open_mic_privacy", "Open microphone settings"))
    if not app_running(apps, "focusrite control"):
        F.append(finding("fc2_app", AGENT, "info", "Focusrite Control 2 is closed",
                         "Not required to record (routing is stored in the Scarlett), but needed to change routing.",
                         "open_focusrite", "Open it"))
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
    studio.open_app("Focusrite Control 2")
    return "Opening Focusrite Control 2."


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
    Action("open_focusrite", "Open Focusrite Control 2", open_focusrite, safe=True, live_safe=True, agent=AGENT),
    Action("open_zoom", "Open Zoom", open_zoom, safe=True, live_safe=True, agent=AGENT),
    Action("open_audio_midi", "Open Audio MIDI Setup", open_audio_midi, live_safe=True, agent=AGENT),
]
