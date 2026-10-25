"""Device layer: one interface over CoreAudio (via the sawti-audio helper) and PortAudio (sounddevice).

RealAudio  — the Mac. The helper creates/updates devices; sounddevice opens meter streams.
SimAudio   — simulation (SAWTI_SIMULATE=1) for training, demos and automated tests; behaves like the
             studio Mac including faults (Scarlett at 44.1 kHz, no Sawti devices) that Fix buttons repair.
"""
import json
import subprocess
import threading
import time

from . import paths

SHOW_INPUT_UID = "com.imi.sawti.show-input"
SHOW_INPUT_NAME = "Sawti Show Input"
ZOOM_SPEAKER_UID = "com.imi.sawti.zoom-speaker"
ZOOM_SPEAKER_NAME = "Sawti Zoom Speaker"


class AudioError(RuntimeError):
    pass


def is_scarlett(d):
    identity = ' '.join(str(d.get(k) or '') for k in ('name', 'uid')).lower()
    return (('scarlett' in identity or ('focusrite' in str(d.get('manufacturer', '')).lower() and '18i8' in identity))
            and d.get("transport") != "aggregate" and d["inputs"] >= 4)


def find_scarlett(devs):
    return next((d for d in devs if is_scarlett(d)), None)


def find_blackhole(devs, channels=2):
    cands = [d for d in devs if "blackhole" in d["name"].lower()]
    exact = [d for d in cands if f"{channels}ch" in d["name"].lower()]
    return next((d for d in exact if d['inputs'] == channels and d['outputs'] == channels), None)


def find_uid(devs, uid, name=None):
    return next((d for d in devs if d.get("uid") == uid), None)


def input_layout(aggregate, devs):
    """Channel offset of each sub-device inside an aggregate, in order: {'scarlett': 0, 'blackhole': 18}."""
    by_uid = {d.get("uid"): d for d in devs}
    offsets, pos = {}, 0
    for uid in aggregate.get("subdevices", []):
        d = by_uid.get(uid)
        if not d:
            raise AudioError('Aggregate contains an unavailable sub-device; channel order is unknown.')
        key = "scarlett" if is_scarlett(d) else "blackhole" if "blackhole" in d["name"].lower() else uid
        offsets.setdefault(key, pos)
        pos += d["inputs"]
    return offsets


# ------------------------------------------------------------------ real Mac
class RealAudio:
    simulated = False

    def __init__(self):
        self.lock = threading.RLock()
        self.stream_open = False  # PortAudio cannot be re-initialised while a stream is open
        self.last_diagnostics = dict(helper_ok=False, portaudio_ok=False, queried=False)
        self._native_cache = (0.0, [], None)

    def diagnostics(self):
        return dict(self.last_diagnostics)

    def helper_available(self):
        p = paths.helper_path()
        return p.is_file()

    def _helper(self, *args, timeout=15):
        if not self.helper_available():
            raise AudioError("The Sawti audio helper is not installed. Re-run INSTALL_SAWTI.command.")
        try:
            r = subprocess.run([str(paths.helper_path()), *args], capture_output=True, text=True, timeout=timeout)
            out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            raise AudioError(f"Audio helper failed: {exc}") from exc
        if not isinstance(out, dict) or r.returncode or not out.get("ok"):
            if not isinstance(out, dict):
                raise AudioError('Audio helper returned an invalid response.')
            raise AudioError(out.get("error") or r.stderr.strip() or "Audio helper failed")
        return out

    def _portaudio(self):
        import sounddevice as sd
        with self.lock:
            if not self.stream_open:
                try:  # pick up devices created since start-up (PortAudio caches the list)
                    sd._terminate()
                    sd._initialize()
                except Exception as exc:
                    raise AudioError('PortAudio device refresh failed: ' + str(exc)) from exc
            return sd.query_devices()

    def _system_devices(self):
        """Read-only built-in macOS observation; never sets devices or rates."""
        now = time.monotonic()
        when, cached, error = self._native_cache
        if now - when < 15:
            if error:
                raise AudioError(error)
            return cached
        try:
            result = subprocess.run(['/usr/sbin/system_profiler', 'SPAudioDataType', '-json'],
                                    capture_output=True, text=True, timeout=8)
            if result.returncode:
                raise AudioError(result.stderr.strip() or 'macOS audio inventory failed.')
            data = json.loads(result.stdout)
            if not isinstance(data, dict) or not isinstance(data.get('SPAudioDataType'), list):
                raise AudioError('macOS audio inventory returned an unsupported response.')
            found = []
            def walk(items):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if isinstance(item.get('_items'), list):
                        walk(item['_items'])
                    if not any(k in item for k in ('coreaudio_device_input', 'coreaudio_device_output')):
                        continue
                    def number(key):
                        try:
                            return max(0, int(float(item.get(key, 0))))
                        except (TypeError, ValueError):
                            return 0
                    rate = number('coreaudio_device_srate')
                    found.append(dict(name=item.get('_name', 'Unnamed audio device'), uid=None,
                                      manufacturer=item.get('coreaudio_device_manufacturer', ''),
                                      inputs=number('coreaudio_device_input'), outputs=number('coreaudio_device_output'),
                                      rate=rate, rate_verified=rate > 0, rate_source='system_profiler',
                                      transport=str(item.get('coreaudio_device_transport', 'unknown')).lower(),
                                      subdevices=[], rates=[], control_available=False))
            walk(data.get('SPAudioDataType', []))
            self._native_cache = (now, found, None)
            return found
        except (OSError, ValueError, subprocess.TimeoutExpired, AudioError) as exc:
            self._native_cache = (now, [], str(exc))
            raise AudioError(str(exc)) from exc

    def devices(self):
        diagnostics = dict(queried=True, helper_available=self.helper_available(), helper_ok=False,
                           portaudio_ok=False, helper_error=None, portaudio_error=None)
        ca = []
        if self.helper_available():
            try:
                ca = self._helper("list")["devices"]
                if not isinstance(ca, list):
                    raise AudioError('Audio helper did not return a device list.')
                diagnostics['helper_ok'] = True
            except (AudioError, KeyError) as exc:
                diagnostics['helper_error'] = str(exc)
                ca = []
        else:
            diagnostics['helper_error'] = 'Sawti audio helper is not installed.'
        try:
            pa = list(self._portaudio())
            diagnostics['portaudio_ok'] = True
        except Exception as exc:
            diagnostics['portaudio_error'] = str(exc)
            pa = []
        self.last_diagnostics = diagnostics
        known_names = {d['name'] for d in ca}
        if not ca or any(not d.get('rate') for d in ca) or any(p['name'] not in known_names for p in pa):
            try:
                native = self._system_devices()
                diagnostics['system_profiler_ok'] = True
                if not ca:
                    ca = native
                else:
                    for d in ca:
                        matches = [n for n in native if n['name'] == d['name']]
                        if not d.get('rate') and len(matches) == 1 and matches[0]['rate_verified']:
                            d.update(rate=matches[0]['rate'], rate_source='system_profiler')
                    ca.extend(n for n in native if n['name'] not in known_names)
            except AudioError as exc:
                diagnostics['system_profiler_ok'] = False
                diagnostics['system_profiler_error'] = str(exc)
        used, out = set(), []
        if ca:
            for d in ca:
                idx = next((i for i, p in enumerate(pa) if i not in used and p["name"] == d["name"]), None)
                if idx is not None:
                    used.add(idx)
                if sum(p['name'] == d['name'] for p in pa) != 1:
                    idx = None  # duplicate names cannot establish a safe PortAudio index
                rate = int(d.get('rate') or 0)
                out.append(dict(d, index=idx, rate=rate, rate_verified=rate > 0,
                                rate_source=d.get('rate_source', 'coreaudio_helper')))
        # Never discard a device visible to PortAudio merely because a partial
        # helper inventory listed some other devices. Defaults remain unverified.
        observed_names = {d['name'] for d in out}
        for i, p in enumerate(pa):
            if p['name'] in observed_names:
                continue
            out.append(dict(index=i, uid=None, name=p["name"], inputs=p["max_input_channels"],
                            outputs=p["max_output_channels"], rate=int(p["default_samplerate"]),
                            rates=[], transport="aggregate" if "aggregate" in p["name"].lower() else "other",
                            subdevices=[], rate_verified=False, rate_source='portaudio_default', control_available=False))
        return out

    def create_aggregate(self, name, uid, main_uid, sub_uids, stacked=False):
        args = ["create", "--name", name, "--uid", uid, "--main", main_uid]
        for s in sub_uids:
            args += ["--sub", s]
        if stacked:
            args.append("--stacked")
        return self._helper(*args)

    def destroy(self, uid):
        return self._helper("destroy", "--uid", uid)

    def set_rate(self, uid, rate):
        result = self._helper("set-rate", "--uid", uid, "--rate", str(int(rate)))
        if result.get('rate') != int(rate):
            raise AudioError('Requested sample rate was not verified. Check device state before retrying.')
        return result

    def set_default(self, role, uid):
        return self._helper("set-default", "--role", role, "--uid", uid)


# ------------------------------------------------------------------ simulation
class SimAudio:
    simulated = True

    def __init__(self):
        self.lock = threading.RLock()
        self.stream_open = False
        self.devs = [
            dict(uid="AppleUSBAudioEngine:Focusrite:Scarlett 18i8 USB", name="Scarlett 18i8 USB", inputs=18,
                 outputs=8, rate=44100, rates=[44100, 48000, 88200, 96000], transport="usb", subdevices=[]),
            dict(uid="BlackHole2ch_UID", name="BlackHole 2ch", inputs=2, outputs=2, rate=48000,
                 rates=[44100, 48000], transport="virtual", subdevices=[]),
            dict(uid="BlackHole16ch_UID", name="BlackHole 16ch", inputs=16, outputs=16, rate=48000,
                 rates=[44100, 48000], transport="virtual", subdevices=[]),
            dict(uid="BuiltInSpeakerDevice", name="Mac Studio Speakers", inputs=0, outputs=2, rate=48000,
                 rates=[48000], transport="builtin", subdevices=[]),
        ]

    def helper_available(self):
        return True

    def devices(self):
        with self.lock:
            return [dict(d, index=i, default_input=False, default_output=False) for i, d in enumerate(self.devs)]

    def create_aggregate(self, name, uid, main_uid, sub_uids, stacked=False):
        with self.lock:
            if any(d["uid"] == uid for d in self.devs):
                return {"ok": True, "existed": True}
            subs = [d for d in self.devs if d["uid"] in sub_uids]
            if len(subs) != len(sub_uids):
                raise AudioError("Sub-device not found")
            main = next(d for d in subs if d["uid"] == main_uid)
            self.devs.append(dict(uid=uid, name=name, transport="aggregate", subdevices=list(sub_uids),
                                  inputs=0 if stacked else sum(d["inputs"] for d in subs),
                                  outputs=max(d["outputs"] for d in subs) if stacked else sum(d["outputs"] for d in subs),
                                  rate=main["rate"], rates=main["rates"]))
            return {"ok": True, "existed": False}

    def destroy(self, uid):
        if not uid.startswith("com.imi.sawti."):
            raise AudioError("Sawti only removes devices it created")
        with self.lock:
            self.devs = [d for d in self.devs if d["uid"] != uid]
        return {"ok": True}

    def set_rate(self, uid, rate):
        with self.lock:
            for d in self.devs:
                if d["uid"] == uid:
                    if d["rates"] and rate not in d["rates"]:
                        raise AudioError("Rate not supported")
                    d["rate"] = int(rate)
                    return {"ok": True, "rate": rate}
        raise AudioError("Device not found")

    def set_default(self, role, uid):
        return {"ok": True}


def make_audio():
    return SimAudio() if paths.simulate() else RealAudio()
