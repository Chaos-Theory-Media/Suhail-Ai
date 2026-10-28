"""Saved-session discovery and adoption: filesystem fixtures, never native Audition."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

import testkit as helpers
from sawti import paths, store, template_catalog
from sawti.agents import audition
from sawti.studio import Studio


class TemplateCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, SAWTI_DATA=str(self.root / 'Sawti'))
        self.env.start()
        self.st = Studio()
        self.st.lifecycle.on = True
        self.st.select_microphones([1, 2], studio_idle=True)
        store.put('recording_root', str(self.root / 'recordings'))
        self.client = helpers.client(self.st)
        self.files = self.root / 'saved'
        self.files.mkdir()
        self.source = self.fixture(self.files / 'Two people.sesx')

    def tearDown(self):
        self.st.power_off()
        self.env.stop()
        self.temp.cleanup()

    def fixture(self, path, tracks=2, media=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.parse(Path(helpers.FIXTURES) / 'podcast_template.sesx')
        container = tree.find('.//tracks')
        for track in list(container):
            if track.tag == 'audioTrack' and int(track.get('index')) > tracks:
                container.remove(track)
        if media:
            ET.SubElement(tree.find('.//audioTrack'), 'audioClip', id='recorded-take')
        tree.write(path)
        return path

    def post(self, path, data):
        return self.client.post(helpers.BASE + path, json=data, headers=helpers.H)

    def search(self):
        response = self.post('/api/audition/templates/search', {'folder': str(self.files)})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json['files']

    def preview(self, choice):
        return self.post('/api/audition/templates/inspect', {'id': choice['id']})

    def adopt(self, choice, info):
        return self.post('/api/audition/templates/use', {'id': choice['id'], 'sha256': info['sha256'],
                         'studio_idle': True, 'blank_template_confirmed': True})

    def test_search_and_preview_are_read_only_and_do_not_open_apps_or_audio(self):
        before = self.source.read_bytes()
        with patch.object(self.st, 'open_app') as open_app, patch.object(self.st, 'start_meter') as meter, \
                patch.object(audition, '_keystroke') as keys:
            choices = self.search()
            self.assertEqual(len(choices), 1)
            response = self.preview(choices[0])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['matches_plan'])
        self.assertEqual(response.json['template']['sample_rate'], 48000)
        self.assertEqual(len(response.json['template']['tracks']), 2)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(store.get('templates'))
        open_app.assert_not_called(); meter.assert_not_called(); keys.assert_not_called()

    def test_discovery_finds_uppercase_extensions_and_nested_files(self):
        self.fixture(self.files / 'nested/Guest.SESX')
        (self.files / 'not-a-template.wav').write_bytes(b'not a session')
        self.assertEqual(len(self.search()), 2)

    def test_symlink_files_hidden_files_and_linked_folders_are_skipped(self):
        outside = self.fixture(self.root / 'outside/Other.sesx')
        (self.files / 'Alias.sesx').symlink_to(outside)
        (self.files / 'linked').symlink_to(outside.parent, target_is_directory=True)
        self.fixture(self.files / '.hidden/Hidden.sesx')
        self.assertEqual([r['name'] for r in self.search()], [self.source.name])

    def test_scan_reports_limits_and_permission_failures(self):
        result = template_catalog.scan([self.files], max_entries=0)
        self.assertTrue(result['limited'])
        self.assertEqual(result['files'], [])
        with patch('sawti.template_catalog.os.scandir', side_effect=PermissionError):
            result = template_catalog.scan([self.files])
        self.assertTrue(result['warnings'])

    def test_specific_folder_required_and_simulation_does_not_scan_real_home(self):
        self.assertEqual(self.post('/api/audition/templates/search', {'folder': '/'}).status_code, 422)
        self.assertEqual(self.post('/api/audition/templates/search', {'folder': str(Path.home())}).status_code, 422)
        self.assertEqual(self.post('/api/audition/templates/search', {'folder': '/tmp/..'}).status_code, 422)
        roots = template_catalog.default_roots(self.st)
        self.assertTrue(all(str(p).startswith(str(paths.data_dir())) for p in roots))

    def test_real_default_locations_include_documents_music_and_adobe_preferences(self):
        self.st.audio.simulated = False
        try:
            with patch('sawti.template_catalog.Path.home', return_value=self.root):
                roots = template_catalog.default_roots(self.st)
        finally:
            self.st.audio.simulated = True
        self.assertIn(self.root / 'Documents', roots)
        self.assertIn(self.root / 'Music', roots)
        self.assertIn(self.root / 'Library/Preferences/Adobe/Audition', roots)

    def test_adoption_copies_file_and_invalidates_old_session_without_touching_its_files(self):
        audition.adopt_template(self.st, 'local', self.source)
        audition.prepare_session(self.st, title='Existing episode')
        episode = Path(self.st.state['session']['path'])
        episode_bytes = episode.read_bytes()
        self.st.state['confirmed'] = {'local:device': 'today'}
        with patch.object(self.st.presenter_speech, 'stop') as voice, patch.object(audition, '_keystroke') as keys:
            choice = self.search()[0]
            response = self.adopt(choice, self.preview(choice).json['template'])
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(audition.today_session(self.st, 'local'))
        self.assertEqual(self.st.state['confirmed'], {})
        self.assertEqual(episode.read_bytes(), episode_bytes)
        self.assertEqual(Path(store.get('templates')['local:1,2']).read_bytes(), self.source.read_bytes())
        voice.assert_called_once_with(clear=True); keys.assert_not_called()

    def test_copying_current_sawti_template_to_itself_is_safe(self):
        audition.adopt_template(self.st, 'local', self.source)
        current = Path(store.get('templates')['local:1,2'])
        original = current.read_bytes()
        audition.adopt_template(self.st, 'local', current)
        self.assertEqual(current.read_bytes(), original)

    def test_recorded_episode_is_listed_but_cannot_be_adopted(self):
        self.fixture(self.source, media=True)
        choice = self.search()[0]
        preview = self.preview(choice)
        self.assertTrue(preview.json['template']['contains_media'])
        self.assertEqual(self.adopt(choice, preview.json['template']).status_code, 422)
        self.assertFalse(store.get('templates'))

    def test_media_file_references_also_block_adoption(self):
        tree = ET.parse(self.source)
        ET.SubElement(tree.getroot(), 'file', relativePath='recorded.wav')
        tree.write(self.source)
        with self.assertRaises(ValueError):
            audition.adopt_template(self.st, 'local', self.source)

    def test_changed_file_must_be_inspected_again(self):
        choice = self.search()[0]
        preview = self.preview(choice).json['template']
        self.source.write_bytes(self.source.read_bytes() + b'\n')
        self.assertEqual(self.adopt(choice, preview).status_code, 422)
        self.assertFalse(store.get('templates'))

    def test_plan_changes_invalidate_old_choices_even_with_same_mic_count(self):
        choice = self.search()[0]
        self.st.select_microphones([1, 3], studio_idle=True)
        self.assertEqual(self.preview(choice).status_code, 422)

    def test_old_search_ids_and_arbitrary_paths_are_not_accepted_as_choices(self):
        choice = self.search()[0]
        self.search()
        self.assertEqual(self.preview(choice).status_code, 422)
        self.assertEqual(self.post('/api/audition/templates/inspect', {'id': str(self.source)}).status_code, 422)

    def test_wrong_track_count_is_previewed_and_adoption_rejected(self):
        self.fixture(self.source, tracks=3)
        choice = self.search()[0]
        response = self.preview(choice)
        self.assertFalse(response.json['matches_plan'])
        self.assertEqual(self.adopt(choice, response.json['template']).status_code, 422)

    def test_adoption_requires_both_attestations_and_is_blocked_live(self):
        choice = self.search()[0]
        info = self.preview(choice).json['template']
        self.assertEqual(self.post('/api/audition/templates/use', {'id': choice['id'], 'sha256': info['sha256']}).status_code, 400)
        self.st.live = True
        self.assertEqual(self.adopt(choice, info).status_code, 400)
        self.assertEqual(self.post('/api/audition/template', {'path': str(self.source), 'studio_idle': True,
                                                               'blank_template_confirmed': True}).status_code, 400)
        self.st.live = False

    def test_invalid_xml_and_wrong_root_have_readable_errors(self):
        for content in (b'not XML', b'<unrelated/>'):
            self.source.write_bytes(content)
            self.assertEqual(self.preview(self.search()[0]).status_code, 422)

    def test_large_files_and_final_symlinks_are_not_read_as_templates(self):
        large = self.files / 'huge.sesx'
        with large.open('wb') as stream:
            stream.truncate(8 * 1024**2 + 1)
        with self.assertRaises(ValueError):
            audition.parse_sesx(large)
        alias = self.files / 'link.sesx'
        alias.symlink_to(self.source)
        with self.assertRaises(OSError):
            audition.parse_sesx(alias)

    def test_slow_search_does_not_block_off_or_return_old_choices(self):
        entered, release = threading.Event(), threading.Event()
        def slow_scan(*args, **kwargs):
            entered.set(); release.wait(3)
            return {'files': [], 'warnings': [], 'limited': False}
        results = []
        def search_request():
            with helpers.client(self.st) as client:
                results.append(client.post(helpers.BASE + '/api/audition/templates/search', headers=helpers.H, json={}))
        with patch('sawti.template_catalog.scan', side_effect=slow_scan):
            thread = threading.Thread(target=search_request)
            thread.start(); self.assertTrue(entered.wait(2))
            self.st.power_off(); release.set(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status_code, 503)
        self.assertFalse(self.st.template_catalog.choices)

    def test_off_during_source_read_prevents_adoption(self):
        original = audition.read_session
        def switch_off(path):
            data = original(path)
            self.st.power_off()
            return data
        with patch('sawti.agents.audition.read_session', side_effect=switch_off):
            response = self.post('/api/audition/template', {'path': str(self.source), 'studio_idle': True,
                                                          'blank_template_confirmed': True})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(store.get('templates'))


if __name__ == '__main__':
    unittest.main()
