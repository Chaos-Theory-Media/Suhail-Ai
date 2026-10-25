"""Devices agent: Scarlett, BlackHole, the Sawti Show Input (aggregate) and Sawti Zoom Speaker (multi-output),
sample rates. Creates and repairs the virtual devices so nobody has to touch Audio MIDI Setup."""
from . import Action, finding
from ..coreaudio import (SHOW_INPUT_NAME, SHOW_INPUT_UID, ZOOM_SPEAKER_NAME, ZOOM_SPEAKER_UID, find_blackhole,
                         find_scarlett, find_uid, input_layout)

AGENT = "Devices"


def check(studio, mode, devs):
    F = []
    audio = studio.audio
    diagnostics = audio.diagnostics() if hasattr(audio, 'diagnostics') else {}
    query_failed = (diagnostics.get('queried') and not diagnostics.get('helper_ok')
                    and not diagnostics.get('portaudio_ok') and not diagnostics.get('system_profiler_ok'))
    if diagnostics.get('helper_error') or diagnostics.get('portaudio_error'):
        detail = '; '.join(str(diagnostics[k]) for k in ('helper_error', 'portaudio_error') if diagnostics.get(k))
        F.append(finding('audio_query', AGENT, 'warn', 'Audio query needs attention', detail))
    sc = find_scarlett(devs)
    if not sc:
        F.append(finding("scarlett", AGENT, 'warn' if query_failed else 'fail',
                         'Scarlett status is unknown — audio queries failed' if query_failed else 'Scarlett is not in Sawti’s audio device list',
                         "If Focusrite Control already sees the interface, leave its rate/routing unchanged. "
                         "Use Device diagnostics to inspect Sawti’s helper and PortAudio query results.",
                         "open_focusrite", "Open Focusrite Control"))
        F.append(finding('scarlett_rate', AGENT, 'manual', 'Scarlett sample rate is unverified',
                         'No reliable Scarlett rate observation is available. This does not mean the hardware rate is unset.'))
    else:
        if not sc.get('rate_verified', True) or not sc.get('rate'):
            F.append(finding('scarlett_rate', AGENT, 'manual', 'Scarlett operating rate is unverified',
                             'The helper is unavailable; PortAudio reports a default, not verified current state.'))
        elif sc["rate"] != 48000:
            F.append(finding("scarlett_rate", AGENT, "fail", f"Scarlett is at {sc['rate'] / 1000:g} kHz",
                             "Podcast sessions run at 48 kHz. Mismatched rates cause clicks and drift.",
                             "set_scarlett_48k" if sc.get('control_available', True) else None, "Set to 48 kHz"))
        else:
            F.append(finding("scarlett", AGENT, "ok", "Scarlett 18i8 connected at 48 kHz"))
        if sc.get('index') is None:
            F.append(finding('capture_index', AGENT, 'warn', 'Scarlett is visible, but capture is not yet available',
                             'Sawti cannot uniquely match it to the capture engine. Inspect Device diagnostics; do not change routing.'))
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
        elif not bh.get('rate_verified', True) or not bh.get('rate'):
            F.append(finding('blackhole_rate', AGENT, 'manual', 'BlackHole operating rate is unverified',
                             'A failed/default-only rate query does not authorise changing the rate.'))
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
                try:
                    lay = input_layout(agg, devs)
                except RuntimeError:
                    lay = {}
                if "scarlett" not in lay or "blackhole" not in lay:
                    F.append(finding("show_input", AGENT, "fail", f"'{SHOW_INPUT_NAME}' is incomplete",
                                     "One of its devices is missing (often after unplugging the Scarlett).",
                                     "repair_show_input", "Rebuild it"))
                elif not agg.get('rate_verified', True) or not agg.get('rate'):
                    F.append(finding('show_input_rate', AGENT, 'manual', 'Show input operating rate is unverified'))
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
    F.append(finding("focusrite_preset", AGENT, "manual", "Focusrite Control routing",
                     "Routing lives in the Scarlett. Inspect the existing preset in Focusrite Control. "
                     "Do not load or change a preset during production without explicit authorisation."))
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
    _, _, bh = _sc_bh(studio)
    if not bh:
        raise RuntimeError('BlackHole 2ch is unavailable; existing aggregate was not removed.')
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
    Action("set_scarlett_48k", "Set Scarlett to 48 kHz", set_scarlett_48k, agent=AGENT,
           impact="Changes the Scarlett hardware sample rate; may interrupt every app using it."),
    Action("set_blackhole_48k", "Set BlackHole to 48 kHz", set_blackhole_48k, agent=AGENT,
           impact="Changes the BlackHole sample rate; may interrupt Zoom or recording."),
    Action("set_show_input_48k", "Set show input to 48 kHz", set_show_input_48k, agent=AGENT,
           impact="Changes the aggregate sample rate; may interrupt connected audio apps."),
    Action("create_show_input", "Create Sawti Show Input", create_show_input, agent=AGENT,
           impact="Creates an aggregate and may change Scarlett/BlackHole sample rates to 48 kHz."),
    Action("repair_show_input", "Rebuild Sawti Show Input", repair_show_input, agent=AGENT,
           impact="Deletes and recreates Sawti Show Input; interrupts apps using that device."),
    Action("create_zoom_speaker", "Create Sawti Zoom Speaker", create_zoom_speaker, agent=AGENT,
           impact="Creates a shared Scarlett/BlackHole output device. Verify routing before use."),
]
