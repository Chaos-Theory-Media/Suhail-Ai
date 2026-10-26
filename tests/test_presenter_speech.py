"""Private speech routing contracts; no real sound, macOS voice or device is used."""
import copy
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import testkit as helpers
import numpy as np
from sawti.coreaudio import RealAudio, SimAudio
from sawti.presenter_speech import PresenterSpeech, installed_voices as read_catalogue, output_map
from sawti.studio import Studio


class DummyAudio:
    simulated = False
    def __init__(self):
        self.lock = threading.RLock()
        self.stream_open = False
        self.output_streams = 0
        self.device = dict(uid='Scarlett:test', name='Scarlett 18i8 USB', transport='usb', index=7,
                           inputs=18, outputs=8, rate=48000, rate_verified=True)
    def devices(self):
        return [copy.deepcopy(self.device)]


class StopCallback(Exception):
    pass


class AbortCallback(Exception):
    pass


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, SAWTI_DATA=self.temp.name)
        env.start()
        self.addCleanup(env.stop)
        self.audio = DummyAudio()
        self.st = Studio(audio=self.audio)
        self.st.lifecycle.on = True
        self.speech = self.st.presenter_speech
        self.addCleanup(self.st.power_off)
        self.mac = patch('sawti.presenter_speech.platform.system', return_value='Darwin')
        self.mac.start()
        self.addCleanup(self.mac.stop)
        voices = patch('sawti.presenter_speech.installed_voices', return_value=[
            {'name': 'Samantha', 'language': 'en_US'}, {'name': 'Laila', 'language': 'ar_SA'}])
        voices.start()
        self.addCleanup(voices.stop)

    def configure(self):
        return self.speech.configure('Scarlett:test', [3, 4], {'en': 'Samantha', 'ar': 'Laila'}, idle=True, mapped=True)

    def driver(self):
        streams = []
        def output(**kwargs):
            stream = Mock()
            stream.options = kwargs
            stream.audio = None
            def start():
                chunks = []
                for _ in range(100):
                    data = np.full((8, 2), np.nan, dtype='float32')
                    try:
                        kwargs['callback'](data, 8, None, False)
                    except (StopCallback, AbortCallback):
                        chunks.append(data.copy())
                        break
                    chunks.append(data.copy())
                stream.audio = np.concatenate(chunks)
                kwargs['finished_callback']()
            stream.start.side_effect = start
            streams.append(stream)
            return stream
        settings = Mock(side_effect=lambda **kwargs: kwargs)
        module = SimpleNamespace(CoreAudioSettings=settings, OutputStream=Mock(side_effect=output),
                                 CallbackStop=StopCallback, CallbackAbort=AbortCallback)
        return module, streams

    def test_channel_map_never_connects_main_outputs_or_unselected_channels(self):
        self.assertEqual(output_map(8, [3, 4]), [-1, -1, 0, 1, -1, -1, -1, -1])
        self.assertEqual(output_map(8, [5, 6]), [-1, -1, -1, -1, 0, 1, -1, -1])
        for pair in ([1, 2], [0, 1], [2, 3], [3, 5], [9, 10], [True, 4], [], None):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                output_map(8, pair)

    def test_default_is_muted_without_startup_playback(self):
        self.assertFalse(self.speech.snapshot()['enabled'])
        self.assertIsNone(self.speech.worker)
        with patch.object(self.speech, '_synthesise') as synth:
            self.assertFalse(self.speech.start('Welcome.'))
        synth.assert_not_called()

    def test_configuration_requires_idle_and_mapping_acknowledgement(self):
        for idle, mapped in ((False, True), (True, False), (1, True)):
            with self.assertRaises(RuntimeError):
                self.speech.configure('Scarlett:test', [3, 4], {'en': 'Samantha'}, idle=idle, mapped=mapped)

    def test_wrong_unverified_aggregate_or_disappeared_device_is_rejected(self):
        for changes in ({'uid': 'another'}, {'transport': 'aggregate'}, {'rate_verified': False},
                        {'rate': 0}, {'index': None}, {'name': 'Mac speakers', 'uid': 'BuiltInSpeaker', 'transport': 'builtin'}):
            original = copy.deepcopy(self.audio.device)
            self.audio.device.update(changes)
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.configure()
            self.audio.device = original

    def test_native_name_only_fallback_cannot_substitute_for_a_stable_device_uid(self):
        self.audio.device['uid'] = None
        with self.assertRaisesRegex(RuntimeError, 'stable Scarlett device UID'):
            self.speech.configure(None, [3, 4], {'en': 'Samantha'}, idle=True, mapped=True)
        self.assertIsNone(self.speech.worker)

    def test_only_installed_language_matching_voices_are_allowed(self):
        for voices in ({'en': 'Not installed'}, {'en': 'Laila'}, {'ar': 'Laila'}, 'Samantha'):
            with self.subTest(voices=voices), self.assertRaises(ValueError):
                self.speech.configure('Scarlett:test', [3, 4], voices, idle=True, mapped=True)

    def test_other_output_pairs_cannot_replace_the_operators_confirmed_headset_feed(self):
        with self.assertRaisesRegex(ValueError, 'not commissioned'):
            self.speech.configure('Scarlett:test', [5, 6], {'en': 'Samantha'}, idle=True, mapped=True)

    def test_installed_voice_catalogue_handles_names_with_spaces_and_filters_languages(self):
        text = 'Samantha en_US # Hello\nLaila Enhanced ar_SA # مرحباً\nAnna de_DE # Hallo\n'
        with patch('sawti.presenter_speech.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=text)) as run:
            voices = read_catalogue()
        self.assertEqual(voices, [{'name': 'Samantha', 'language': 'en_US'}, {'name': 'Laila Enhanced', 'language': 'ar_SA'}])
        self.assertEqual(run.call_args.args[0], ['/usr/bin/say', '-v', '?'])

    def test_enable_requires_a_completed_test_and_every_isolation_attestation(self):
        self.configure()
        checks = dict(headphones_only=True, no_recorded_speech=True, no_loopback=True, acoustic_checked=True)
        with self.assertRaises(RuntimeError):
            self.speech.authorise(checks, idle=True)
        self.speech.tested = True
        for key in checks:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.speech.authorise(dict(checks, **{key: False}), idle=True)
        self.assertTrue(self.speech.authorise(checks, idle=True)['enabled'])
        self.assertFalse(self.speech.snapshot()['privacy_automatically_verified'])

    def test_test_phrase_requires_specific_idle_authorisation(self):
        self.configure()
        for idle, confirmed in ((False, True), (True, False)):
            with self.assertRaises(RuntimeError):
                self.speech.start('', test=True, idle=idle, confirmed=confirmed)
        self.st.live = True
        with self.assertRaises(RuntimeError):
            self.speech.start('', test=True, idle=True, confirmed=True)
        self.st.live = False

    def test_playback_uses_exact_device_two_stream_channels_and_coreaudio_map_without_device_changes(self):
        self.configure()
        driver, streams = self.driver()
        before = copy.deepcopy(self.audio.device)
        with patch.dict('sys.modules', sounddevice=driver), \
             patch.object(self.speech, '_synthesise', return_value=(np.ones(8, dtype='float32'), 48000)):
            self.assertTrue(self.speech.start('', test=True, idle=True, confirmed=True))
            self.speech.worker.join(2)
        self.assertFalse(self.speech.worker.is_alive())
        self.assertEqual(streams[0].options['device'], 7)
        self.assertEqual(streams[0].options['samplerate'], 48000)
        self.assertEqual(streams[0].options['channels'], 2)
        self.assertEqual(streams[0].options['extra_settings'], dict(
            channel_map=[-1, -1, 0, 1, -1, -1, -1, -1], change_device_parameters=False, fail_if_conversion_required=True))
        self.assertLessEqual(float(np.max(streams[0].audio)), 0.081)
        self.assertEqual(self.audio.device, before)
        self.assertEqual(self.audio.output_streams, 0)
        self.assertTrue(self.speech.tested)
        self.assertFalse(self.speech.enabled)
        streams[0].close.assert_called_once()

    def test_output_open_failure_mutes_without_falling_back_to_default_device(self):
        self.configure()
        driver, _ = self.driver()
        driver.OutputStream.side_effect = RuntimeError('Device failed')
        with patch.dict('sys.modules', sounddevice=driver), \
             patch.object(self.speech, '_synthesise', return_value=(np.ones(8, dtype='float32'), 48000)):
            self.speech.start('', test=True, idle=True, confirmed=True)
            self.speech.worker.join(2)
        driver.OutputStream.assert_called_once()
        self.assertFalse(self.speech.enabled)
        self.assertFalse(self.speech.tested)
        self.assertEqual(self.audio.output_streams, 0)

    def test_speech_is_resampled_without_requesting_a_different_device_rate(self):
        self.configure()
        driver, streams = self.driver()
        with patch.dict('sys.modules', sounddevice=driver), \
             patch.object(self.speech, '_synthesise', return_value=(np.ones(8, dtype='float32'), 22050)):
            self.speech.start('', test=True, idle=True, confirmed=True)
            self.speech.worker.join(2)
        self.assertTrue(self.speech.tested)
        self.assertEqual(streams[0].options['samplerate'], 48000)
        self.assertEqual(self.audio.device['rate'], 48000)

    def test_learning_report_contains_voice_outcomes_but_no_spoken_text_or_route_identity(self):
        from sawti import learning_report
        self.configure()
        self.speech.enabled = True
        driver, _ = self.driver()
        with patch.dict('sys.modules', sounddevice=driver), \
             patch.object(self.speech, '_synthesise', return_value=(np.ones(8, dtype='float32'), 48000)):
            self.speech.start('PRIVATE-TTS-CONTENT')
            self.speech.worker.join(2)
        report = learning_report.report_path().read_text()
        self.assertIn('presenter_voice_result', report)
        for private in ('PRIVATE-TTS-CONTENT', 'Samantha', 'Scarlett:test'):
            self.assertNotIn(private, report)

    def test_close_failure_blocks_reuse_and_portaudio_refresh_until_restart(self):
        self.configure()
        driver, streams = self.driver()
        make = driver.OutputStream.side_effect
        def broken_close(**kwargs):
            stream = make(**kwargs)
            stream.close.side_effect = RuntimeError('close failed')
            return stream
        driver.OutputStream.side_effect = broken_close
        with patch.dict('sys.modules', sounddevice=driver), \
             patch.object(self.speech, '_synthesise', return_value=(np.ones(8, dtype='float32'), 48000)):
            self.speech.start('', test=True, idle=True, confirmed=True)
            self.speech.worker.join(2)
        self.assertFalse(self.speech.tested)
        self.assertTrue(self.speech.needs_restart)
        self.assertEqual(self.audio.output_streams, 1)
        with self.assertRaisesRegex(RuntimeError, 'Restart'):
            self.configure()

    def test_test_admission_blocks_go_live_and_sound_check(self):
        self.configure()
        entered, release = threading.Event(), threading.Event()
        def synth(*args):
            entered.set()
            release.wait(2)
            return np.ones(8, dtype='float32'), 48000
        with patch.object(self.speech, '_synthesise', side_effect=synth):
            self.speech.start('', test=True, idle=True, confirmed=True)
            self.assertTrue(entered.wait(1))
            try:
                with self.assertRaisesRegex(RuntimeError, 'headset test'):
                    self.st.go_live()
                with self.assertRaisesRegex(RuntimeError, 'headset test'):
                    self.st.pretest.start()
            finally:
                self.speech.stop()
                release.set()
                self.speech.worker.join(2)

    def test_live_show_or_active_pretest_cannot_start_commissioning(self):
        self.configure()
        self.st.pretest.active = True
        with self.assertRaisesRegex(RuntimeError, 'sound check'):
            self.speech.start('', test=True, idle=True, confirmed=True)
        self.st.pretest.active = False
        self.st.live = True
        with self.assertRaises(RuntimeError):
            self.speech.start('', test=True, idle=True, confirmed=True)
        self.st.live = False

    def test_mixed_english_name_uses_english_voice_and_arabic_uses_arabic_voice(self):
        self.configure()
        driver, _ = self.driver()
        self.speech.enabled = True
        with patch.dict('sys.modules', sounddevice=driver), \
             patch.object(self.speech, '_synthesise', return_value=(np.ones(8, dtype='float32'), 48000)) as synth:
            self.speech.start('I am Sawti (صوتي), your studio assistant.')
            self.speech.worker.join(2)
            self.assertEqual(synth.call_args.args[1], 'Samantha')
            self.speech.start('أنا صوتي، مساعدتك في الاستوديو.')
            self.speech.worker.join(2)
            self.assertEqual(synth.call_args.args[1], 'Laila')

    def test_disappearing_device_revokes_voice_enablement(self):
        self.configure()
        self.speech.enabled = True
        self.audio.device['uid'] = 'disappeared'
        with self.assertRaises(RuntimeError):
            self.speech.start('Hello.')
        self.assertFalse(self.speech.enabled)

    def test_off_during_synthesis_never_opens_an_output_stream(self):
        self.configure()
        entered, release = threading.Event(), threading.Event()
        def synth(*args):
            entered.set()
            release.wait(2)
            return np.ones(8, dtype='float32'), 48000
        driver, _ = self.driver()
        with patch.dict('sys.modules', sounddevice=driver), patch.object(self.speech, '_synthesise', side_effect=synth):
            self.speech.start('', test=True, idle=True, confirmed=True)
            self.assertTrue(entered.wait(1))
            self.st.power_off()
            release.set()
            self.speech.worker.join(2)
        driver.OutputStream.assert_not_called()
        self.assertFalse(self.speech.enabled)
        self.assertIsNone(self.speech.route)

    def test_off_during_playback_aborts_only_owned_output_and_silences_subsequent_callback(self):
        self.configure()
        ready = threading.Event()
        chunks = []
        stream = Mock()
        def output(**kwargs):
            def render():
                data = np.full((8, 2), np.nan, dtype='float32')
                try:
                    kwargs['callback'](data, 8, None, False)
                except (StopCallback, AbortCallback):
                    pass
                chunks.append(data)
            def start():
                render()
                ready.set()
            def abort():
                render()
                kwargs['finished_callback']()
            stream.start.side_effect = start
            stream.abort.side_effect = abort
            return stream
        driver = SimpleNamespace(CoreAudioSettings=lambda **kwargs: kwargs, OutputStream=output,
                                 CallbackStop=StopCallback, CallbackAbort=AbortCallback)
        with patch.dict('sys.modules', sounddevice=driver), \
             patch.object(self.speech, '_synthesise', return_value=(np.ones(32, dtype='float32'), 48000)):
            self.speech.start('', test=True, idle=True, confirmed=True)
            self.assertTrue(ready.wait(1))
            self.st.power_off()
            self.speech.worker.join(2)
        self.assertFalse(self.speech.worker.is_alive())
        self.assertTrue(np.any(chunks[0]))
        self.assertTrue(np.all(chunks[-1] == 0))
        stream.abort.assert_called_once()
        stream.close.assert_called_once()
        self.assertEqual(self.audio.output_streams, 0)
        self.assertFalse(self.speech.enabled)

    def test_changed_rate_invalidates_qualification_before_synthesis(self):
        self.configure()
        self.speech.tested = self.speech.enabled = True
        self.audio.device['rate'] = 44100
        with patch.object(self.speech, '_synthesise') as synth:
            with self.assertRaises(RuntimeError):
                self.speech.start('Hello.')
        synth.assert_not_called()
        self.assertFalse(self.speech.enabled)

    def test_old_power_epoch_cannot_speak_in_a_new_session(self):
        self.configure()
        self.speech.enabled = True
        with self.assertRaises(RuntimeError):
            self.speech.start('Old reply', epoch=-1)

    def test_meter_device_and_mode_changes_mute_private_voice(self):
        self.configure()
        self.speech.enabled = True
        self.st.select_microphones([1], studio_idle=True)
        self.assertFalse(self.speech.enabled)
        self.assertIsNone(self.speech.route)
        self.configure()
        self.st.set_mode('zoom')
        self.assertIsNone(self.speech.route)

    def test_portaudio_is_not_reinitialised_while_private_output_exists(self):
        audio = RealAudio()
        audio.output_streams = 1
        driver = SimpleNamespace(_terminate=Mock(), _initialize=Mock(), query_devices=Mock(return_value=[]))
        with patch.dict('sys.modules', sounddevice=driver):
            audio._portaudio()
        driver._terminate.assert_not_called()
        driver._initialize.assert_not_called()

    def test_simulation_cannot_start_private_audio(self):
        sim = Studio(audio=SimAudio())
        sim.lifecycle.on = True
        self.addCleanup(sim.power_off)
        with self.assertRaises(RuntimeError):
            sim.presenter_speech.start('Hello', test=True, idle=True, confirmed=True)
        self.assertIsNone(sim.presenter_speech.worker)

    def test_synthesis_is_file_only_and_owned_temporary_text_is_removed(self):
        calls = []
        texts = []
        def spawn(command, **kwargs):
            calls.append(command)
            texts.append(Path(command[-1]).read_text())
            Path(command[command.index('-o') + 1]).write_bytes(b'aiff')
            return SimpleNamespace(returncode=0, poll=lambda: 0)
        with patch('sawti.presenter_speech.subprocess.Popen', side_effect=spawn), \
             patch('soundfile.read', return_value=(np.ones((8, 1), dtype='float32'), 48000)):
            self.speech._synthesise('Hello [[volm 1]] presenter', 'Samantha', threading.Event())
        self.assertEqual(calls[0][:3], ['/usr/bin/say', '-v', 'Samantha'])
        self.assertIn('-o', calls[0])
        self.assertIn('-f', calls[0])
        self.assertNotIn('[[', texts[0])
        self.assertFalse(Path(calls[0][calls[0].index('-o') + 1]).exists())
        self.assertFalse(Path(calls[0][-1]).exists())


if __name__ == '__main__':
    unittest.main()
