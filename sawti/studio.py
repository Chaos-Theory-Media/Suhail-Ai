"""The orchestrator: owns the agents, the meter, the show state and every action Sawti can take."""
import collections
import datetime
import json
import threading
import time

from . import paths, store
from .commissioning import microphone_plan
from .agents import audition, devices as devices_agent, learning, levels, mac
from .agents.pretest import Pretest
from .coreaudio import SHOW_INPUT_NAME, SHOW_INPUT_UID, find_blackhole, find_scarlett, find_uid, input_layout, make_audio
from .lifecycle import Lifecycle
from .meter import Monitor
from .safety import Approvals, powered, serialised
from .presenter_speech import PresenterSpeech

SEVERITY_ORDER = {"fail": 0, "warn": 1, "manual": 2, "info": 3, "ok": 4}


class Studio:
    def __init__(self, audio=None):
        self.audio = audio or make_audio()
        self.monitor = Monitor(self.audio)
        self.lifecycle = Lifecycle(allow_ai=not self.audio.simulated)
        self.lock = threading.RLock()
        self.mode = "local"
        self.mic_plan = None  # explicit confirmation per powered session; never restored from disk
        self.live = False
        self.live_since = None
        self.accessibility_ok = None
        self.sim_apps = {"focusrite control"} if self.audio.simulated else set()
        self.notices = collections.deque(maxlen=30)
        self._notice_id = 0
        self._dev_cache = (0.0, [])
        self._last_live_warn = {}
        self.state = store.get("state", {}) or {}
        self.pretest = Pretest(self)
        self.actions = {}
        for a in devices_agent.ACTIONS + mac.ACTIONS + audition.ACTIONS:
            self.actions[a.name] = a
        self._scheduler = None
        self._stop = threading.Event()
        self.power_epoch = 0
        self.approvals = Approvals(self)
        self.presenter_speech = PresenterSpeech(self)

    def require_on(self):
        if not self.lifecycle.on:
            raise RuntimeError("Sawti is OFF. Switch it ON first.")

    # ------------------------------------------------------------ storage passthrough
    def settings(self, key):
        return store.get(key)

    def put_setting(self, key, value):
        store.put(key, value)

    def learn(self, kind, **data):
        try:
            store.log(kind, **data)
        except Exception:
            pass

    def events(self, kind=None, since=None):
        return store.events(kind, since)

    def observations(self):
        return store.observations()

    def save_observations(self, rows):
        store.save_observations(rows)

    def save_state(self):
        store.put("state", self.state)

    def notify(self, message, level="info"):
        with self.lock:
            self._notice_id += 1
            self.notices.append(dict(id=self._notice_id, ts=time.time(), message=message, level=level))

    # ------------------------------------------------------------ environment
    def profile(self, mode=None):
        mode = mode or self.mode
        if mode not in ("local", "zoom"):
            raise ValueError("Unknown show type")
        prof = json.loads((paths.APP_ROOT / "profiles" / f"{mode}.json").read_text())
        names = (self.settings("source_names") or {}).get(mode, {})
        if mode == 'local' and self.mic_plan:
            chosen = self.mic_plan['inputs']
            prof['sources'] = [s for s in prof['sources'] if s['role'] != 'programme' or s['channels'][0] in chosen]
            prof['audition_tracks'] = [f'Mic {i}' for i in chosen]
            prof['name'] = f'Podcast · {len(chosen)} microphone(s)'
        for s in prof["sources"]:
            if names.get(s["id"]):
                s["name"] = names[s["id"]][:60]
        return prof

    @powered
    def select_microphones(self, inputs, studio_idle=False):
        plan = microphone_plan(inputs)
        if self.mode != 'local':
            raise RuntimeError('Microphone selection currently supports Podcast mode only.')
        if self.live or studio_idle is not True:
            raise RuntimeError('Confirm all recording is idle before changing the Podcast plan.')
        self.pretest.cancel()
        self.approvals.invalidate()
        self.presenter_speech.stop(clear=True)
        # Stop only Sawti capture. Never reopen a stream or touch production audio here.
        self.stop_meter()
        self.mic_plan = plan
        self.state['confirmed'] = {}
        self.save_state()
        self.learn('microphones_selected', inputs=plan['inputs'], mode=self.mode)
        return dict(plan=plan, message='Podcast plan confirmed. Mic 1 is presenter; input 4 is talkback only. '
                    'Verify the matching Audition template; its tracks have not been changed.')

    def devices(self, fresh=False):
        t, cached = self._dev_cache
        if fresh or time.monotonic() - t > 2.0:
            try:
                cached = self.audio.devices()
            except Exception:
                cached = []
            self._dev_cache = (time.monotonic(), cached)
        return cached

    def running_apps(self):
        if self.audio.simulated:
            return sorted(self.sim_apps)
        try:
            import psutil
            return [(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])]
        except Exception:
            return []

    def open_app(self, name):
        if self.audio.simulated:
            self.sim_apps.add(name.lower())
            return
        import subprocess
        try:
            result = subprocess.run(["/usr/bin/open", "-a", name], check=False, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('macOS did not complete the application launch request in time.') from exc
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'macOS refused to open ' + name)

    def open_url(self, url):
        if self.audio.simulated:
            return
        import subprocess
        subprocess.run(["/usr/bin/open", url], check=False, capture_output=True, timeout=10)

    # ------------------------------------------------------------ meter
    def meter_config(self, mode=None):
        mode = mode or self.mode
        prof = self.profile(mode)
        devs = self.devices(fresh=True)
        sc = find_scarlett(devs)
        if not sc:
            raise RuntimeError("Scarlett 18i8 not detected. Check the USB cable and power.")
        if prof["meter_device"] == "show_input":
            dev = find_uid(devs, SHOW_INPUT_UID, SHOW_INPUT_NAME)
            if not dev:
                raise RuntimeError("The Sawti Show Input does not exist yet. Use 'Fix everything I can' first.")
            offsets = input_layout(dev, devs)
            if "blackhole" not in offsets:
                raise RuntimeError("The Sawti Show Input is incomplete. Use the Rebuild fix.")
        else:
            dev, offsets = sc, {"scarlett": 0}
        if dev.get("index") is None:
            raise RuntimeError(f"'{dev['name']}' is not visible to the audio engine yet. Press Start again in a moment.")
        sources = []
        for s in prof["sources"]:
            if s["device"] not in offsets:
                continue
            chans = [offsets[s["device"]] + c - 1 for c in s["channels"]]
            if max(chans) < dev["inputs"]:
                sources.append(dict(id=s["id"], name=s["name"], role=s["role"], chans=chans,
                                    gain_knob=s.get("gain_knob")))
        if not sources:
            raise RuntimeError("No inputs to meter on this device.")
        cfg = dict(device_index=dev["index"], device_name=dev["name"], rate=int(dev["rate"] or 48000),
                   open_channels=max(c for s in sources for c in s["chans"]) + 1, sources=sources, leveler=None)
        if self.settings("leveler_enabled"):
            if not self.audio.simulated:
                raise RuntimeError("Inline audio output is not qualified for production. Disable the leveler; "
                                   "capture-only monitoring remains available. The leveler can be tested in simulation.")
            want = self.settings("leveler_output")
            out = next((d for d in devs if d["name"] == want and d["outputs"] > 0), None)
            zoom_bh = find_blackhole(devs, 2)
            if not out:
                raise RuntimeError(f"Inline leveler output '{want}' not found. Install BlackHole 16ch or turn the "
                                   "leveler off in Settings.")
            if zoom_bh and out["uid"] == zoom_bh.get("uid") and mode == "zoom":
                raise RuntimeError("The leveler cannot use the same BlackHole as Zoom. Use BlackHole 16ch.")
            prog = [s for s in sources if s["role"] in ("programme", "remote")]
            cfg["leveler"] = dict(enabled=True, out_index=out["index"], out_channels=min(out["outputs"], len(prog)),
                                  target=self.settings("speech_target"), out_name=out["name"])
        if not self.audio.simulated and (not dev.get('rate_verified') or not dev.get('rate')):
            raise RuntimeError('Current operating sample rate is unverified. Install/repair the read-only audio '
                               'helper before capture; Sawti will not request a guessed default rate.')
        return cfg

    def ensure_meter(self):
        if not self.monitor.running:
            return self.start_meter()
        return True

    @powered
    def start_meter(self):
        try:
            cfg = self.meter_config()
        except Exception as exc:
            self.monitor.error = str(exc)
            return False
        return self.monitor.start(cfg)

    @serialised
    def stop_meter(self):
        self.monitor.stop()

    # ------------------------------------------------------------ checks
    def check_all(self, mode=None):
        mode = mode or self.mode
        devs = self.devices()
        apps = self.running_apps()
        snap = self.monitor.snapshot()
        F = devices_agent.check(self, mode, devs) + mac.check(self, mode, snap, apps) + \
            audition.check(self, mode, apps) + levels.check(self, snap)
        if mode == 'local' and not self.mic_plan:
            F.append(dict(id='microphone_selection', agent='Audition', severity='warn',
                          title='How many microphones for this Podcast?',
                          detail='Confirm 1–3 programme microphones in Prepare. Mic 1 is presenter; input 4 is talkback only.',
                          action=None, action_label=None))
        if snap.get("error") and not snap.get("running"):
            F.append(dict(id="meter_error", agent="Levels", severity="warn", title="Meters could not start",
                          detail=snap["error"], action=None, action_label=None))
        confirmed = self.state.get("confirmed", {})
        today = datetime.date.today().isoformat()
        for f in F:
            if f["severity"] == "manual" and confirmed.get(f"{mode}:{f['id']}") == today:
                f["severity"], f["confirmed"] = "ok", True
        F.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
        return F

    def confirm(self, fid):
        self.state.setdefault("confirmed", {})[f"{self.mode}:{fid}"] = datetime.date.today().isoformat()
        self.save_state()
        self.learn("manual_confirmed", mode=self.mode, check=fid)

    # ------------------------------------------------------------ actions
    @powered
    def apply(self, name, by="operator", approval=None, operator_confirmed=False, studio_idle=False):
        meta = {
            "fix_all": lambda: self.fix_all(),
            "pretest": lambda: (self.pretest.start(), "Pre-test started.")[1],
            "meter_start": lambda: "Meters started." if self.start_meter() else
            f"Meters could not start: {self.monitor.error}",
            "meter_stop": lambda: (self.stop_meter(), "Meters stopped.")[1],
            "mode_zoom": lambda: self.set_mode("zoom"),
            "mode_local": lambda: self.set_mode("local"),
        }
        if name in meta:
            return meta[name]()
        a = self.actions.get(name)
        if not a:
            raise ValueError("Unknown action")
        if self.live and not a.live_safe:
            raise RuntimeError("Not while recording — Sawti never changes devices or routing during a live show.")
        if a.impact:
            if by != "operator":
                raise RuntimeError("Audio-impact actions require a fresh operator approval every time.")
            self.approvals.consume(name, approval, operator_confirmed, studio_idle)
            self.state.pop('confirmed', None)
            if a.agent == 'Devices':
                self.presenter_speech.stop(clear=True)
                self.pretest.cancel()
                self.stop_meter()  # release only Sawti capture before the authorised change
        try:
            msg = a.fn(self)
        finally:
            self.approvals.invalidate()
        self._dev_cache = (0.0, [])
        self.save_state()
        self.learn("fix_applied", action=name, by=by, mode=self.mode)
        return msg

    @powered
    def fix_all(self, by="operator"):
        done, failed, seen = [], [], set()
        for _ in range(3):  # fixes can unlock further fixes (e.g. rate -> aggregate)
            todo = [f for f in self.check_all() if f["severity"] in ("fail", "warn") and f.get("action")
                    and f["action"] in self.actions and self.actions[f["action"]].safe
                    and not self.actions[f["action"]].impact and f["action"] not in seen]
            if not todo:
                break
            for f in todo:
                seen.add(f["action"])
                try:
                    done.append(self.apply(f["action"], by=by))
                except Exception as exc:
                    failed.append(f"{f['title']}: {exc}")
        msg = " ".join(done) if done else "No non-audio fixes available."
        msg += " Device, sample-rate and Audition changes require individual review and approval."
        if failed:
            msg += " Could not fix: " + "; ".join(failed)
        return msg

    @powered
    def run_autofixes(self, reason="power-on"):
        approved = {k for k, v in (self.settings("autofix") or {}).items() if v}
        done = []
        if not approved or self.live:
            return done
        for f in self.check_all():
            a = self.actions.get(f.get("action"))
            if (a and a.safe and not a.impact and f.get("action") in approved
                    and f["severity"] in ("fail", "warn")):
                try:
                    done.append(self.apply(f["action"], by="auto"))
                except Exception as exc:
                    done.append(f"{f['title']} not fixed: {exc}")
        if done:
            self.learn("autofix_run", reason=reason, count=len(done))
        return done

    def approve_autofix(self, action, enabled=True):
        a = self.actions.get(action)
        if not a or (enabled and (not a.safe or a.impact)):
            raise ValueError("That action cannot run automatically.")
        auto = self.settings("autofix") or {}
        auto[action] = bool(enabled)
        self.put_setting("autofix", auto)

    # ------------------------------------------------------------ mode & show
    @serialised
    def set_mode(self, mode):
        if mode not in ("local", "zoom"):
            raise ValueError("Unknown show type")
        if mode == self.mode:
            return f"Already in {'Zoom Show' if mode == 'zoom' else 'Podcast'} mode."
        if self.live and mode != self.mode:
            raise RuntimeError("Finish the live show before switching show type.")
        was_running = self.monitor.running
        self.pretest.cancel()
        self.approvals.invalidate()
        self.mode = mode
        self.presenter_speech.stop(clear=True)
        self.mic_plan = None
        self.learn("mode_selected", mode=mode)
        if was_running:
            self.stop_meter()
            self.start_meter()
        return f"Switched to {'Zoom Show' if mode == 'zoom' else 'Podcast'}."

    @powered
    def go_live(self, source="operator"):
        if self.live:
            return "Already live."
        speech = self.presenter_speech.snapshot()
        if speech['phase'] in ('preparing', 'speaking') and not speech['enabled']:
            raise RuntimeError('Finish or mute the private headset test before going live or pressing Record.')
        if not self.ensure_meter():
            raise RuntimeError(self.monitor.error or 'Live monitoring could not start. Show was not marked live.')
        self.live, self.live_since = True, time.time()
        self.approvals.invalidate()
        self.lifecycle.keep_awake(True)
        self.learn("show_started", mode=self.mode, source=source)
        return "Show is live. Sawti watches levels and will not touch devices until you end the show."

    @serialised
    def end_live(self):
        if not self.live:
            return "No live show."
        dur = time.time() - (self.live_since or time.time())
        self.live, self.live_since = False, None
        self.approvals.invalidate()
        self.learn("show_ended", mode=self.mode, minutes=round(dur / 60, 1))
        self.notify("Show ended. Post-production can now mix and master today's recordings.", "info")
        return f"Show ended after {dur / 60:.0f} min."

    # ------------------------------------------------------------ power & background work
    @serialised
    def power_on(self, mode=None):
        if mode:
            self.set_mode(mode)
        self.lifecycle.power_on()
        self.learn('sawti_started', simulated=self.audio.simulated)
        done = self.run_autofixes("power-on")
        if done:
            self.notify("Done in advance: " + " ".join(done), "info")
        if self._scheduler is None or not self._scheduler.is_alive() or self._stop.is_set():
            self._stop = threading.Event()
            self._scheduler = threading.Thread(target=self._loop, args=(self._stop,), daemon=True)
            self._scheduler.start()

    @serialised
    def power_off(self):
        self._stop.set()
        self.power_epoch += 1
        self.presenter_speech.stop(clear=True)
        self.approvals.invalidate()
        self.mic_plan = None
        if self.live:
            self.end_live()
        try:
            self.pretest.cancel()
        finally:
            try:
                self.stop_meter()
            finally:
                self.lifecycle.power_off()

    def _loop(self, stop):
        last_learn = 0
        while not stop.wait(2.0):
            with self.lock:
                if not self.lifecycle.on or stop.is_set():
                    continue
                try:
                    if self.live and self.monitor.running:
                        self._watch_live()
                    if time.time() - last_learn > 60:
                        last_learn = time.time()
                        learning.tick(self)
                except Exception as exc:
                    self.notify(f"Background check error: {exc}", "warn")

    def _watch_live(self):
        snap = self.monitor.snapshot()
        if snap.get("digital_silence"):
            self._live_warn("silence", "All inputs went silent — check the Scarlett connection now!", "fail")
        for c in levels.coach(self, snap):
            if c["status"] in ("clip", "very_low", "hot"):
                if self._live_warn(c["id"] + c["status"], c["message"], "fail" if c["status"] == "clip" else "warn"):
                    self.learn("gain_advice", mode=self.mode, source=c["id"], delta=c["delta"], live=True)

    def _live_warn(self, key, message, level):
        now = time.time()
        if now - self._last_live_warn.get(key, 0) < 30:
            return False
        self._last_live_warn[key] = now
        self.notify(message, level)
        return True

    def snapshot(self):
        lc = self.lifecycle.snapshot()
        return dict(on=lc["on"], mode=self.mode, live=self.live,
                    recording_state="unknown", power_epoch=self.power_epoch,
                    live_minutes=round((time.time() - (self.live_since or time.time())) / 60, 1) if self.live else None,
                    ollama=lc["ollama"], ollama_detail=lc["ollama_detail"], keep_awake=lc["keep_awake"],
                    simulated=self.audio.simulated, session=self.state.get("session"),
                    microphone_plan=self.mic_plan,
                    presenter_speech=self.presenter_speech.snapshot(),
                    notices=list(self.notices)[-8:])
