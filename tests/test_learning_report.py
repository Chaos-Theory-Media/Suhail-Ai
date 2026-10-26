"""Sharing boundary: automatic reports must exclude private learning payloads."""
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import testkit as helpers
from sawti import learning_report, store
from sawti.coreaudio import SimAudio
from sawti.studio import Studio


class LearningReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, SAWTI_DATA=str(self.root))
        env.start()
        self.addCleanup(env.stop)

    def read(self):
        return json.loads(learning_report.report_path().read_text())

    def test_new_learning_automatically_creates_and_updates_report(self):
        store.log('gain_advice', source='mic2', mode='local', delta=6)
        self.assertEqual(self.read()['events'][0]['delta'], 6)
        store.log('pretest_done', mode='local', ok=False, failed=['mic:mic2'])
        report = self.read()
        self.assertEqual(report['event_count'], 2)
        self.assertEqual(report['event_counts']['pretest_done'], 1)
        self.assertEqual(report['events'][0]['failed'], ['mic:mic2'])

    def test_private_fields_and_unrecognised_tokens_are_never_exported(self):
        secret = 'PRIVATE_TEST_MARKER'
        store.log('session_prepared', mode='local', name=secret, folder='/Users/' + secret,
                  transcript=secret, embedding=[secret], audio=secret, source=secret, check=secret)
        store.log(secret, payload=secret)
        text = learning_report.report_path().read_text()
        self.assertNotIn(secret, text)
        self.assertNotIn('/Users/', text)
        self.assertEqual(self.read()['events'][0]['kind'], 'unclassified_event')
        self.assertEqual(len(store.events()), 2)  # private local history remains intact

    def test_values_are_closed_set_or_numeric_not_arbitrary_strings(self):
        store.log('gain_advice', source='mic1', delta='private-name', inputs=[1, 4],
                  failed=['record', '/private/file.wav'], ok='private-name')
        event = self.read()['events'][0]
        self.assertNotIn('delta', event)
        self.assertNotIn('inputs', event)
        self.assertNotIn('ok', event)
        self.assertEqual(event['failed'], ['record'])

    def test_reports_include_more_than_the_default_event_query_limit(self):
        with closing(store.connect()) as db, db:
            db.executemany('INSERT INTO events(ts,kind,data) VALUES (?,?,?)',
                           [(1700000000 + i, 'chat_intent', '{"intent":"levels"}') for i in range(2101)])
        learning_report.refresh()
        self.assertEqual(self.read()['event_count'], 2101)

    def test_failed_atomic_replace_preserves_old_report_and_working_history(self):
        store.log('pretest_started', mode='local')
        original = learning_report.report_path().read_bytes()
        with patch('sawti.learning_report.os.replace', side_effect=OSError('disk unavailable')):
            store.log('show_ended', minutes=5)
        self.assertEqual(learning_report.report_path().read_bytes(), original)
        self.assertTrue(learning_report.status()['stale'])
        self.assertEqual(len(store.events()), 2)
        self.assertFalse(list(learning_report.folder().glob('*.tmp')))
        learning_report.refresh()
        self.assertFalse(learning_report.status()['stale'])
        self.assertEqual(self.read()['event_count'], 2)

    def test_forget_clears_the_local_report(self):
        store.log('gain_advice', source='mic2', delta=6)
        store.clear_learning()
        self.assertEqual(self.read()['events'], [])
        self.assertEqual(self.read()['event_counts'], {})

    def test_failed_reset_warns_that_old_report_remains(self):
        store.log('gain_advice', source='mic2', delta=6)
        with patch('sawti.learning_report.os.replace', side_effect=OSError('read only')):
            with self.assertRaisesRegex(RuntimeError, 'old file may remain'):
                store.clear_learning()
        self.assertEqual(store.events(), [])
        self.assertTrue(learning_report.status()['stale'])

    def test_report_does_not_follow_symlinks_or_overwrite_an_external_file(self):
        external = self.root / 'private-notes.json'
        external.write_text('PRIVATE')
        learning_report.folder()
        target = self.root / 'learning_reports' / 'Sawti-Learnings.json'
        target.symlink_to(external)
        store.log('pretest_started')
        self.assertEqual(external.read_text(), 'PRIVATE')
        self.assertTrue(learning_report.status()['stale'])

    def test_report_file_is_private(self):
        store.log('pretest_started')
        self.assertEqual(learning_report.report_path().stat().st_mode & 0o777, 0o600)

    def test_download_and_failure_history_use_local_api_without_upload(self):
        studio = Studio(audio=SimAudio())
        studio.lifecycle.on = True
        self.addCleanup(studio.power_off)
        client = helpers.client(studio)
        client.post(helpers.BASE + '/api/podcast/microphones', json={'inputs': [1, 4]}, headers=helpers.H)
        events = self.read()['events']
        self.assertEqual(events[0]['kind'], 'operation_failed')
        self.assertEqual(events[0]['operation'], '/api/podcast/microphones')
        response = client.get(helpers.BASE + '/api/learning/report/download')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertEqual(json.loads(response.data)['application'], 'Sawti')
        response.close()
        studio.power_off()
        self.assertEqual(client.get(helpers.BASE + '/api/learning/report/download').status_code, 503)


if __name__ == '__main__':
    unittest.main()
