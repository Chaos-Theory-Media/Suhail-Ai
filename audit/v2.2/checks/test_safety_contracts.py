"""Audit acceptance checks. Failures document defects; no expected-failure masks.

Hardware, transcription and process spawning are replaced with deterministic
test doubles. These checks do not certify the Mac Studio integrations.
"""
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import app as web
import sawti
from studio.engine import Monitor, profile
from studio.lifecycle import Lifecycle


class SafetyAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sawti-audit-')
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(sawti, 'DB', Path(self.temp.name) / 'people.sqlite3')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.monitor = Monitor()
        self.lifecycle = Lifecycle(self.monitor)
        for name, value in [('monitor', self.monitor), ('lifecycle', self.lifecycle)]:
            p = patch.object(web, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = web.app.test_client()

    def test_off_blocks_diagnostic_and_mutation_endpoints(self):
        for path in ['/api/status', '/api/presenters', '/api/devices']:
            self.assertEqual(self.client.get(path).status_code, 503)
        with patch.object(self.monitor, 'start') as start:
            self.assertEqual(self.client.post('/api/meter/start', json={'mode': 'local'}).status_code, 503)
            start.assert_not_called()

    def test_on_does_not_automatically_open_meter_or_spawn_missing_ollama(self):
        with patch('studio.lifecycle.os.path.isfile', return_value=False), \
             patch('studio.lifecycle.shutil.which', return_value=None), \
             patch('studio.lifecycle.subprocess.Popen') as spawn, \
             patch.object(self.monitor, 'start') as start:
            response = self.client.post('/api/power/on', json={'mode': 'local'})
        self.assertTrue(response.json['on'])
        start.assert_not_called()
        spawn.assert_not_called()

    def test_invalid_mode_does_not_enable_power(self):
        self.assertEqual(self.client.post('/api/power/on', json={'mode': 'invalid'}).status_code, 400)
        self.assertFalse(self.lifecycle.on)

    def test_off_terminates_only_owned_child(self):
        child = Mock()
        child.poll.return_value = None
        self.lifecycle.child = child
        self.lifecycle.on = True
        with patch('studio.lifecycle.subprocess.Popen') as spawn:
            self.lifecycle.stop()
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=5)
        spawn.assert_not_called()

    def test_enrolment_requires_explicit_consent(self):
        with self.assertRaises(ValueError):
            sawti.enrol_name('Test presenter', False)
        self.assertEqual(sawti.people(), [])

    def test_voice_enrolment_requires_registered_consent(self):
        with patch.object(sawti, 'voice_embed', return_value=[1.0, 0.0]):
            with self.assertRaises(ValueError):
                sawti.enrol_voice('Unknown', b'test')

    def test_deletion_removes_presenter_and_embedding(self):
        sawti.enrol_name('Test presenter', True)
        with patch.object(sawti, 'voice_embed', return_value=[1.0, 0.0]):
            sawti.enrol_voice('Test presenter', b'test')
        self.assertTrue(sawti.people()[0]['enrolled'])
        sawti.remove_person('Test presenter')
        self.assertEqual(sawti.people(), [])
        with sawti.connect() as db:
            self.assertEqual(db.execute('select count(*) from people').fetchone()[0], 0)

    def test_speaker_matching_is_never_authentication(self):
        sawti.enrol_name('Test presenter', True)
        with patch.object(sawti, 'voice_embed', return_value=[1.0, 0.0]):
            sawti.enrol_voice('Test presenter', b'test')
            result = sawti.identify(b'test')
        self.assertEqual(result['name'], 'Test presenter')
        self.assertFalse(result['verified'])

    def test_unknown_speaker_stays_unnamed(self):
        with patch.object(sawti, 'voice_embed', return_value=[1.0, 0.0]):
            self.assertIsNone(sawti.identify(b'test')['name'])

    def test_rule_diagnostics_do_not_call_language_model(self):
        with patch.object(sawti, 'llm_reply') as llm:
            result = sawti.respond('mic 1 silent', 'local', {'checks': []})
        self.assertEqual(result['source'], 'rule')
        llm.assert_not_called()

    def test_stale_meter_is_not_reported_as_healthy(self):
        result = sawti.agent_status('local', [], {'running': True, 'last_audio_age': 120}, {})
        meter = next(x for x in result if x['label'] == 'Audio metering')
        self.assertNotEqual(meter['state'], 'pass', 'Stale capture is currently shown as pass')

    def test_exact_selected_model_tag_must_be_installed(self):
        response = Mock()
        response.read.return_value = json.dumps({'models': [{'name': 'qwen3:0.6b'}]}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(sawti, 'MODEL', 'qwen3:4b'), \
             patch('sawti.urllib.request.urlopen', return_value=response):
            self.assertFalse(sawti.ollama_status()['available'], 'A different model size is accepted as ready')

    def test_cross_origin_form_cannot_switch_power_off(self):
        self.lifecycle.on = True
        response = self.client.post('/api/power/off', data={'mode': 'local'},
                                    headers={'Origin': 'https://untrusted.example'})
        self.assertIn(response.status_code, (400, 403), 'No Origin/CSRF check protects power control')
        self.assertTrue(self.lifecycle.on)

    def test_off_wins_against_already_admitted_meter_start(self):
        self.lifecycle.on = True
        entered, release = threading.Event(), threading.Event()
        errors = []
        def delayed_start(mode):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Audit synchronisation timeout')
            self.monitor.stream = Mock()
            return True
        def request_start():
            try:
                with web.app.test_client() as client:
                    client.post('/api/meter/start', json={'mode': 'local'})
            except Exception as exc:
                errors.append(exc)
        with patch.object(self.monitor, 'start', side_effect=delayed_start):
            worker = threading.Thread(target=request_start)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertFalse(self.client.post('/api/power/off').json['on'])
            finally:
                release.set()
                worker.join(4)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)
        self.assertFalse(self.monitor.snapshot()['running'], 'An admitted start reopens capture after OFF')

    def test_recording_state_is_explicit_in_status(self):
        self.lifecycle.on = True
        result = self.client.get('/api/status').json
        self.assertIn('recording_state', result, 'No recording/idle/unknown state is exposed')

    def test_zoom_profile_includes_guest_return_channels(self):
        p = profile('zoom')
        self.assertGreater(p['required_input_channels'], 4, 'Current profile captures only the four assumed Scarlett channels')
        self.assertTrue(any('guest' in x['name'].lower() or 'zoom' in x['name'].lower() for x in p['sources']))

    def test_arabic_rule_prompt_receives_arabic_answer(self):
        result = sawti.respond('افحص الميكروفونات', 'local', {'checks': []})
        self.assertTrue(any('\u0600' <= c <= '\u06ff' for c in result['reply']), 'Arabic trigger returns an English rule response')

    def test_health_audit_is_connected_to_agent_endpoint(self):
        self.lifecycle.on = True
        with patch.object(web, 'getdevices', return_value=[]), \
             patch.object(web, 'ollama_status', return_value={}), \
             patch.object(web, 'audit') as health:
            self.assertEqual(self.client.get('/api/agents/local').status_code, 200)
        health.assert_called_once()
