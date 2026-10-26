"""Opt-in, operator-commissioned speech on an explicit Scarlett playback pair.

Never uses a default output, browser TTS, afplay, device setters or production
transport. The operator must test electrical and acoustic isolation on the Mac.
"""
import math
import platform
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from .coreaudio import is_scarlett

WELCOME = 'Hello, I’m Sawti, your studio assistant. I can help you prepare and check your studio.'
HEADSET_PAIR = [3, 4]  # Operator confirmed: Playback 3–4 feeds presenter outputs 3–4.


def output_map(outputs, pair):
    if (not isinstance(pair, list) or len(pair) != 2 or any(type(c) is not int for c in pair)
            or pair[0] < 3 or pair[0] % 2 != 1 or pair[1] != pair[0] + 1 or pair[1] > outputs):
        raise ValueError('Choose an explicit dedicated stereo pair above outputs 1–2 on the Scarlett.')
    mapping = [-1] * outputs
    mapping[pair[0] - 1], mapping[pair[1] - 1] = 0, 1
    return mapping


def installed_voices():
    if platform.system() != 'Darwin':
        return []
    result = subprocess.run(['/usr/bin/say', '-v', '?'], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError('macOS could not list installed speech voices.')
    voices = []
    for line in result.stdout.splitlines():
        match = re.match(r'^(.*?)\s+([a-z]{2,3}_[A-Z]{2})\s+#', line)
        if match and match[2].startswith(('en_', 'ar_')):
            voices.append(dict(name=match[1].strip(), language=match[2]))
    return voices


class PresenterSpeech:
    def __init__(self, studio):
        self.studio = studio
        self.lock = threading.RLock()
        self.route = None
        self.voice = None
        self.enabled = False
        self.tested = False
        self.phase = 'muted'
        self.error = None
        self.caption = WELCOME
        self.cancel = threading.Event()
        self.worker = None
        self.needs_restart = False

    def snapshot(self):
        with self.lock:
            return dict(enabled=self.enabled, configured=bool(self.route), test_completed=self.tested,
                        phase=self.phase, error=self.error, caption=self.caption,
                        pair=self.route['pair'] if self.route else None,
                        privacy_automatically_verified=False)

    def _device(self, uid):
        if not isinstance(uid, str) or not uid.strip():
            raise RuntimeError('A stable Scarlett device UID is required. Check the read-only audio helper; names alone are not safe.')
        matches = [d for d in self.studio.devices(fresh=True) if d.get('uid') == uid]
        if len(matches) != 1:
            raise RuntimeError('The exact Scarlett output device is unavailable or ambiguous. Speech stays muted.')
        d = matches[0]
        identity = (str(d.get('name', '')) + ' ' + str(d.get('uid', ''))).lower()
        if (not is_scarlett(d) or d.get('transport') != 'usb' or d.get('index') is None
                or '18i8' not in identity or d.get('rate_verified') is not True
                or type(d.get('rate')) is not int or d['rate'] <= 0):
            raise RuntimeError('An identified USB Scarlett with a verified current rate and engine index is required.')
        return d

    @staticmethod
    def _identity(d):
        return {k: d.get(k) for k in ('uid', 'index', 'outputs', 'rate')}

    def configure(self, uid, pair, voice, idle=False, mapped=False):
        self.studio.require_on()
        if self.needs_restart:
            raise RuntimeError('Restart Sawti before configuring speech; its previous output stream could not close.')
        if self.studio.audio.simulated or platform.system() != 'Darwin':
            raise RuntimeError('Private speech commissioning must run on the Mac; simulation never plays real audio.')
        if idle is not True or mapped is not True or self.studio.live:
            raise RuntimeError('Check all recording is idle and confirm the dedicated headphone mapping first.')
        device = self._device(uid)
        if pair != HEADSET_PAIR:
            raise ValueError('This studio’s confirmed presenter feed is USB Playback 3–4. Other pairs are not commissioned.')
        mapping = output_map(device['outputs'], pair)
        catalogue = {v['name']: v['language'] for v in installed_voices()}
        if not isinstance(voice, dict) or not voice.get('en') or set(voice) - {'en', 'ar'}:
            raise ValueError('Choose an installed English voice and optionally an Arabic voice.')
        if any(not isinstance(name, str) or not catalogue.get(name, '').startswith(language + '_')
               for language, name in voice.items()):
            raise ValueError('The selected voices must be installed and match their English/Arabic language.')
        self.stop(clear=True)
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise RuntimeError('Wait for Sawti speech to finish stopping before changing the route.')
            self.route = dict(self._identity(device), pair=list(pair), mapping=mapping)
            self.voice = dict(voice)
            self.phase = 'configured'
            self.error = None
        return self.snapshot()

    def authorise(self, attestations, idle=False):
        self.studio.require_on()
        required = ('headphones_only', 'no_recorded_speech', 'no_loopback', 'acoustic_checked')
        if (idle is not True or self.studio.live or not isinstance(attestations, dict)
                or any(attestations.get(k) is not True for k in required)):
            raise RuntimeError('Complete the headphone, recording, loopback and acoustic isolation tests while idle.')
        with self.lock:
            if not self.tested or not self.route or (self.worker and self.worker.is_alive()):
                raise RuntimeError('Finish the explicit test phrase and check its test recordings before enabling speech.')
            self._check_route()
            self.enabled = True
            self.phase = 'ready'
        return self.snapshot()

    def _check_route(self):
        if not self.route:
            raise RuntimeError('No private headset output is configured.')
        try:
            d = self._device(self.route['uid'])
        except RuntimeError:
            self.enabled = self.tested = False
            raise
        if self._identity(d) != {k: self.route[k] for k in ('uid', 'index', 'outputs', 'rate')}:
            self.enabled = self.tested = False
            raise RuntimeError('Scarlett device/rate/index changed. Reconfigure and repeat isolation tests.')
        return d

    def start(self, text, *, test=False, idle=False, confirmed=False, epoch=None):
        self.studio.require_on()
        admitted_epoch = self.studio.power_epoch if epoch is None else epoch
        if self.studio.audio.simulated or platform.system() != 'Darwin':
            raise RuntimeError('Simulation cannot synthesize or play presenter speech.')
        if admitted_epoch != self.studio.power_epoch:
            raise RuntimeError('The response belongs to an earlier powered session.')
        with self.lock:
            if self.worker and self.worker.is_alive():
                return False  # no queue of old replies to play later
            if test:
                if idle is not True or confirmed is not True or self.studio.live:
                    raise RuntimeError('Explicitly approve the test phrase while all production recording is idle.')
                text = 'Sawti private headset test. Check this voice is absent from every recording and guest feed.'
            elif not self.enabled:
                return False
            if not isinstance(text, str) or not text.strip():
                return False
            if len(text) > 700:
                raise ValueError('This answer is too long for headset speech. Read it on screen.')
            if not self.route or not self.voice:
                raise RuntimeError('No installed speech voice is selected.')
            arabic_letters = len(re.findall(r'[\u0621-\u064a\u066e-\u06d3]', text))
            language = 'ar' if arabic_letters > len(re.findall(r'[a-zA-Z]', text)) else 'en'
            selected_voice = self.voice.get(language)
            if not selected_voice:
                raise RuntimeError('No local voice is configured for this language. Read the reply on screen.')
            route = dict(self.route)
        # Slow read-only inventory must not hold up OFF. Reserve the playback
        # job under the studio lock only after it completes, in the same order
        # as Record/Go Live and the pre-test admission checks.
        try:
            device = self._device(route['uid'])
        except RuntimeError:
            self.stop()
            raise
        with self.studio.lock, self.lock:
            if not self.studio.lifecycle.on or admitted_epoch != self.studio.power_epoch:
                raise RuntimeError('Sawti power changed; this speech request was cancelled.')
            if self.route != route:
                raise RuntimeError('The private voice plan changed; retry only after verification.')
            if self._identity(device) != {k: route[k] for k in ('uid', 'index', 'outputs', 'rate')}:
                self.enabled = self.tested = False
                raise RuntimeError('Scarlett device/rate/index changed. Reconfigure and repeat isolation tests.')
            if self.worker and self.worker.is_alive():
                return False
            if test:
                if self.studio.live or self.studio.pretest.active:
                    raise RuntimeError('Finish the live show or sound check before commissioning private voice.')
                self.enabled = self.tested = False
                self.studio.approvals.invalidate()
            elif not self.enabled:
                return False
            self.cancel = threading.Event()
            self.error = None
            self.caption = text.strip()
            self.phase = 'preparing'
            self.worker = threading.Thread(target=self._run,
                args=(self.caption, route, selected_voice, self.cancel, admitted_epoch, test), daemon=True)
            self.worker.start()
            return True

    def _synthesise(self, text, voice, cancel):
        import soundfile as sf
        with tempfile.TemporaryDirectory(prefix='sawti-speech-') as folder:
            message, audio = Path(folder) / 'message.txt', Path(folder) / 'voice.aiff'
            # NSSpeechSynthesizer recognises [[...]] embedded commands. Replies
            # are literal text, not permission to change synthesis controls.
            message.write_text(text.replace('[[', '').replace(']]', ''), encoding='utf-8')
            # File output is mandatory: say must never select a playback device.
            process = subprocess.Popen(['/usr/bin/say', '-v', voice, '-o', str(audio), '-f', str(message)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 30
            try:
                while process.poll() is None:
                    if cancel.wait(0.05) or time.monotonic() > deadline:
                        process.terminate()
                        try:
                            process.wait(2)
                        except subprocess.TimeoutExpired:
                            process.kill()  # only the exact owned synthesis process
                            process.wait(2)
                        raise RuntimeError('Sawti speech synthesis cancelled or timed out.')
                if process.returncode or not audio.is_file():
                    raise RuntimeError('The selected local macOS voice could not synthesize this reply.')
                samples, rate = sf.read(audio, dtype='float32', always_2d=True)
                return samples.mean(axis=1), int(rate)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(2)

    def _run(self, text, route, voice, cancel, epoch, test):
        stream = None
        reserved = False
        finished = threading.Event()
        completed = False
        playback_fault = False
        audio = self.studio.audio
        try:
            if cancel.is_set() or epoch != self.studio.power_epoch or not self.studio.lifecycle.on:
                return
            samples, source_rate = self._synthesise(text, voice, cancel)
            if cancel.is_set() or epoch != self.studio.power_epoch:
                return
            from scipy.signal import resample_poly
            if source_rate <= 0 or len(samples) > source_rate * 30 or not np.isfinite(samples).all():
                raise RuntimeError('Speech waveform is invalid or longer than 30 seconds.')
            if source_rate != route['rate']:
                divisor = math.gcd(source_rate, route['rate'])
                samples = resample_poly(samples, route['rate'] // divisor, source_rate // divisor)
            peak = float(np.max(np.abs(samples))) if len(samples) else 0
            if not peak:
                raise RuntimeError('Speech synthesis produced no audio.')
            # Conservative digital test/reply level; headset amplifier volume is independent.
            samples = (samples / max(peak, 1.0) * 0.08).astype('float32')
            import sounddevice as sd
            position = 0
            def callback(out, frames, timing, status):
                nonlocal position, completed, playback_fault
                out.fill(0)
                if cancel.is_set() or epoch != self.studio.power_epoch or not self.studio.lifecycle.on:
                    raise sd.CallbackAbort
                if status:
                    playback_fault = True
                    cancel.set()
                    raise sd.CallbackAbort
                count = min(frames, len(samples) - position)
                out[:count, 0] = samples[position:position + count]
                out[:count, 1] = samples[position:position + count]
                position += count
                if position >= len(samples):
                    completed = True
                    raise sd.CallbackStop
            with audio.lock:
                if cancel.is_set() or epoch != self.studio.power_epoch:
                    return
                self._check_route()
                if cancel.is_set() or epoch != self.studio.power_epoch:
                    return
                audio.output_streams = getattr(audio, 'output_streams', 0) + 1
                reserved = True
                settings = sd.CoreAudioSettings(channel_map=route['mapping'], change_device_parameters=False,
                                                fail_if_conversion_required=True)
                stream = sd.OutputStream(device=route['index'], channels=2, samplerate=route['rate'],
                                         dtype='float32', extra_settings=settings, callback=callback,
                                         finished_callback=finished.set)
                stream.start()
            with self.lock:
                self.phase = 'speaking'
            deadline = time.monotonic() + len(samples) / route['rate'] + 3
            while not finished.wait(0.05):
                if cancel.is_set() or epoch != self.studio.power_epoch or time.monotonic() > deadline:
                    stream.abort()
                    break
            if not completed or cancel.is_set():
                raise RuntimeError('Speech playback did not complete; private voice is muted.')
            with self.lock:
                if test:
                    self.tested = True
                self.phase = 'test_complete' if test else 'ready'
        except Exception as exc:
            with self.lock:
                self.enabled = self.tested = False
                self.phase = 'muted'
                self.error = str(exc)[:300] if playback_fault or not cancel.is_set() else None
        finally:
            closed = True
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    closed = False
                    with self.lock:
                        self.enabled = self.tested = False
                        self.needs_restart = True
                        self.phase = 'muted'
                        self.error = 'Sawti speech output did not close. Restart Sawti before using speech again.'
            if reserved and closed:
                with audio.lock:
                    audio.output_streams = max(0, getattr(audio, 'output_streams', 1) - 1)
            with self.lock:
                if cancel.is_set():
                    self.enabled = self.tested = False
                    self.phase = 'muted'
            outcome = ('failed' if not closed or playback_fault else
                       'cancelled' if cancel.is_set() or epoch != self.studio.power_epoch else
                       'completed' if completed else 'failed')
            self.studio.learn('presenter_voice_result', ok=outcome == 'completed', test=bool(test), reason=outcome)

    def stop(self, clear=False):
        with self.lock:
            self.cancel.set()
            self.enabled = self.tested = False
            self.phase = 'muted'
            if clear:
                self.route = self.voice = None
