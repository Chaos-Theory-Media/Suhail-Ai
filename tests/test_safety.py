"""Regression tests for defects found in the 3.0 upload. No studio hardware is used."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

import testkit as helpers
import numpy as np
import soundfile as sf

from sawti import dsp, store
from sawti.agents import post
from sawti.coreaudio import SimAudio, find_blackhole, find_uid, input_layout
from sawti.lifecycle import Lifecycle, Managed
from sawti.meter import Monitor
from sawti.studio import Studio


def approve(studio, action):
    review = studio.approvals.review(action)
    return dict(approval=review['token'], operator_confirmed=True, studio_idle=review['requires_idle'])


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, SAWTI_DATA=self.temp.name)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.st = Studio(audio=SimAudio())
        self.st.lifecycle.on = True
        self.addCleanup(self.st.power_off)
        store.put('recording_root', str(Path(self.temp.name) / 'Recordings'))
        self.c = helpers.client(self.st)

    def test_device_change_requires_fresh_scoped_approval(self):
        with self.assertRaises(RuntimeError):
            self.st.apply('set_scarlett_48k')
        self.assertEqual(self.st.audio.devices()[0]['rate'], 44100)
        grant = approve(self.st, 'set_scarlett_48k')
        self.st.apply('set_scarlett_48k', **grant)
        self.assertEqual(self.st.audio.devices()[0]['rate'], 48000)
        with self.assertRaises(RuntimeError):
            self.st.apply('set_scarlett_48k', **grant)

    def test_approval_cannot_authorise_another_action(self):
        grant = approve(self.st, 'set_scarlett_48k')
        with self.assertRaises(RuntimeError):
            self.st.apply('create_show_input', **grant)
        self.assertEqual(len(self.st.audio.devices()), 4)

    def test_approval_expires_and_state_changes_invalidate_it(self):
        grant = approve(self.st, 'set_scarlett_48k')
        with patch('sawti.safety.time.monotonic', return_value=time.monotonic() + 31):
            with self.assertRaises(RuntimeError):
                self.st.apply('set_scarlett_48k', **grant)
        grant = approve(self.st, 'set_scarlett_48k')
        self.st.audio.devs[0]['rate'] = 96000
        with self.assertRaises(RuntimeError):
            self.st.apply('set_scarlett_48k', **grant)

    def test_idle_attestation_is_required_for_audio_changes(self):
        grant = approve(self.st, 'set_scarlett_48k')
        grant['studio_idle'] = False
        with self.assertRaises(RuntimeError):
            self.st.apply('set_scarlett_48k', **grant)

    def test_transport_requires_specific_approval(self):
        transport = Mock(return_value='Stopped')
        self.st.actions['stop'].fn = transport
        with self.assertRaises(RuntimeError):
            self.st.apply('stop')
        transport.assert_not_called()
        self.st.apply('stop', **approve(self.st, 'stop'))
        transport.assert_called_once()

    def test_bulk_and_legacy_autofixes_cannot_change_audio(self):
        store.put('autofix', {'set_scarlett_48k': True, 'create_show_input': True, 'open_session': True})
        self.st.fix_all()
        self.st.run_autofixes()
        self.assertEqual(self.st.audio.devices()[0]['rate'], 44100)
        self.assertEqual(len(self.st.audio.devices()), 4)
        with self.assertRaises(ValueError):
            self.st.approve_autofix('set_scarlett_48k')
        self.st.approve_autofix('set_scarlett_48k', False)  # revocation stays possible

    def test_api_action_requires_approval(self):
        url = helpers.BASE + '/api/action'
        self.assertEqual(self.c.post(url, json={'action': 'set_scarlett_48k'}, headers=helpers.H).status_code, 422)
        review = self.c.post(helpers.BASE + '/api/action/review', json={'action': 'set_scarlett_48k'}, headers=helpers.H).json
        response = self.c.post(url, headers=helpers.H, json=dict(action='set_scarlett_48k', approval=review['token'],
                                                              operator_confirmed=True, studio_idle=True))
        self.assertEqual(response.status_code, 200, response.json)

    def test_power_on_and_simulation_do_not_spawn_services_or_change_audio(self):
        self.st.power_off()
        with patch('sawti.lifecycle.subprocess.Popen') as spawn:
            self.st.power_on()
        spawn.assert_not_called()
        self.assertEqual(self.st.audio.devices()[0]['rate'], 44100)
        self.assertFalse(self.st.monitor.running)

    def test_off_cancels_pending_approvals_and_direct_meter_start(self):
        grant = approve(self.st, 'set_scarlett_48k')
        self.st.power_off()
        with self.assertRaises(RuntimeError):
            self.st.start_meter()
        self.st.lifecycle.on = True
        with self.assertRaises(RuntimeError):
            self.st.apply('set_scarlett_48k', **grant)

    def test_off_serialises_with_inflight_capture_start(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        monitor = Mock(running=False)
        def start(config):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Test synchronisation failed')
            monitor.running = True
            return True
        monitor.start.side_effect = start
        monitor.stop.side_effect = lambda: setattr(monitor, 'running', False)
        self.st.monitor = monitor
        a = threading.Thread(target=self.st.start_meter)
        b = threading.Thread(target=lambda: (self.st.power_off(), finished.set()))
        a.start()
        try:
            self.assertTrue(entered.wait(3))
            b.start()
            self.assertFalse(finished.wait(0.05), 'OFF returned before the admitted start completed')
        finally:
            release.set()
            a.join(4)
            if b.ident is not None:
                b.join(4)
        self.assertTrue(finished.is_set())
        self.assertFalse(monitor.running)

    def test_settings_types_and_atomic_validation(self):
        url = helpers.BASE + '/api/settings'
        for data in [[], {'leveler_enabled': 'false'}, {'source_names': {'local': 'not a map'}},
                     {'show_name': {'local': {}}}, {'llm_model': 'qwen3-cloud'}]:
            self.assertEqual(self.c.post(url, json=data, headers=helpers.H).status_code, 400, data)
        before = store.get('loudness_target')
        self.assertEqual(self.c.post(url, json={'loudness_target': -18, 'true_peak': 8}, headers=helpers.H).status_code, 400)
        self.assertEqual(store.get('loudness_target'), before)

    def test_live_setting_changes_and_unqualified_inline_output_are_blocked(self):
        self.st.live = True
        self.assertEqual(self.c.post(helpers.BASE + '/api/settings', json={'leveler_output': 'Speakers'}, headers=helpers.H).status_code, 409)
        self.st.live = False
        self.st.audio.simulated = False
        self.assertEqual(self.c.post(helpers.BASE + '/api/settings', json={'leveler_enabled': True}, headers=helpers.H).status_code, 400)
        store.put('leveler_enabled', True)
        with self.assertRaisesRegex(RuntimeError, 'not qualified'):
            self.st.meter_config()

    def test_recording_state_never_inferred_from_live_flag(self):
        self.st.live = True
        self.assertEqual(self.st.snapshot()['recording_state'], 'unknown')

    def test_empty_or_malformed_requests_do_not_create_jobs(self):
        for path, data in [('/api/post/automix', {'files': []}), ('/api/post/qc', {'files': 'bad'}),
                           ('/api/chat', {'message': []}), ('/api/session/prepare', {'title': 42}),
                           ('/api/pretest/recording', {})]:
            self.assertIn(self.c.post(helpers.BASE + path, json=data, headers=helpers.H).status_code, (400, 422), path)

    def test_skipped_pretest_cannot_claim_readiness(self):
        self.st.pretest.start()
        while not self.st.pretest.state()['done']:
            result = self.st.pretest.skip()
        self.assertFalse(result['ready'])

    def test_failed_meter_does_not_start_pretest(self):
        with patch.object(self.st, 'ensure_meter', return_value=False):
            with self.assertRaises(RuntimeError):
                self.st.pretest.start()
        self.assertFalse(self.st.pretest.active)

    def test_silence_diagnosis_does_not_claim_permission_certainty(self):
        from sawti.agents import mac
        finding = next(f for f in mac.check(self.st, 'local', {'running': True, 'digital_silence': True}, [])
                       if f['id'] == 'mic_permission')
        self.assertIn('unverified', finding['title'])

    def test_missing_aggregate_subdevice_fails_closed(self):
        with self.assertRaises(RuntimeError):
            input_layout({'subdevices': ['unavailable', 'bh']}, [{'uid': 'bh', 'name': 'BlackHole 2ch', 'inputs': 2}])

    def test_wrong_blackhole_or_named_device_is_not_selected(self):
        self.assertIsNone(find_blackhole([d for d in self.st.audio.devices() if d['inputs'] != 2], 2))
        self.assertIsNone(find_uid([{'uid': 'foreign', 'name': 'Sawti Show Input'}], 'owned', 'Sawti Show Input'))

    def test_failed_stream_start_closes_allocated_stream(self):
        audio = types.SimpleNamespace(simulated=False, stream_open=False)
        stream = Mock()
        stream.start.side_effect = RuntimeError('device busy')
        fake_sd = types.SimpleNamespace(InputStream=Mock(return_value=stream))
        monitor = Monitor(audio)
        with patch.dict('sys.modules', sounddevice=fake_sd):
            self.assertFalse(monitor.start(self.st.meter_config()))
        stream.close.assert_called_once()
        self.assertFalse(audio.stream_open)

    def test_unowned_ollama_port_is_not_contacted(self):
        lc = Lifecycle()
        with patch('sawti.lifecycle.paths.ollama_binary', return_value='/fake/ollama'), \
             patch('sawti.lifecycle.port_open', return_value=True), \
             patch('sawti.lifecycle.urllib.request.urlopen') as request, \
             patch('sawti.lifecycle.subprocess.Popen') as spawn:
            lc.power_on()
        request.assert_not_called()
        spawn.assert_not_called()
        self.assertEqual(lc.ollama_state, 'failed')
        lc.power_off()

    def test_marker_only_stale_pidfile_cannot_kill_current_process(self):
        managed = Managed('audit-stale')
        managed.pidfile.write_text(json.dumps({'pid': os.getpid(), 'marker': 'python'}))
        with patch('sawti.lifecycle.os.killpg') as kill:
            self.assertFalse(managed.cleanup_stale())
        kill.assert_not_called()

    def test_v22_database_upgrade_preserves_people_and_backup(self):
        folder = Path(self.temp.name) / 'legacy'
        folder.mkdir()
        dbpath = folder / 'sawti.sqlite3'
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.executescript('CREATE TABLE events(id INTEGER PRIMARY KEY, date INTEGER, category TEXT, message TEXT);'
                            'CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, '
                            'consent INTEGER NOT NULL DEFAULT 0, embedding TEXT, created INTEGER);')
            db.execute("INSERT INTO events VALUES(1,1,'prompt','private old prompt')")
            db.execute("INSERT INTO people VALUES(1,'Presenter',1,'[1.0,0.0]',1)")
        with patch.dict(os.environ, SAWTI_DATA=str(folder)):
            self.assertEqual(store.people()[0]['name'], 'Presenter')
            store.log('migration_check', ok=True)
            self.assertEqual(len(store.events()), 1)
        with closing(sqlite3.connect(folder / 'sawti-before-v3.sqlite3')) as backup:
            self.assertEqual(backup.execute('select message from events').fetchone()[0], 'private old prompt')

    def test_large_learning_event_is_not_truncated_into_invalid_json(self):
        store.log('long', name='x' * 5000)
        self.assertEqual(len(store.events('long')[0]['name']), 5000)

    def test_go_live_does_not_claim_monitoring_when_capture_failed(self):
        with patch.object(self.st, 'ensure_meter', return_value=False):
            with self.assertRaises(RuntimeError):
                self.st.go_live()
        self.assertFalse(self.st.live)

    def test_record_without_target_session_sends_no_keystroke(self):
        from sawti.agents import audition
        with patch.object(audition, '_keystroke') as keys:
            with self.assertRaises(RuntimeError):
                self.st.apply('record', **approve(self.st, 'record'))
        keys.assert_not_called()

    def test_audio_change_invalidates_prior_manual_confirmations(self):
        self.st.confirm('talkback')
        self.st.apply('set_scarlett_48k', **approve(self.st, 'set_scarlett_48k'))
        self.assertFalse(self.st.state.get('confirmed'))

    def test_arabic_rule_reply_and_talkback_uncertainty(self):
        from sawti.agents import chat
        reply = chat.answer(self.st, 'صوتي، افحص الميكروفونات')
        self.assertTrue(any('\u0600' <= c <= '\u06ff' for c in reply['reply']))
        reply = chat.answer(self.st, 'can the guest hear the talkback?')
        self.assertIn('unverified', reply['reply'])

    def test_simulation_refuses_real_voice_processing(self):
        with patch('sawti.server.voice.transcribe') as transcribe:
            response = self.c.post(helpers.BASE + '/api/voice', data={}, headers=helpers.H)
        self.assertEqual(response.status_code, 400)
        transcribe.assert_not_called()
        self.assertFalse(self.c.get(helpers.BASE + '/api/app').json['voice']['transcribe'])

    def test_presenter_embedding_requires_consent_and_is_removed_on_delete(self):
        with self.assertRaises(ValueError):
            store.add_person('Presenter', False)
        with self.assertRaises(ValueError):
            store.set_embedding(123, [1, 0])
        store.add_person('Presenter', True)
        pid = store.people()[0]['id']
        store.set_embedding(pid, [1, 0])
        self.assertEqual(len(store.embeddings()), 1)
        store.remove_person(pid)
        self.assertEqual(store.embeddings(), [])

    def test_real_capture_refuses_an_unverified_default_rate(self):
        self.st.audio.simulated = False
        with patch.object(self.st.monitor, 'start') as start:
            self.assertFalse(self.st.start_meter())
        start.assert_not_called()
        self.assertIn('unverified', self.st.monitor.error)


class ExportSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'take.wav'
        sf.write(self.source, helpers.speech(2, -12), helpers.FS)

    def test_master_does_not_overwrite_existing_output(self):
        st = Mock(live=False)
        st.settings.side_effect = {'loudness_target': -16, 'true_peak': -1}.get
        old = self.folder / 'take_master.wav'
        old.write_bytes(b'previous export')
        result = post.master(st, self.source)
        self.assertEqual(old.read_bytes(), b'previous export')
        self.assertNotEqual(Path(result['output']).parent, self.folder)

    def test_output_name_cannot_escape_export_directory(self):
        for name in ['../take', '/tmp/take', '..', 'a\\b']:
            with self.assertRaises(ValueError):
                post._export_name(name)

    def test_direct_dsp_refuses_source_aliases(self):
        alias = self.folder / 'hardlink.wav'
        os.link(self.source, alias)
        before = self.source.read_bytes()
        with self.assertRaises(ValueError):
            dsp.master_file(self.source, alias)
        with self.assertRaises(ValueError):
            dsp.automix([self.source], self.source)
        self.assertEqual(self.source.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
