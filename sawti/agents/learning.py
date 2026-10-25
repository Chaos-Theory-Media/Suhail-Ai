"""Learning agent: watches what the team does and makes the next show simpler.

What it learns (all local, from Sawti's own event log and an optional recordings-folder scan):
  * when shows happen (weekday + hour) and which type  -> predicts the next show
  * how sessions are named and where they are saved     -> names and files sessions automatically
  * which fixes keep being needed                       -> after the 2nd time, offers to do them automatically
  * per-microphone gain habits                          -> warns before the show ("Mic 2 usually needs +6 dB")
What it does in advance (only 'safe' actions, never Record, never routing changes while live):
  * within 45 minutes of a predicted show: run checks, apply approved fixes, prepare today's session.
"""
import collections
import datetime
import re
import time
from pathlib import Path

AUTO_AFTER = 2           # a fix applied manually this many times becomes an auto-fix suggestion
PREP_WINDOW_MIN = 45
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MEDIA = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".sesx", ".m4a"}


# ------------------------------------------------------------------ naming
def token_shape(name):
    stem = Path(name).stem
    stem = re.sub(r"\d{4}[-_]\d{2}[-_]\d{2}", "{DATE}", stem)
    stem = re.sub(r"\d{8}", "{DATE8}", stem)
    stem = re.sub(r"\d+", "{N}", stem)
    return stem[:120]


def learned_pattern(studio, mode):
    names = [e.get("name") for e in studio.events("session_prepared") if e.get("mode") == mode and e.get("name")]
    names += [r[1] for r in studio.observations() if r[2] == ".sesx"]
    shapes = collections.Counter(token_shape(n) for n in names if "{DATE" in token_shape(n))
    return shapes.most_common(1)[0][0] if shapes else None


def suggest_name(studio, mode, when=None):
    when = when or datetime.date.today()
    pattern = learned_pattern(studio, mode)
    show = (studio.settings("show_name") or {}).get(mode) or ("Podcast" if mode == "local" else "Zoom Show")
    show = re.sub(r"[^\w\- ]+", "", show).strip().replace(" ", "_") or "Show"
    if pattern:
        n = len([e for e in studio.events("session_prepared") if e.get("mode") == mode]) + 1
        out = pattern.replace("{DATE}", when.isoformat()).replace("{DATE8}", when.strftime("%Y%m%d"))
        return out.replace("{N}", f"{n:02d}", 1).replace("{N}", "1")
    return f"{show}_{when.isoformat()}"


# ------------------------------------------------------------------ schedule
def predict_next(studio, now=None):
    """Most likely next show from past show starts: same weekday & hour seen at least twice."""
    now = now or datetime.datetime.now()
    starts = studio.events("show_started")
    slots = collections.Counter()
    modes = collections.defaultdict(collections.Counter)
    for e in starts:
        t = datetime.datetime.fromtimestamp(e["ts"])
        slots[(t.weekday(), t.hour)] += 1
        modes[(t.weekday(), t.hour)][e.get("mode", "local")] += 1
    best = None
    for (wd, hour), count in slots.items():
        if count < 2:
            continue
        days = (wd - now.weekday()) % 7
        cand = (now + datetime.timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
        if cand < now - datetime.timedelta(hours=1):
            cand += datetime.timedelta(days=7)
        if best is None or cand < best[0]:
            mode, mcount = modes[(wd, hour)].most_common(1)[0]
            best = (cand, mode, count, mcount)
    if not best:
        return None
    cand, mode, count, mcount = best
    return dict(at=cand.isoformat(timespec="minutes"), label=f"{DAYS[cand.weekday()]} {cand:%H:%M}", mode=mode,
                seen=count, confidence=round(mcount / count, 2),
                minutes_away=round((cand - now).total_seconds() / 60))


# ------------------------------------------------------------------ fixes & habits
def fix_counts(studio):
    return collections.Counter(e.get("action") for e in studio.events("fix_applied") if e.get("by") == "operator")


def autofix_suggestions(studio):
    approved = studio.settings("autofix") or {}
    out = []
    for action, n in fix_counts(studio).items():
        a = studio.actions.get(action)
        if a and a.safe and n >= AUTO_AFTER and action not in approved:
            out.append(dict(action=action, label=a.label, times=n))
    return out


def gain_habits(studio):
    """Average dB correction Sawti had to ask for, per source, over recent shows."""
    per_day = collections.defaultdict(lambda: collections.defaultdict(list))
    for e in studio.events("gain_advice", since=time.time() - 60 * 86400):
        if e.get("delta") is not None:
            day = datetime.date.fromtimestamp(e["ts"]).isoformat()
            per_day[(e.get("mode"), e.get("source"))][day].append(float(e["delta"]))
    out = []
    for (mode, src), days in per_day.items():
        vals = [sum(v) / len(v) for v in days.values()]  # one vote per show day
        if len(vals) >= 2:
            avg = sum(vals) / len(vals)
            if abs(avg) >= 3:
                out.append(dict(mode=mode, source=src, avg_delta=round(avg), times=len(vals)))
    return out


def tips_for(studio, mode):
    tips = []
    names = {s["id"]: s["name"] for s in studio.profile(mode)["sources"]}
    for h in gain_habits(studio):
        if h["mode"] == mode and h["source"] in names:
            word = "up" if h["avg_delta"] > 0 else "down"
            tips.append(f"{names[h['source']]} usually needs about {abs(h['avg_delta'])} dB {word} — "
                        f"set its gain before the guests arrive.")
    return tips


# ------------------------------------------------------------------ folder scan (metadata only)
BLOCKED = {Path("/"), Path("/System"), Path("/Library"), Path("/Applications"), Path("/Users")}


def scan_folder(studio, folder, max_entries=20000, max_seconds=8):
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("That folder does not exist.")
    if root in BLOCKED or root == Path.home():
        raise ValueError("Choose the folder where recordings are kept, not a whole drive or home folder.")
    rows, seen, t0 = [], 0, time.time()
    for p in root.rglob("*"):
        seen += 1
        if seen > max_entries or time.time() - t0 > max_seconds:
            break
        try:
            if p.suffix.lower() in MEDIA and p.is_file() and not p.is_symlink():
                st = p.stat()
                rows.append((str(p), str(p.parent), p.name, p.suffix.lower(), st.st_mtime, time.time()))
        except OSError:
            continue
    studio.save_observations(rows)
    studio.put_setting("learning_folder", str(root))
    return dict(files=len(rows), stopped_early=seen > max_entries or time.time() - t0 > max_seconds)


# ------------------------------------------------------------------ summary
def insights(studio):
    mode = studio.mode
    pred = predict_next(studio)
    shows = studio.events("show_started")
    issues = collections.Counter(e.get("action") for e in studio.events("fix_applied"))
    folders = collections.Counter(r[0] for r in studio.observations())
    return dict(
        shows_logged=len(shows),
        next_show=pred,
        suggested_name=suggest_name(studio, mode),
        naming_pattern=learned_pattern(studio, mode),
        top_folder=folders.most_common(1)[0][0] if folders else None,
        autofix=studio.settings("autofix") or {},
        autofix_suggestions=autofix_suggestions(studio),
        recurring_fixes=[dict(action=a, times=n, label=studio.actions[a].label if a in studio.actions else a)
                         for a, n in issues.most_common(5) if a],
        tips=tips_for(studio, mode),
        auto_prepare=studio.settings("auto_prepare"),
    )


def tick(studio):
    """Called every minute while Sawti is ON: prepare a predicted show in advance."""
    if not studio.lifecycle.on or not studio.settings("auto_prepare") or studio.live:
        return None
    pred = predict_next(studio)
    if not pred or not (0 <= pred["minutes_away"] <= PREP_WINDOW_MIN) or pred["confidence"] < 0.6:
        return None
    key = f"{pred['at']}"
    if studio.state.get("auto_prepared") == key:
        return None
    studio.state["auto_prepared"] = key
    if studio.mode != pred["mode"]:
        studio.notify(f"A {pred['mode']} show is predicted. Choose its mode manually before preparation.")
        return None
    done = studio.run_autofixes(reason="auto-prep")
    try:
        from . import audition
        done.append(audition.prepare_session(studio, pred["mode"]))
    except Exception as exc:
        done.append(f"Session not prepared: {exc}")
    studio.notify(f"Getting ready for the {pred['label']} {'Zoom show' if pred['mode'] == 'zoom' else 'podcast'}: "
                  + " ".join(done), "info")
    studio.learn("auto_prepared", mode=pred["mode"], actions=len(done))
    return done
