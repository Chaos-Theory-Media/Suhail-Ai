"""Clean uninstall in fake home directories; never touches real apps/audio."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('clean_uninstall', ROOT / 'helpers/uninstall.py')
clean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clean)


class FakeProcesses:
    def __init__(self):
        self.active = set()
        self.verified = set()
        self.stopped = []
    def identity_matches(self, record):
        pid = record['pid']
        return pid in self.active and pid in self.verified
    def related(self, source, support):
        return set(self.active)
    def stop(self, record):
        self.stopped.append(record['pid'])
        self.active.remove(record['pid'])


class FakeDevices:
    def __init__(self):
        self.removed = []
        self.fail = False
        self.rows = [dict(uid=clean.DEVICE_UIDS[0], name='Sawti Show Input', running_somewhere=False,
                          default_input=False, default_output=False, default_system=False, subdevices=[])]
    def preview(self):
        return self.rows
    def remove(self, uid):
        if self.fail:
            raise RuntimeError('Device became busy; retained')
        self.removed.append(uid)


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.source = self.home / 'Documents/Studio source'
        self.source.mkdir(parents=True)
        (self.source / 'app.py').write_text('print("source")\n')
        clean.save_json(self.source / 'install-source-manifest.json',
                        dict(schema=1, files={'app.py': clean.sha(self.source / 'app.py')}))
        self.processes, self.devices = FakeProcesses(), FakeDevices()
        self.engine = clean.Uninstaller(self.home, self.source, self.processes, self.devices)
        self.support = self.engine.support
        self.support.mkdir(parents=True)
        for name in ('runtime/python', 'venv/bin', 'models', 'cache/pip', 'run', 'templates', 'bin'):
            (self.support / name).mkdir(parents=True)
        (self.support / 'models/qwen.bin').write_bytes(b'model weights')
        (self.support / 'venv/bin/python').write_text('private runtime')
        (self.support / 'bin/sawti-audio').write_text('fake helper')
        (self.support / 'sawti.sqlite3').write_bytes(b'legacy or damaged database')
        self.app = self.bundle('Sawti.app', 'com.imi.sawti')
        self.uninstaller = self.bundle('Uninstall Sawti.app', 'com.imi.sawti.uninstall')
        self.engine.register()

    def bundle(self, name, identity):
        app = self.home / 'Applications' / name
        (app / 'Contents').mkdir(parents=True)
        with open(app / 'Contents/Info.plist', 'wb') as stream:
            plistlib.dump({'CFBundleIdentifier': identity}, stream)
        return app

    def execute(self, components=('app', 'runtime', 'data')):
        return self.engine.execute(self.engine.plan(components), confirm_idle=True)

    def test_preview_is_non_destructive(self):
        plan = self.engine.plan(('app', 'runtime', 'data'))
        self.assertTrue(plan['remove'])
        self.assertTrue(self.app.exists())
        self.assertTrue((self.support / 'models/qwen.bin').exists())
        self.assertFalse((self.home / '.Trash').exists())

    def test_full_private_cleanup_moves_components_to_trash(self):
        backup = self.bundle('Sawti-backup-2026.app', 'com.imi.sawti')
        desktop = self.home / 'Desktop'
        desktop.mkdir()
        (desktop / 'Sawti.app').symlink_to(self.app)
        result = self.execute()
        self.assertFalse(self.app.exists())
        self.assertFalse(backup.exists())
        self.assertFalse(self.support.exists())
        self.assertFalse((desktop / 'Sawti.app').is_symlink())
        self.assertTrue(Path(result['trash']).is_dir())
        moved_model = next(item for item in result['moved'] if item['original'].endswith('/models'))
        self.assertEqual((Path(moved_model['trash']) / 'qwen.bin').read_bytes(), b'model weights')
        self.assertTrue(Path(result['report']).is_file())

    def test_recordings_and_sessions_inside_support_are_preserved(self):
        takes = self.support / 'models/Unexpected recordings'
        takes.mkdir()
        audio = takes / 'episode.bwf'
        audio.write_bytes(b'production audio')
        session = self.support / 'session.sesx'
        session.write_text('session')
        result = self.execute()
        self.assertEqual(audio.read_bytes(), b'production audio')
        self.assertEqual(session.read_text(), 'session')
        self.assertFalse((self.support / 'models/qwen.bin').exists())
        self.assertFalse(result['recordings_deleted'])

    def test_configured_recording_location_preserves_every_file(self):
        dbpath = self.support / 'sawti.sqlite3'
        dbpath.unlink()
        recording = self.support / 'runtime/Recordings'
        recording.mkdir()
        (recording / 'unusual-format.xyz').write_bytes(b'do not move')
        db = sqlite3.connect(dbpath)
        db.execute('create table settings(key text,value text)')
        db.execute('insert into settings values(?,?)', ('recording_root', json.dumps(str(recording))))
        db.commit()
        db.close()
        self.execute()
        self.assertEqual((recording / 'unusual-format.xyz').read_bytes(), b'do not move')

    def test_personal_data_can_be_kept_while_runtime_is_removed(self):
        template = self.support / 'templates/local_template.sesx'
        template.write_text('personal template')
        self.execute(('runtime', 'app'))
        self.assertTrue((self.support / 'sawti.sqlite3').exists())
        self.assertTrue(template.exists())
        self.assertFalse((self.support / 'models').exists())

    def test_selected_personal_templates_are_removed(self):
        (self.support / 'templates/local_template.sesx').write_text('personal template')
        self.execute()
        self.assertFalse((self.support / 'templates').exists())

    def test_unknown_files_and_empty_directories_survive(self):
        (self.support / 'valuable.txt').write_text('user file')
        empty = self.support / 'user-created-empty-folder'
        empty.mkdir()
        result = self.execute()
        self.assertEqual((self.support / 'valuable.txt').read_text(), 'user file')
        self.assertTrue(empty.is_dir())
        self.assertTrue(any('valuable.txt' in item['path'] for item in result['preserved']))

    def test_source_cleanup_keeps_edited_and_untracked_files(self):
        original = self.source / 'app.py'
        original.write_text('user edit')
        (self.source / 'added.py').write_text('new work')
        (self.source / 'recording.wav').write_bytes(b'private take')
        result = self.execute(('source',))
        self.assertEqual(original.read_text(), 'user edit')
        self.assertTrue((self.source / 'added.py').exists())
        self.assertTrue((self.source / 'recording.wav').exists())
        self.assertTrue(all(item['original'].endswith('install-source-manifest.json') for item in result['moved']))

    def test_unchanged_source_is_optional_and_removable(self):
        self.execute(('source',))
        self.assertFalse(self.source.exists())
        self.assertTrue(self.app.exists())

    def test_git_checkout_is_preserved(self):
        (self.source / '.git').mkdir()
        self.execute(('source',))
        self.assertTrue((self.source / 'app.py').exists())
        self.assertTrue((self.source / '.git').is_dir())

    def test_private_symlink_does_not_remove_external_target(self):
        external = self.home / 'external'
        external.mkdir()
        (external / 'keep.txt').write_text('external')
        (self.support / 'models/external').symlink_to(external, target_is_directory=True)
        self.execute()
        self.assertEqual((external / 'keep.txt').read_text(), 'external')

    def test_symlinked_support_parent_is_refused(self):
        application_support = self.support.parent
        elsewhere = self.home / 'elsewhere'
        application_support.rename(elsewhere)
        application_support.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.engine.plan(('runtime',))
        self.assertTrue((elsewhere / 'Sawti/models/qwen.bin').exists())

    def test_traversal_or_forged_removal_paths_cannot_escape_scope(self):
        with self.assertRaises(RuntimeError):
            self.engine.safe_path(self.home / '../foreign')
        victim = self.home / 'victim.txt'
        victim.write_text('preserve')
        preview = self.engine.plan(('app',))
        preview['remove'] = [str(victim)]
        self.engine.execute(preview, confirm_idle=True)
        self.assertTrue(victim.exists())

    def test_confirmation_and_component_validation_fail_closed(self):
        preview = self.engine.plan(('runtime',))
        with self.assertRaises(RuntimeError):
            self.engine.execute(preview)
        with self.assertRaises(ValueError):
            self.engine.plan(('everything_on_the_mac',))
        self.assertTrue((self.support / 'models/qwen.bin').exists())

    def test_unverified_running_process_blocks_all_file_removal(self):
        self.processes.active.add(123)
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertTrue(self.app.exists())
        self.assertEqual(self.processes.stopped, [])

    def test_verified_owned_process_is_stopped_before_files_move(self):
        pid = 123
        self.processes.active.add(pid)
        self.processes.verified.add(pid)
        clean.save_json(self.support / 'run/server.json', dict(pid=pid, source=str(self.source),
                        identity=dict(pid=pid, exe=str(self.support / 'runtime/python'), created=1, uid=os.getuid())))
        self.execute()
        self.assertEqual(self.processes.stopped, [pid])
        self.assertFalse(self.app.exists())

    def test_default_cleanup_never_touches_audio_devices(self):
        self.execute()
        self.assertEqual(self.devices.removed, [])

    def test_only_reviewed_unused_devices_can_be_removed(self):
        preview = self.engine.plan(('devices',))
        self.devices.rows.append(dict(self.devices.rows[0], uid=clean.DEVICE_UIDS[1]))
        self.engine.execute(preview, confirm_idle=True)
        self.assertEqual(self.devices.removed, [clean.DEVICE_UIDS[0]])

    def test_active_default_referenced_and_unknown_devices_are_kept(self):
        for changes in ({'running_somewhere': True}, {'default_output': True}, {'running_somewhere': None}):
            self.devices.rows[0].update(changes)
            plan = self.engine.plan(('devices',))
            self.assertEqual(plan['devices'], [])
            self.assertTrue(plan['retained_devices'])
            self.devices.rows[0].update(running_somewhere=False, default_output=False)
        self.devices.rows.append(dict(uid='foreign', subdevices=[clean.DEVICE_UIDS[0]]))
        self.assertFalse(self.engine.plan(('devices',))['devices'])

    def test_device_recheck_failure_retains_retry_tool(self):
        self.devices.fail = True
        result = self.execute(('app', 'runtime', 'data', 'devices'))
        self.assertTrue(result['errors'])
        self.assertTrue(self.uninstaller.exists())
        self.assertTrue((self.support / 'bin/sawti-audio').exists())
        self.assertTrue(self.engine.manifest_path.exists())
        self.assertFalse(self.app.exists())

    def test_foreign_app_and_desktop_item_are_kept(self):
        foreign = self.bundle('Sawti-backup-foreign.app', 'org.someone.other')
        desktop = self.home / 'Desktop'
        desktop.mkdir()
        (desktop / 'Sawti').write_text('not an alias owned by Sawti')
        self.execute()
        self.assertTrue(foreign.exists())
        self.assertTrue((desktop / 'Sawti').exists())

    def test_standalone_preview_works_with_site_packages_disabled(self):
        proc = subprocess.run([sys.executable, '-I', '-S', str(ROOT / 'helpers/uninstall.py'), 'preview',
                               '--home', str(self.home), '--source', str(self.source)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(json.loads(proc.stdout)['remove'])

    def test_real_identity_rejects_reused_pid_birth(self):
        identity = clean.native_identity(os.getpid())
        if identity is None:
            self.skipTest('Process inspection unavailable')
        record = dict(pid=os.getpid(), identity=identity)
        self.assertTrue(clean.Processes().identity_matches(record))
        record['identity'] = dict(identity, created=identity['created'] - 100)
        self.assertFalse(clean.Processes().identity_matches(record))

    def test_unreadable_container_is_not_treated_as_empty(self):
        original = Path.iterdir
        model_dir = self.support / 'models'
        def blocked(path):
            if path == model_dir:
                raise PermissionError('blocked')
            return original(path)
        with patch.object(Path, 'iterdir', blocked):
            plan = self.engine.plan(('runtime',))
        self.assertNotIn(str(model_dir), plan['remove'])
        self.assertTrue(any(item['path'] == str(model_dir) for item in plan['preserved']))

    def test_repeat_cleanup_is_harmless(self):
        self.execute()
        result = self.execute()
        self.assertEqual(result['moved'], [])

    def test_files_present_before_install_are_not_claimed(self):
        recording = self.source / 'recorded_before_install.wav'
        recording.write_bytes(b'production recording')
        (self.source / 'my_notes.txt').write_text('private')
        self.engine.register()
        self.execute(('source',))
        self.assertTrue(recording.exists())
        self.assertEqual((self.source / 'my_notes.txt').read_text(), 'private')

    def test_audio_is_not_claimed_even_if_in_a_source_manifest(self):
        recording = self.source / 'episode.wav'
        recording.write_bytes(b'production recording')
        clean.save_json(self.source / 'install-source-manifest.json',
                        dict(schema=1, files={'episode.wav': clean.sha(recording)}))
        self.engine.register()
        self.execute(('source',))
        self.assertTrue(recording.exists())

    def test_unknown_session_inside_template_folder_is_preserved(self):
        path = self.support / 'templates/actual_episode.sesx'
        path.write_text('production session')
        self.execute()
        self.assertEqual(path.read_text(), 'production session')

    def test_learning_report_is_optional_data_and_unknown_files_are_preserved(self):
        folder = self.support / 'learning_reports'
        folder.mkdir()
        report = folder / 'Sawti-Learnings.json'
        report.write_text('{"application":"Sawti"}')
        notes = folder / 'operator-notes.txt'
        notes.write_text('keep these notes')
        self.execute(('runtime',))
        self.assertTrue(report.exists())
        self.execute(('data',))
        self.assertFalse(report.exists())
        self.assertEqual(notes.read_text(), 'keep these notes')

    def test_corrupt_process_metadata_does_not_grant_kill_permission(self):
        clean.save_json(self.support / 'run/server.json', {'pid': 123, 'identity': ['corrupt']})
        self.assertEqual(self.engine.records(), [])
        self.assertFalse(clean.Processes().identity_matches({'pid': 123, 'identity': ['corrupt']}))

    def test_partial_file_failure_keeps_inventory_and_uninstaller_for_retry(self):
        original = os.rename
        def fail_model(src, dst, **kwargs):
            if src == 'models':
                raise PermissionError('test: models busy')
            return original(src, dst, **kwargs)
        with patch.object(os, 'rename', side_effect=fail_model):
            result = self.execute()
        self.assertTrue(result['errors'])
        self.assertTrue(self.uninstaller.exists())
        self.assertTrue(self.engine.manifest_path.exists())
        self.assertTrue((self.support / 'bin/sawti-audio').exists())
        retry = self.execute()
        self.assertFalse(retry['errors'])
        self.assertFalse(self.support.exists())


if __name__ == '__main__':
    unittest.main()
