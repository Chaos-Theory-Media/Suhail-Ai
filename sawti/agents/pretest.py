"""Pre-test wizard: a guided sound check that proves the studio is ready, one step at a time.

1  Studio checks (devices, Mac, Audition) with one-click fixes
2  Each microphone in turn: right input? level in the podcast window? clipping? (coaches the gain)
3  Talkback: arrives on its own input and nowhere in the recorded microphones
4  Zoom guest return level (Zoom shows)
5  Test recording: confirms new audio was written and every track has signal
"""
import time
from pathlib import Path

from . import levels, post

STEP_TIMEOUT = 40


class Pretest:
    def __init__(self, studio):
        self.studio = studio
        self.steps = []
        self.i = 0
        self.active = False
        self.step_started = 0
        self.advised = set()

    # ------------------------------------------------------------ build
    def start(self):
        st = self.studio
        st.require_on()
        speech = st.presenter_speech.snapshot()
        if speech['phase'] in ('preparing', 'speaking') and not speech['enabled']:
            raise RuntimeError('Finish or mute the private headset test before the sound check.')
        from ..commissioning import require_plan
        require_plan(st)
        if st.live:
            raise RuntimeError('Run the sound check before the live show.')
        prof = st.profile(st.mode)
        steps = [dict(id="checks", kind="checks", title="Studio checks",
                      instruction="Sawti checks devices, the Mac and Audition. Fix anything red, then press Next.")]
        for s in prof["sources"]:
            if s["role"] == "programme":
                steps.append(dict(id=f"mic:{s['id']}", kind="mic", source=s["id"], title=f"Sound check · {s['name']}",
                                  instruction=f"Ask the person on {s['name']} to talk normally for about 10 seconds "
                                              "(name, what they had for breakfast)."))
        tb = next((s for s in prof["sources"] if s["role"] == "talkback"), None)
        if tb:
            steps.append(dict(id="talkback", kind="talkback", source=tb["id"], title="Talkback check",
                              instruction="Speak into the talkback mic for 5 seconds. Everyone in headphones should "
                                          "hear you; it must not show on any recorded mic."))
        rem = next((s for s in prof["sources"] if s["role"] == "remote"), None)
        if rem:
            steps.append(dict(id="remote", kind="remote", source=rem["id"], title="Zoom guest check",
                              instruction="Ask the Zoom guest to talk for 10 seconds. Ask them: can you hear us, and "
                                          "do you hear yourself echoing? (You should not.)"))
        steps.append(dict(id="record", kind="record", title="Test recording",
                          instruction="Record 10 seconds in Audition with everyone speaking, then stop. Press "
                                      "'Check the test recording'."))
        for s in steps:
            s.update(status="pending", detail="", advice=[])
        self.steps, self.i, self.active, self.advised = steps, 0, True, set()
        st.ensure_meter()
        if not st.monitor.running:
            self.active = False
            raise RuntimeError(st.monitor.error or 'Meters could not start; pre-test did not start.')
        self._enter()
        st.learn("pretest_started", mode=st.mode)
        return self.state()

    def _enter(self):
        step = self.steps[self.i]
        step["status"] = "running"
        self.step_started = time.monotonic()
        self.studio.monitor.mark("pretest")
        self.studio.monitor.sim_focus = step.get("source") if step["kind"] in ("mic", "talkback", "remote") else None

    # ------------------------------------------------------------ evaluate
    def _evaluate(self):
        step = self.steps[self.i]
        st = self.studio
        kind = step["kind"]
        snapshot = st.monitor.snapshot()
        if kind not in ('checks', 'record') and (not snapshot['running'] or snapshot.get('stale')):
            step.update(status='fail', detail='No fresh meter samples. Signal checks are unverified.')
            return
        if kind == "checks":
            findings = st.check_all()
            fails = [f for f in findings if f["severity"] == "fail"]
            step["findings"] = [f for f in findings if f["severity"] in ("fail", "warn")]
            step["status"] = "fail" if fails else "pass"
            step["detail"] = (f"{len(fails)} problem(s) to fix" if fails else "All automatic checks passed")
            return
        if kind == "record":
            return
        stats = st.monitor.mark_stats("pretest")
        if not stats:
            step["detail"] = "Meters are not running."
            return
        me = stats["sources"].get(step["source"], {})
        elapsed = stats["elapsed"]
        others = {k: v for k, v in stats["sources"].items() if k != step["source"]}
        names = {s["id"]: s["name"] for s in st.profile(st.mode)["sources"]}
        if kind in ("mic", "remote"):
            if me.get("active_s", 0) >= 3:
                fake = dict(name=names.get(step["source"], step["source"]), role="programme", speaking=True,
                            short_term=me["avg_st"], hold=me["max_peak"], clip=me["clips"] > 0,
                            gain_knob=next((s.get("gain_knob") for s in st.profile(st.mode)["sources"]
                                            if s["id"] == step["source"]), None))
                a = levels.assess(fake, st.settings("speech_target"))
                louder = [k for k, v in others.items() if v.get("active_s", 0) >= 3
                          and v.get("avg_st", -120) > me["avg_st"] + 10 and k != "talkback"]
                if louder:
                    step["status"] = "fail"
                    step["detail"] = (f"The voice is much louder on {names.get(louder[0])} than on "
                                      f"{fake['name']} — the cables or inputs are probably swapped.")
                elif a["status"] == "good":
                    step["status"] = "pass"
                    step["detail"] = f"Good level ({me['avg_st']} LUFS, peaks {me['max_peak']} dBFS)."
                else:
                    step["status"] = "warn"
                    step["detail"] = a["message"] + " Then press Retest."
                    if a["delta"] is not None and step["id"] not in self.advised:
                        self.advised.add(step["id"])
                        st.learn("gain_advice", mode=st.mode, source=step["source"], delta=a["delta"])
            elif elapsed > STEP_TIMEOUT:
                step["status"] = "fail"
                step["detail"] = (f"No speech detected on {names.get(step['source'])}. Check the XLR cable, that the "
                                  "mic is in the right input, the gain knob, and 48V if it is a condenser mic.")
            else:
                step["detail"] = f"Listening… {int(me.get('active_s', 0))} s of speech heard"
        elif kind == "talkback":
            if me.get("active_s", 0) >= 2:
                leak = [k for k, v in others.items() if v.get("active_s", 0) >= 2 and
                        v.get("avg_st", -120) > me.get("avg_st", -120) - 15]
                if leak:
                    step["status"] = "fail"
                    step["detail"] = (f"Talkback is also arriving on {names.get(leak[0])} — it would be recorded. "
                                      "Inspect Focusrite Control routing while idle; do not load a preset during production.")
                else:
                    step["status"] = "pass"
                    step["detail"] = ("No comparable signal observed on the monitored programme inputs. "
                                      "Audition track assignment and Zoom talkback privacy still require a manual test.")
            elif elapsed > STEP_TIMEOUT:
                step["status"] = "fail"
                step["detail"] = "No talkback signal. Check the talkback mic cable and input 4."
            else:
                step["detail"] = "Listening for talkback…"

    def check_recording(self):
        """Operator finished the test take: find new audio in today's session folder and QC it."""
        if not self.active or self.i >= len(self.steps) or self.steps[self.i]['kind'] != 'record':
            raise ValueError('Navigate to the test-recording step first.')
        step = self.steps[self.i]
        st = self.studio
        sess = st.state.get("session")
        if st.audio.simulated:
            step.update(status="pass", detail="(simulation) Test recording verified on all tracks.")
            return self.state()
        if not sess:
            step.update(status="warn", detail="No Sawti session today, so the take cannot be checked automatically. "
                                              "Listen back in Audition.")
            return self.state()
        recent = [p for p in post.session_tracks(sess["folder"]) if time.time() - Path(p).stat().st_mtime < 300]
        if not recent:
            step.update(status="fail", detail="No new recording found in today's session folder. Was Record pressed "
                                              "in the session Sawti opened?")
            return self.state()
        qc = post.qc_files(recent)
        bad = [q for q in qc if q["issues"]]
        if bad:
            step.update(status="warn", detail="; ".join(f"{Path(q['path']).name}: {', '.join(q['issues'])}" for q in bad))
        else:
            required = len(st.profile(st.mode).get('audition_tracks', []))
            step.update(status="warn", detail=f"{len(qc)} file(s) have signal; {required} tracks are expected. "
                        "File count does not verify track identity, input mapping or talkback exclusion. Listen back in Audition.")
        return self.state()

    # ------------------------------------------------------------ navigation
    def state(self):
        if self.active and self.i < len(self.steps):
            self._evaluate()
        done = self.active and self.i >= len(self.steps)
        return dict(active=self.active, index=self.i, steps=self.steps, done=done,
                    ready=done and all(s["status"] == "pass" for s in self.steps))

    def next(self):
        if not self.active or self.i >= len(self.steps):
            return self.state()
        if self.steps[self.i]["status"] == "running":
            self.steps[self.i]["status"] = "skipped"
        self.i += 1
        if self.i < len(self.steps):
            self._enter()
        else:
            self.studio.monitor.unmark("pretest")
            self.studio.monitor.sim_focus = None
            ok = all(s["status"] == "pass" for s in self.steps)
            self.studio.learn("pretest_done", mode=self.studio.mode, ok=ok,
                              failed=[s["id"] for s in self.steps if s["status"] in ("fail", "warn")])
        return self.state()

    def skip(self):
        if self.active and self.i < len(self.steps):
            self.steps[self.i]["status"] = "skipped"
        return self.next()

    def retest(self):
        if self.active and self.i < len(self.steps):
            self.steps[self.i].update(status="running", detail="")
            self.advised.discard(self.steps[self.i]["id"])
            self._enter()
        return self.state()

    def cancel(self):
        self.active = False
        self.studio.monitor.unmark("pretest")
        self.studio.monitor.sim_focus = None
        return self.state()
