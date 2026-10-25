"""Levels agent: keeps every microphone in the window a high-end podcast needs while recording, and coaches
the operator in plain words ("Mic 2 is quiet: turn Gain 2 up about 6 dB").

Raw-track targets (24-bit recording, before mastering):
  speech short-term loudness ≈ -20 LUFS (good window -26 … -14), peaks below -6 dBFS, never clipping.
The finished episode is mastered afterwards to the house standard (-16 LUFS integrated, -1 dBTP).
"""
from . import finding

AGENT = "Levels"
LOW, VERY_LOW, HIGH = -26.0, -32.0, -14.0
HOT_PEAK, CLIP = -6.0, -0.5


def assess(src, target=-20.0):
    """One source from the meter snapshot -> status, short message, suggested dB change."""
    name = src["name"]
    knob = src.get("gain_knob")
    knob_txt = f"Gain {knob}" if knob else "its gain"
    if src.get("digital_zero"):
        return dict(status="dead", delta=None,
                    message=f"{name}: no signal at all — check the cable/mic is plugged into input "
                            f"{src['chans'][0] if src.get('chans') else ''}, and 48V if it is a condenser mic.")
    if src["clip"] or src["hold"] >= CLIP:
        return dict(status="clip", delta=-6.0,
                    message=f"{name} is clipping — turn {knob_txt} down about 6 dB now.")
    if src["role"] == "talkback":
        return dict(status="ok", delta=None, message=f"{name}: talkback (not recorded).")
    if not src["speaking"]:
        return dict(status="waiting", delta=None, message=f"{name}: waiting for speech.")
    st = src["short_term"]
    delta = round(target - st)
    if src["hold"] > HOT_PEAK and st > -18:
        return dict(status="hot", delta=min(delta, -3),
                    message=f"{name} is hot — turn {knob_txt} down about {abs(min(delta, -3))} dB.")
    if st < VERY_LOW:
        return dict(status="very_low", delta=delta,
                    message=f"{name} is far too quiet — turn {knob_txt} up about {delta} dB "
                            "(or move the mic closer, a fist away from the mouth).")
    if st < LOW:
        return dict(status="low", delta=delta, message=f"{name} is a bit quiet — turn {knob_txt} up about {delta} dB.")
    if st > HIGH:
        return dict(status="high", delta=delta, message=f"{name} is loud — turn {knob_txt} down about {abs(delta)} dB.")
    return dict(status="good", delta=0, message=f"{name}: level is good.")


def coach(studio, snapshot):
    target = studio.settings("speech_target")
    knobs = {s["id"]: s.get("gain_knob") for s in studio.profile(studio.mode)["sources"]}
    out = []
    for s in snapshot.get("sources", []):
        a = assess(dict(s, gain_knob=knobs.get(s["id"])), target)
        out.append(dict(id=s["id"], **a))
    return out


def check(studio, snapshot):
    F = []
    if not snapshot.get("running"):
        return F
    for c in coach(studio, snapshot):
        if c["status"] in ("clip", "dead"):
            F.append(finding(f"level_{c['id']}", AGENT, "fail", c["message"]))
        elif c["status"] in ("very_low", "hot", "high", "low"):
            F.append(finding(f"level_{c['id']}", AGENT, "warn", c["message"]))
    return F
