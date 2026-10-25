"""Live metering: per-source loudness (momentary / short-term LUFS), peaks, clipping, speech activity,
digital-silence detection (macOS microphone permission), and the optional inline leveler.

Capture only. Audio is analysed in memory and never stored or transmitted.
"""
import collections
import threading
import time

import numpy as np

from . import dsp

BLOCK = 1024
SPEECH_GATE = -55.0      # LUFS momentary: below this a mic is treated as not speaking
CLIP_DBFS = -0.5


class SourceState:
    def __init__(self, src):
        self.src = src
        self.blocks = collections.deque()  # (t, mean_square, frames)
        self.peak = dsp.NEG_INF
        self.hold = dsp.NEG_INF
        self.clips = 0
        self.zero_since = None
        self.last_nonzero = None
        self.active_s = 0.0

    def window_power(self, now, seconds):
        tot = n = 0.0
        for t, ms, fr in reversed(self.blocks):
            if now - t > seconds:
                break
            tot += ms * fr
            n += fr
        return tot / n if n else 0.0


class MarkStats:
    """Per-source statistics collected since a mark (used by the pre-test wizard)."""

    def __init__(self, ids):
        self.started = time.monotonic()
        self.s = {i: dict(max_st=dsp.NEG_INF, max_peak=dsp.NEG_INF, active_s=0.0, st_sum=0.0, st_n=0, clips=0)
                  for i in ids}


class Monitor:
    def __init__(self, audio):
        self.audio = audio
        self.lock = threading.RLock()
        self.stream = None
        self.sim_thread = None
        self.sim_stop = threading.Event()
        self.config = None
        self.sources = {}
        self.error = None
        self.started_at = None
        self.last_audio = None
        self.kw = None
        self.mix_blocks = collections.deque()
        self.marks = {}
        self.leveler = None
        self.leveler_gain = {}
        self.sim_focus = None      # simulation: which source is "speaking" during a guided check
        self.sim_faults = set()    # simulation: e.g. {"mic2_dead", "permission"}

    # ------------------------------------------------------------ lifecycle
    def start(self, config):
        """config: device_index, device_name, rate, open_channels, sources[{id,name,role,chans}], leveler{...}"""
        self.stop()
        with self.lock:
            self.config = config
            self.sources = {s["id"]: SourceState(s) for s in config["sources"]}
            self.kw = dsp.KWeighter(config["rate"], config["open_channels"])
            self.mix_blocks.clear()
            self.error = None
            self.started_at = time.monotonic()
            self.last_audio = None
            lv = config.get("leveler") or {}
            prog = [s for s in config["sources"] if s["role"] in ("programme", "remote")]
            self.leveler = dsp.Leveler(config["rate"], len(prog), target=lv.get("target", -20.0)) \
                if lv.get("enabled") else None
            self.leveler_gain = {}
        try:
            if self.audio.simulated:
                self.sim_stop.clear()
                self.sim_thread = threading.Thread(target=self._simulate, daemon=True)
                self.sim_thread.start()
            else:
                self._open_stream(config)
            return True
        except Exception as exc:  # report the real reason to the operator
            with self.lock:
                self.error = self._explain(exc)
                self.config = None
            return False

    def _open_stream(self, config):
        import sounddevice as sd
        lv = config.get("leveler") or {}
        self.audio.stream_open = True
        try:
            if lv.get("enabled"):
                stream = sd.Stream(device=(config["device_index"], lv["out_index"]),
                                   channels=(config["open_channels"], lv["out_channels"]),
                                   samplerate=config["rate"], blocksize=BLOCK, dtype="float32",
                                   callback=self._duplex_callback)
            else:
                stream = sd.InputStream(device=config["device_index"], channels=config["open_channels"],
                                        samplerate=config["rate"], blocksize=BLOCK, dtype="float32",
                                        callback=self._input_callback)
            stream.start()
        except Exception:
            self.audio.stream_open = False
            raise
        with self.lock:
            self.stream = stream

    @staticmethod
    def _explain(exc):
        text = str(exc)
        if "PortAudio" in text and "not found" in text:
            return "Audio library missing. Re-run INSTALL_SAWTI.command."
        if "Invalid number of channels" in text:
            return "The audio device has fewer channels than this show needs. Run the device fixes first."
        if "Invalid sample rate" in text:
            return "The audio device is not at 48 kHz. Use the Fix button for the sample rate."
        return text

    def stop(self):
        with self.lock:
            stream, self.stream = self.stream, None
            self.config = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            self.audio.stream_open = False
        if self.sim_thread is not None:
            self.sim_stop.set()
            self.sim_thread.join(timeout=2)
            self.sim_thread = None

    @property
    def running(self):
        return self.config is not None and (self.stream is not None or self.sim_thread is not None)

    # ------------------------------------------------------------ analysis
    def _input_callback(self, indata, frames, time_info, status):
        self._analyse(indata, status)

    def _duplex_callback(self, indata, outdata, frames, time_info, status):
        self._analyse(indata, status)
        outdata.fill(0)
        y = self._level(indata)
        if y is not None:
            n = min(outdata.shape[1], y.shape[1])
            outdata[:, :n] = y[:, :n]

    def _level(self, indata):
        if self.leveler is None or self.config is None:
            return None
        prog = [s for s in self.config["sources"] if s["role"] in ("programme", "remote")]
        x = np.stack([indata[:, s["chans"]].mean(axis=1) for s in prog], axis=1)
        y = self.leveler.process(x)
        with self.lock:
            self.leveler_gain = {s["id"]: round(float(g), 1) for s, g in zip(prog, self.leveler.gain_db)}
        return y.astype(np.float32)

    def _analyse(self, indata, status=None):
        now = time.monotonic()
        x = np.asarray(indata, dtype=np.float64)
        with self.lock:
            if self.config is None:
                return
            if status:
                self.error = f"Audio interruption: {status}"
            k = self.kw.process(x)
            self.last_audio = now
            frames = len(x)
            dt = frames / self.config["rate"]
            mix = np.zeros(frames)
            for sid, st in self.sources.items():
                ch = st.src["chans"]
                ms = float((k[:, ch] ** 2).mean(axis=0).sum())
                st.blocks.append((now, ms, frames))
                while st.blocks and now - st.blocks[0][0] > 3.2:
                    st.blocks.popleft()
                pk = float(np.max(np.abs(x[:, ch]))) if frames else 0.0
                st.peak = dsp.db(pk)
                st.hold = max(st.peak, st.hold - 10 * dt)
                if st.peak >= CLIP_DBFS:
                    st.clips += 1
                if pk == 0.0:
                    st.zero_since = st.zero_since or now
                else:
                    st.zero_since = None
                    st.last_nonzero = now
                mom = dsp.lufs_from_power(st.window_power(now, 0.4))
                if mom > SPEECH_GATE:
                    st.active_s += dt
                if st.src["role"] in ("programme", "remote"):
                    mix += k[:, ch].sum(axis=1)
                stt = dsp.lufs_from_power(st.window_power(now, 3.0))
                for m in self.marks.values():
                    s = m.s.get(sid)
                    if s is None:
                        continue
                    s["max_peak"] = max(s["max_peak"], st.peak)
                    if st.peak >= CLIP_DBFS:
                        s["clips"] += 1
                    if mom > SPEECH_GATE:
                        s["active_s"] += dt
                        s["max_st"] = max(s["max_st"], stt)
                        s["st_sum"] += stt
                        s["st_n"] += 1
            self.mix_blocks.append((now, float((mix ** 2).mean()), frames))
            while self.mix_blocks and now - self.mix_blocks[0][0] > 3.2:
                self.mix_blocks.popleft()

    # ------------------------------------------------------------ marks (pre-test)
    def mark(self, name):
        with self.lock:
            self.marks[name] = MarkStats(list(self.sources))
            return self.marks[name]

    def mark_stats(self, name):
        with self.lock:
            m = self.marks.get(name)
            if not m:
                return None
            out = {}
            for sid, s in m.s.items():
                avg = s["st_sum"] / s["st_n"] if s["st_n"] else dsp.NEG_INF
                out[sid] = dict(max_st=round(s["max_st"], 1), avg_st=round(avg, 1), max_peak=round(s["max_peak"], 1),
                                active_s=round(s["active_s"], 1), clips=s["clips"])
            return dict(elapsed=round(time.monotonic() - m.started, 1), sources=out)

    def unmark(self, name):
        with self.lock:
            self.marks.pop(name, None)

    # ------------------------------------------------------------ snapshot
    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            cfg = self.config
            out = dict(running=self.running, error=self.error, device=cfg["device_name"] if cfg else None,
                       rate=cfg["rate"] if cfg else None, simulated=self.audio.simulated,
                       leveler=bool(self.leveler), sources=[], mix_st=None, mix_m=None,
                       audio_age=round(now - self.last_audio, 1) if self.last_audio else None,
                       digital_silence=False)
            if not cfg:
                return out
            silent_all = bool(self.sources) and now - self.started_at > 2.5
            for sid, st in self.sources.items():
                mom = dsp.lufs_from_power(st.window_power(now, 0.4))
                stt = dsp.lufs_from_power(st.window_power(now, 3.0))
                zero = st.zero_since is not None and now - st.zero_since > 2.0
                if not zero:
                    silent_all = False
                out["sources"].append(dict(
                    id=sid, name=st.src["name"], role=st.src["role"], chans=[c + 1 for c in st.src["chans"]],
                    momentary=round(mom, 1), short_term=round(stt, 1), peak=round(st.peak, 1),
                    hold=round(st.hold, 1), clip=st.hold >= CLIP_DBFS, clips=st.clips,
                    speaking=mom > SPEECH_GATE, digital_zero=zero,
                    leveler_gain=self.leveler_gain.get(sid)))
            mix3 = sum(ms * fr for t, ms, fr in self.mix_blocks if now - t <= 3.0)
            n3 = sum(fr for t, ms, fr in self.mix_blocks if now - t <= 3.0)
            out["mix_st"] = round(dsp.lufs_from_power(mix3 / n3), 1) if n3 else None
            out["digital_silence"] = silent_all
            return out

    # ------------------------------------------------------------ simulation
    def _simulate(self):
        from scipy import signal
        cfg = self.config
        fs, nch = cfg["rate"], cfg["open_channels"]
        rng = np.random.default_rng(7)
        sos = signal.butter(2, [150, 3800], "bandpass", fs=fs, output="sos")
        zi = np.zeros((sos.shape[0], 2, nch))
        # burst level per absolute channel (≈ LUFS + 3.5); sim studio: mic 1 good, mic 2 too quiet, mic 3 hot
        level = np.full(nch, -200.0)
        for s in cfg["sources"]:
            base = {"mic1": -16.5, "mic2": -26.5, "mic3": -13.0, "talkback": -20.5, "guests": -17.5}.get(s["id"], -17.5)
            for c in s["chans"]:
                level[c] = base
        noise_floor = 10 ** (-78 / 20)
        t0 = time.monotonic()
        n = 0
        while not self.sim_stop.is_set():
            t = n * BLOCK / fs + np.arange(BLOCK) / fs
            x = rng.standard_normal((BLOCK, nch))
            x, zi = signal.sosfilt(sos, x, axis=0, zi=zi)
            syll = (0.5 + 0.5 * np.sin(2 * np.pi * 3.3 * t)) ** 2
            out = np.zeros((BLOCK, nch))
            for s in cfg["sources"]:
                # who talks: guided check -> only the focused source; otherwise turn-taking every 6 s
                if self.sim_focus:
                    talking = s["id"] == self.sim_focus
                else:
                    order = [p["id"] for p in cfg["sources"] if p["role"] in ("programme", "remote")]
                    talking = s["id"] in order and order[int(t[0] // 6) % max(1, len(order))] == s["id"]
                for c in s["chans"]:
                    amp = 10 ** (level[c] / 20) * 2.5
                    sig = x[:, c] * syll * amp if talking else 0.0
                    out[:, c] = sig + rng.standard_normal(BLOCK) * noise_floor
                    if f"{s['id']}_dead" in self.sim_faults or "permission" in self.sim_faults:
                        out[:, c] = 0.0
            self._analyse(out.astype(np.float32))
            if self.leveler is not None:
                self._level(out.astype(np.float32))
            n += 1
            wait = t0 + n * BLOCK / fs - time.monotonic()
            if wait > 0:
                self.sim_stop.wait(wait)
