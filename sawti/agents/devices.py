"""Devices agent: Scarlett, BlackHole, the Sawti Show Input (aggregate) and Sawti Zoom Speaker (multi-output),
sample rates. Creates and repairs the virtual devices so nobody has to touch Audio MIDI Setup."""
from . import Action, finding
from ..coreaudio import (SHOW_INPUT_NAME, SHOW_INPUT_UID, ZOOM_SPEAKER_NAME, ZOOM_SPEAKER_UID, find_blackhole,
                         find_scarlett, find_uid, input_layout)

AGENT = "Devices"


def check(studio, mode, devs):
    F = []
    audio = studio.audio
    sc = find_scarlett(devs)
    if not sc:
        F.append(finding("scarlett", AGENT, "fail", "Scarlett 18i8 not detected",
                         "Check the USB cable and that the Scarlett is switched on. If it is connected, "
                         "open Focusrite Control 2 to wake it.", "open_focusrite", "Open Focusrite Control 2"))
    else:
        if sc["rate"] != 48000:
            F.append(finding("scarlett_rate", AGENT, "fail", f"Scarlett is at {sc['rate'] / 1000:g} kHz",
                             "Podcast sessions run at 48 kHz. Mismatched rates cause clicks and drift.",
                             "set_scarlett_48k", "Set to 48 kHz"))
        else:
            F.append(finding("scarlett", AGENT, "ok", "Scarlett 18i8 connected at 48 kHz"))
    if not audio.helper_available():
        F.append(finding("helper", AGENT, "warn", "Automatic device fixes unavailable",
                         "The Sawti audio helper is not installed, so Sawti can check but not create devices. "
                         "Re-run INSTALL_SAWTI.command (it needs Apple's Command Line Tools)."))
    if mode == "zoom":
        bh = find_blackhole(devs, 2)
        if not bh:
            F.append(finding("blackhole", AGENT, "fail", "BlackHole 2ch is not installed",
                             "BlackHole carries the Zoom guests into Audition. Ask IT to install "
                             "'BlackHole 2ch' (existential.audio) — it needs an administrator password once."))
        elif bh["rate"] != 48000:
            F.append(finding("blackhole_rate", AGENT, "fail", f"BlackHole is at {bh['rate'] / 1000:g} kHz",
                             "Set to 48 kHz to match the Scarlett.", "set_blackhole_48k", "Set to 48 kHz"))
        agg = find_uid(devs, SHOW_INPUT_UID, SHOW_INPUT_NAME)
        if sc and bh:
            if not agg:
                F.append(finding("show_input", AGENT, "fail", "Recording input for Zoom shows is missing",
                                 f"Sawti will create '{SHOW_INPUT_NAME}' (Scarlett inputs + Zoom guests) for Audition.",
                                 "create_show_input", "Create it"))
            else:
                lay = input_layout(agg, devs)
                if "scarlett" not in lay or "blackhole" not in lay:
                    F.append(finding("show_input", AGENT, "fail", f"'{SHOW_INPUT_NAME}' is incomplete",
                                     "One of its devices is missing (often after unplugging the Scarlett).",
                                     "repair_show_input", "Rebuild it"))
                elif agg["rate"] != 48000:
                    F.append(finding("show_input_rate", AGENT, "fail", f"'{SHOW_INPUT_NAME}' is not at 48 kHz", "",
                                     "set_show_input_48k", "Set to 48 kHz"))
                else:
                    F.append(finding("show_input", AGENT, "ok",
                                     f"'{SHOW_INPUT_NAME}' ready — Zoom guests on inputs "
                                     f"{lay['blackhole'] + 1}–{lay['blackhole'] + 2}"))
            zs = find_uid(devs, ZOOM_SPEAKER_UID, ZOOM_SPEAKER_NAME)
            if not zs:
                F.append(finding("zoom_speaker", AGENT, "fail", "Zoom speaker device is missing",
                                 f"Sawti will create '{ZOOM_SPEAKER_NAME}' so guests are heard in headphones "
                                 "AND recorded.", "create_zoom_speaker", "Create it"))
            else:
                F.append(finding("zoom_speaker", AGENT, "ok", f"'{ZOOM_SPEAKER_NAME}' ready"))
        F.append(finding("zoom_settings", AGENT, "manual", "Zoom audio settings",
                         f"Zoom › Settings › Audio: Speaker = '{ZOOM_SPEAKER_NAME}', Microphone = 'Scarlett 18i8 USB'. "
                         "Untick 'Automatically adjust microphone volume'. Turn on 'Original sound for musicians'."))
        F.append(finding("mix_minus", AGENT, "manual", "Guest cannot hear themselves (mix-minus)",
                         "Ask the Zoom guest to speak: they must not hear their own voice coming back."))
    F.append(finding("focusrite_preset", AGENT, "manual", "Focusrite Control 2 routing",
                     "Routing lives in the Scarlett. If anyone changed it, load the saved show preset in "
                     "Focusrite Control 2 (outputs 1–2 speakers, 3–4 headphone amp)."))
    F.append(finding("talkback", AGENT, "manual", "Talkback stays private",
                     "Speak into the talkback mic: you hear it in the headphones, it does not appear on any "
                     "recorded track or in Zoom. (The pre-test checks the recording side automatically.)"))
    return F


# ------------------------------------------------------------------ actions
def _sc_bh(studio):
    devs = studio.audio.devices()
    sc, bh = find_scarlett(devs), find_blackhole(devs, 2)
    if not sc:
        raise RuntimeError("Scarlett not connected.")
    return devs, sc, bh


def set_scarlett_48k(studio):
    _, sc, _ = _sc_bh(studio)
    studio.audio.set_rate(sc["uid"], 48000)
    return "Scarlett set to 48 kHz."


def set_blackhole_48k(studio):
    _, _, bh = _sc_bh(studio)
    if not bh:
        raise RuntimeError("BlackHole is not installed.")
    studio.audio.set_rate(bh["uid"], 48000)
    return "BlackHole set to 48 kHz."


def set_show_input_48k(studio):
    studio.audio.set_rate(SHOW_INPUT_UID, 48000)
    return "Show input set to 48 kHz."


def create_show_input(studio):
    _, sc, bh = _sc_bh(studio)
    if not bh:
        raise RuntimeError("Install BlackHole 2ch first.")
    for d in (sc, bh):
        if d["rate"] != 48000:
            studio.audio.set_rate(d["uid"], 48000)
    studio.audio.create_aggregate(SHOW_INPUT_NAME, SHOW_INPUT_UID, sc["uid"], [sc["uid"], bh["uid"]])
    return f"Created '{SHOW_INPUT_NAME}'. Audition records from it in Zoom shows."


def repair_show_input(studio):
    studio.audio.destroy(SHOW_INPUT_UID)
    return create_show_input(studio)


def create_zoom_speaker(studio):
    _, sc, bh = _sc_bh(studio)
    if not bh:
        raise RuntimeError("Install BlackHole 2ch first.")
    studio.audio.create_aggregate(ZOOM_SPEAKER_NAME, ZOOM_SPEAKER_UID, sc["uid"], [sc["uid"], bh["uid"]],
                                  stacked=True)
    return f"Created '{ZOOM_SPEAKER_NAME}'. Select it as the Speaker in Zoom."


ACTIONS = [
    Action("set_scarlett_48k", "Set Scarlett to 48 kHz", set_scarlett_48k, safe=True, agent=AGENT),
    Action("set_blackhole_48k", "Set BlackHole to 48 kHz", set_blackhole_48k, safe=True, agent=AGENT),
    Action("set_show_input_48k", "Set show input to 48 kHz", set_show_input_48k, safe=True, agent=AGENT),
    Action("create_show_input", "Create Sawti Show Input", create_show_input, safe=True, agent=AGENT),
    Action("repair_show_input", "Rebuild Sawti Show Input", repair_show_input, safe=True, agent=AGENT),
    Action("create_zoom_speaker", "Create Sawti Zoom Speaker", create_zoom_speaker, safe=True, agent=AGENT),
]
