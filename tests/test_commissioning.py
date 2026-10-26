"""Microphone-plan isolation, session binding and honest readiness boundaries."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import testkit as helpers
from sawti import readiness, store
from sawti.agents import audition
from sawti.coreaudio import SimAudio
from sawti.studio import Studio


class CommissioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, SAWTI_DATA=str(self.root / 'data'))
        env.start()
        self.addCleanup(env.stop)
        self.st = Studio(audio=SimAudio())
        self.st.lifecycle.on = True
        self.addCleanup(self.st.power_off)
        store.put('recording_root', str(self.root / 'recordings'))
        self.client = helpers.client(self.st)

    def choose(self, inputs):
        return self.st.select_microphones(inputs, studio_idle=True)['plan']

    def template(self, inputs):
        tree = ET.parse(Path(helpers.FIXTURES) / 'podcast_template.sesx')
        tracks = tree.find('.//tracks')
        for track in list(tracks):
            if track.tag == 'audioTrack' and int(track.get('index')) not in inputs:
                tracks.remove(track)
        path = self.root / ('template-' + '-'.join(map(str, inputs)) + '.sesx')
        tree.write(path)
        audition.adopt_template(self.st, 'local', str(path))

    def test_plan_requires_presenter_and_excludes_talkback(self):
        for invalid in (None, [], [2], [1, 4], [1, 2, 3, 4], [1, 1], [True], ['1'], '1', [1.0]):
            with self.subTest(inputs=invalid), self.assertRaises(ValueError):
                self.choose(invalid)
        self.assertIsNone(self.st.mic_plan)

    def test_no_plan_blocks_preparation_and_pretest(self):
        for fn in (lambda: audition.prepare_session(self.st), self.st.pretest.start):
            with self.assertRaisesRegex(RuntimeError, 'Confirm'):
                fn()
        self.assertFalse(self.st.monitor.running)

    def test_profile_filters_only_programme_inputs_retains_talkback(self):
        for inputs in ([1], [1, 2], [1, 3], [1, 2, 3]):
            with self.subTest(inputs=inputs):
                self.choose(inputs)
                profile = self.st.profile()
                self.assertEqual([s['channels'][0] for s in profile['sources'] if s['role'] == 'programme'], inputs)
                self.assertEqual(profile['audition_tracks'], [f'Mic {i}' for i in inputs])
                self.assertEqual(next(s for s in profile['sources'] if s['role'] == 'talkback')['channels'], [4])

    def test_plan_never_mutates_audio_or_opens_apps(self):
        devices = self.st.audio.devices()
        with patch.object(self.st, 'open_app') as launch, patch.object(self.st, 'start_meter') as start:
            self.choose([1, 3])
        self.assertEqual(devices, self.st.audio.devices())
        launch.assert_not_called()
        start.assert_not_called()

    def test_plan_change_requires_idle_and_blocks_live_or_off(self):
        with self.assertRaises(RuntimeError):
            self.st.select_microphones([1])
        self.st.live = True
        with self.assertRaises(RuntimeError):
            self.choose([1])
        self.st.live = False
        self.st.power_off()
        with self.assertRaises(RuntimeError):
            self.choose([1])

    def test_selection_clears_checks_and_approvals_stops_only_owned_capture(self):
        self.choose([1, 2, 3])
        helpers.prepare_sim_audio(self.st)
        self.st.pretest.start()
        self.st.confirm('talkback')
        review = self.st.approvals.review('record')
        self.choose([1])
        self.assertFalse(self.st.pretest.active)
        self.assertFalse(self.st.monitor.running)
        self.assertFalse(self.st.approvals.pending)
        self.assertFalse(self.st.state.get('confirmed'))
        with self.assertRaises(RuntimeError):
            self.st.apply('record', approval=review['token'], operator_confirmed=True, studio_idle=True)

    def test_pretest_only_tests_selected_programme_mics(self):
        self.choose([1, 3])
        helpers.prepare_sim_audio(self.st)
        state = self.st.pretest.start()
        self.assertEqual([s['source'] for s in state['steps'] if s['kind'] == 'mic'], ['mic1', 'mic3'])
        self.assertIn('talkback', [s['id'] for s in state['steps']])

    def test_three_mic_template_is_not_adopted_for_one_mic(self):
        self.choose([1])
        with self.assertRaisesRegex(ValueError, 'count'):
            audition.adopt_template(self.st, 'local', Path(helpers.FIXTURES) / 'podcast_template.sesx')

    def test_templates_are_separate_and_session_reconfirmation_preserves_old_files(self):
        self.choose([1, 2, 3])
        self.template([1, 2, 3])
        audition.prepare_session(self.st)
        old = Path(self.st.state['session']['path'])
        original = old.read_bytes()
        self.choose([1])
        self.assertIsNone(audition.today_session(self.st, 'local'))
        self.assertIsNone(audition.template_info(self.st, 'local'))
        with self.assertRaises(RuntimeError):
            audition.prepare_session(self.st)
        self.template([1])
        audition.prepare_session(self.st)
        self.assertNotEqual(old, Path(self.st.state['session']['path']))
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(set(store.get('templates')), {'local:1', 'local:1,2,3'})

    def test_legacy_three_mic_template_remains_usable_for_three_mics(self):
        store.put('templates', {'local': str(Path(helpers.FIXTURES) / 'podcast_template.sesx')})
        self.choose([1, 2, 3])
        audition.prepare_session(self.st)
        self.assertIsNotNone(audition.today_session(self.st, 'local'))

    def test_reconfirmation_cannot_record_into_the_previously_prepared_session(self):
        self.choose([1])
        self.template([1])
        audition.prepare_session(self.st)
        self.choose([1])  # even the same channel list requires a fresh session binding
        self.st.audio.simulated = False
        with patch.object(audition, '_keystroke') as keys:
            with self.assertRaisesRegex(RuntimeError, 'Prepare and verify'):
                audition.record(self.st)
        keys.assert_not_called()

    def test_marking_live_preserves_the_selected_microphones(self):
        plan = self.choose([1, 3])
        with patch.object(self.st, 'ensure_meter', return_value=True):
            self.st.go_live()
        self.assertEqual(self.st.mic_plan, plan)

    def test_power_and_mode_changes_clear_confirmation(self):
        self.choose([1])
        self.st.set_mode('zoom')
        self.assertIsNone(self.st.mic_plan)
        self.st.set_mode('local')
        self.choose([1])
        self.st.power_off()
        self.assertIsNone(self.st.mic_plan)
        self.assertIsNone(Studio(audio=SimAudio()).mic_plan)

    def test_endpoint_enforces_idle_and_validation(self):
        path = helpers.BASE + '/api/podcast/microphones'
        for body in ({'inputs': [1]}, {'inputs': [1, 4], 'studio_idle': True}, {'inputs': [True], 'studio_idle': True}):
            self.assertEqual(self.client.post(path, json=body, headers=helpers.H).status_code, 422)
        result = self.client.post(path, json={'inputs': [1, 3], 'studio_idle': True}, headers=helpers.H)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()['plan']['inputs'], [1, 3])

    def test_readiness_cannot_claim_autonomy_from_good_meters_or_plan(self):
        self.choose([1])
        self.template([1])
        audition.prepare_session(self.st)
        with patch.object(self.st.monitor, 'snapshot', return_value={'running': True, 'stale': False}):
            result = readiness.report(self.st)
        self.assertTrue(result['session_prepared'])
        self.assertTrue(result['monitoring_fresh'])
        self.assertFalse(result['full_autonomy_ready'])
        self.assertEqual(result['recording_state'], 'unknown')

    def test_simulation_inspection_never_calls_macos(self):
        with patch('subprocess.run') as run:
            result = readiness.inspect_audition(self.st)
        run.assert_not_called()
        self.assertEqual(result['status'], 'simulation')

    def test_actual_os_and_build_are_read_without_changing_settings(self):
        with patch('platform.system', return_value='Darwin'), patch('subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '27.0.1\n'
            result = readiness.system_info()
        self.assertEqual(result['macos_version'], '27.0.1')
        self.assertIn(['/usr/bin/sw_vers', '-buildVersion'], [call.args[0] for call in run.call_args_list])

    def test_inspection_is_bounded_and_never_declares_recording_qualified(self):
        self.st.audio.simulated = False
        app = dict(bundle_id='com.adobe.AdobeAudition')
        response = json.dumps(dict(status='observed', nodes=[{'role': 'AXButton', 'name': 'Record'}]))
        with patch('platform.system', return_value='Darwin'), patch.object(audition, 'find_app', return_value=app), \
                patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, response, '')) as run:
            result = readiness.inspect_audition(self.st)
        self.assertFalse(result['qualified_for_recording'])
        self.assertEqual(result['transport_state'], 'unknown')
        self.assertEqual(run.call_args.kwargs['timeout'], 20)
        self.assertEqual(run.call_args.args[0][-1], 'com.adobe.AdobeAudition')

    def test_inspection_failure_is_not_success(self):
        self.st.audio.simulated = False
        with patch('platform.system', return_value='Darwin'), \
                patch.object(audition, 'find_app', return_value={'bundle_id': 'com.adobe.AdobeAudition'}), \
                patch('subprocess.run', side_effect=subprocess.TimeoutExpired('osascript', 20)):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                readiness.inspect_audition(self.st)

    def test_off_is_not_blocked_by_inspection_and_discards_its_late_result(self):
        entered, release = threading.Event(), threading.Event()
        results = []
        def inspect(studio):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Test inspection timed out')
            return {'status': 'observed', 'nodes': []}
        def request():
            client = helpers.client(self.st)
            results.append(client.post(helpers.BASE + '/api/audition/inspect', json={}, headers=helpers.H))
        with patch.object(readiness, 'inspect_audition', side_effect=inspect):
            worker = threading.Thread(target=request)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                response = self.client.post(helpers.BASE + '/api/power/off', json={}, headers=helpers.H)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(self.st.lifecycle.on)
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].status_code, 503)


if __name__ == '__main__':
    unittest.main()
