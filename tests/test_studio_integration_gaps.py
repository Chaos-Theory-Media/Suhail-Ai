"""Regression checks for the first real-Mac app/device integration report."""
import os
from pathlib import Path
import plistlib
import json
import types
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import testkit as helpers
from sawti import applications, store
from sawti.agents import audition, devices, mac
from sawti.coreaudio import AudioError, RealAudio, SimAudio, find_scarlett
from sawti.studio import Studio


class StudioIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, SAWTI_DATA=str(self.root / 'data'))
        env.start()
        self.addCleanup(env.stop)
        audition._bundle_cache.clear()
        self.st = Studio(audio=SimAudio())
        self.st.lifecycle.on = True
        self.addCleanup(self.st.power_off)

    def bundle(self, name, bid, title):
        path = self.root / 'Applications' / name
        (path / 'Contents').mkdir(parents=True)
        with (path / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump(dict(CFBundleIdentifier=bid, CFBundleName=title), stream)
        return path

    def test_focusrite_original_selected_instead_of_control_2(self):
        classic = self.bundle('Focusrite Control.app', 'com.focusrite.control', 'Focusrite Control')
        self.bundle('Focusrite Control 2.app', 'com.focusrite.control2', 'Focusrite Control 2')
        with patch('pathlib.Path.home', return_value=self.root):
            app = applications.discover('focusrite')
        self.assertEqual(app['path'], str(classic))

    def test_control_2_is_not_a_substitute_for_18i8_third_gen(self):
        self.bundle('Focusrite Control 2.app', 'com.focusrite.control2', 'Focusrite Control 2')
        with patch('pathlib.Path.home', return_value=self.root):
            self.assertIsNone(applications.discover('focusrite'))

    def test_audition_direct_bundle_and_actual_identifier_are_supported(self):
        path = self.bundle('Adobe Audition 2026.app', 'com.adobe.AdobeAudition', 'Adobe Audition 2026')
        with patch('pathlib.Path.home', return_value=self.root):
            app = applications.discover('audition')
        self.assertEqual(app['path'], str(path))

    def test_missing_audition_is_not_cached_forever(self):
        app = dict(path=str(self.root / 'Adobe Audition.app'), name='Audition', bundle_id='com.adobe.AdobeAudition')
        with patch('sawti.applications.discover', side_effect=[None, app]):
            self.assertIsNone(audition.find_app())
            self.assertEqual(audition.find_app(), app)

    def test_open_apps_does_not_require_or_open_a_session(self):
        self.assertFalse(self.st.settings('templates'))
        before = self.st.audio.devices()
        helpers.approved_action(self.st, 'open_studio_apps')
        self.assertIn('adobe audition', self.st.sim_apps)
        self.assertIn('focusrite control', self.st.sim_apps)
        self.assertEqual(self.st.audio.devices(), before)
        self.assertFalse(self.st.monitor.running)
        self.assertIsNone(self.st.state.get('session'))

    def test_open_apps_requires_approval_and_never_runs_on_power_on(self):
        with self.assertRaises(RuntimeError):
            self.st.apply('open_studio_apps')
        self.st.power_off()
        with patch.object(mac, 'open_studio_apps') as launch:
            self.st.power_on()
        launch.assert_not_called()
        self.assertNotIn('adobe audition', self.st.sim_apps)

    def test_os_launch_error_is_not_reported_as_success(self):
        self.st.audio.simulated = False
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='Application not found')):
            with self.assertRaisesRegex(RuntimeError, 'Application not found'):
                self.st.open_app('/Applications/Missing.app')

    def test_group_reports_partial_launch_failure(self):
        with patch.object(mac, 'open_focusrite', return_value='Focusrite launch requested'), \
             patch.object(audition, 'open_application', side_effect=RuntimeError('not installed')):
            with self.assertRaisesRegex(RuntimeError, 'not installed'):
                mac.open_studio_apps(self.st)

    def test_renamed_device_can_be_identified_by_its_scarlett_uid(self):
        item = dict(name='Studio input', uid='Focusrite:Scarlett 18i8 USB', inputs=18, transport='usb')
        self.assertIs(find_scarlett([item]), item)

    def test_failed_queries_mean_unknown_not_hardware_failure_or_unset_rate(self):
        audio = RealAudio()
        with patch.object(audio, 'helper_available', return_value=False), \
             patch.object(audio, '_portaudio', side_effect=OSError('PortAudio unavailable')), \
             patch.object(audio, '_system_devices', side_effect=AudioError('native unavailable')):
            devs = audio.devices()
        self.st.audio = audio
        findings = devices.check(self.st, 'local', devs)
        scarlett = next(f for f in findings if f['id'] == 'scarlett')
        self.assertIn('unknown', scarlett['title'])
        rate = next(f for f in findings if f['id'] == 'scarlett_rate')
        self.assertIn('unverified', rate['title'])
        self.assertIsNone(rate['action'])
        self.assertIn('PortAudio unavailable', audio.diagnostics()['portaudio_error'])

    def test_portaudio_default_48k_is_not_claimed_as_current_hardware_rate(self):
        audio = RealAudio()
        pa = [dict(name='Scarlett 18i8 USB', max_input_channels=18, max_output_channels=8, default_samplerate=48000)]
        with patch.object(audio, 'helper_available', return_value=False), patch.object(audio, '_portaudio', return_value=pa), \
             patch.object(audio, '_system_devices', side_effect=AudioError('native unavailable')):
            devs = audio.devices()
        self.st.audio = audio
        rate = next(f for f in devices.check(self.st, 'local', devs) if f['id'] == 'scarlett_rate')
        self.assertEqual(rate['severity'], 'manual')
        self.assertIsNone(rate['action'])

    def test_zero_helper_rate_is_unverified_and_has_no_set_rate_button(self):
        audio = RealAudio()
        data = [dict(uid='SC', name='Scarlett 18i8 USB', inputs=18, outputs=8, rate=0, transport='usb')]
        with patch.object(audio, 'helper_available', return_value=True), \
             patch.object(audio, '_helper', return_value={'ok': True, 'devices': data}), \
             patch.object(audio, '_portaudio', return_value=[]), \
             patch.object(audio, '_system_devices', side_effect=AudioError('native unavailable')):
            devs = audio.devices()
        self.st.audio = audio
        self.assertFalse(devs[0]['rate_verified'])
        rate = next(f for f in devices.check(self.st, 'local', devs) if f['id'] == 'scarlett_rate')
        self.assertEqual(rate['severity'], 'manual')
        self.assertIsNone(rate['action'])

    def test_verified_48k_does_not_offer_an_unnecessary_rate_change(self):
        self.st.audio.devs[0]['rate'] = 48000
        findings = devices.check(self.st, 'local', self.st.audio.devices())
        self.assertTrue(any(f['id'] == 'scarlett' and f['severity'] == 'ok' for f in findings))
        self.assertFalse(any(f.get('action') == 'set_scarlett_48k' for f in findings))

    def test_no_template_still_offers_open_audition(self):
        findings = audition.check(self.st, 'local', [])
        self.assertTrue(any(f.get('action') == 'open_audition' for f in findings))

    def test_device_diagnostics_do_not_mutate_hardware(self):
        audio = RealAudio()
        self.st.audio = audio
        with patch.object(audio, 'helper_available', return_value=False), \
             patch.object(audio, '_portaudio', side_effect=OSError('query failed')), \
             patch.object(audio, '_system_devices', side_effect=AudioError('native unavailable')), \
             patch.object(audio, 'set_rate') as set_rate:
            response = helpers.client(self.st).get(helpers.BASE + '/api/devices')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['diagnostics']['portaudio_error'], 'query failed')
        set_rate.assert_not_called()

    def test_native_mac_inventory_can_observe_scarlett_48k_without_compiled_helper(self):
        audio = RealAudio()
        native = {'SPAudioDataType': [{'_name': 'Devices', '_items': [
            {'_name': 'Scarlett 18i8 USB', 'coreaudio_device_input': 18,
             'coreaudio_device_output': 8, 'coreaudio_device_srate': 48000,
             'coreaudio_device_manufacturer': 'Focusrite', 'coreaudio_device_transport': 'USB'}]}]}
        result = SimpleNamespace(returncode=0, stdout=json.dumps(native), stderr='')
        with patch.object(audio, 'helper_available', return_value=False), \
             patch.object(audio, '_portaudio', side_effect=OSError('capture query failed')), \
             patch('sawti.coreaudio.subprocess.run', return_value=result) as run:
            devs = audio.devices()
        self.assertEqual(devs[0]['name'], 'Scarlett 18i8 USB')
        self.assertEqual(devs[0]['rate'], 48000)
        self.assertTrue(devs[0]['rate_verified'])
        self.assertEqual(devs[0]['rate_source'], 'system_profiler')
        self.assertIsNone(devs[0]['index'])
        self.assertEqual(run.call_args.args[0], ['/usr/sbin/system_profiler', 'SPAudioDataType', '-json'])
        self.st.audio = audio
        findings = devices.check(self.st, 'local', devs)
        self.assertTrue(any(f['id'] == 'scarlett' and f['severity'] == 'ok' for f in findings))
        self.assertTrue(any(f['id'] == 'capture_index' for f in findings))

    def test_native_observation_fills_unknown_helper_rate_without_setting_it(self):
        audio = RealAudio()
        item = dict(uid='SC', name='Scarlett 18i8 USB', inputs=18, outputs=8, rate=0, transport='usb')
        native = dict(item, uid=None, rate=48000, rate_verified=True)
        with patch.object(audio, 'helper_available', return_value=True), \
             patch.object(audio, '_helper', return_value={'devices': [item]}), \
             patch.object(audio, '_portaudio', return_value=[]), \
             patch.object(audio, '_system_devices', return_value=[native]), \
             patch.object(audio, 'set_rate') as setter:
            result = audio.devices()
        self.assertEqual(result[0]['rate'], 48000)
        self.assertTrue(result[0]['rate_verified'])
        setter.assert_not_called()

    def test_portaudio_refresh_error_is_not_silently_reported_as_an_empty_list(self):
        fake = types.SimpleNamespace(_terminate=Mock(), _initialize=Mock(side_effect=RuntimeError('host init failed')),
                                     query_devices=Mock(return_value=[]))
        with patch.dict('sys.modules', sounddevice=fake):
            with self.assertRaisesRegex(AudioError, 'host init failed'):
                RealAudio()._portaudio()
        fake.query_devices.assert_not_called()

    def test_partial_helper_inventory_does_not_hide_scarlett_seen_by_other_queries(self):
        audio = RealAudio()
        helper = dict(name='Built-in Speakers', uid='builtin', inputs=0, outputs=2, rate=48000)
        pa = dict(name='Scarlett 18i8 USB', max_input_channels=18, max_output_channels=8, default_samplerate=48000)
        native = dict(name=pa['name'], uid=None, inputs=18, outputs=8, rate=48000, rate_verified=True,
                      rate_source='system_profiler', control_available=False, transport='usb', subdevices=[])
        with patch.object(audio, 'helper_available', return_value=True), \
             patch.object(audio, '_helper', return_value={'devices': [helper]}), \
             patch.object(audio, '_portaudio', return_value=[pa]), \
             patch.object(audio, '_system_devices', return_value=[native]):
            result = audio.devices()
        scarlett = find_scarlett(result)
        self.assertIsNotNone(scarlett)
        self.assertEqual(scarlett['rate'], 48000)
        self.assertEqual(scarlett['index'], 0)


if __name__ == '__main__':
    unittest.main()
