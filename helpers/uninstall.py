"""Standalone Sawti uninstall inventory and cleanup (Python standard library).

No Flask/audio/AI imports. Removal means moving reviewed items to this user's
Trash, never permanent erasure. Unknown files, recordings and shared tools stay.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import plistlib
import signal
import stat
import subprocess
import sys
import time
import uuid
import sqlite3

COMPONENTS = ('app', 'runtime', 'data', 'source', 'devices')
MEDIA = {'.wav', '.wave', '.bwf', '.w64', '.rf64', '.aif', '.aiff', '.flac', '.mp3', '.m4a', '.mp4', '.mov',
         '.caf', '.sesx', '.ses', '.sd2', '.raw', '.pcm', '.ogg', '.opus', '.aac', '.mxf'}
DEVICE_UIDS = ('com.imi.sawti.show-input', 'com.imi.sawti.zoom-speaker')
EXCLUDED = {'.git', '.venv', '__pycache__', 'node_modules', 'local_data', '.DS_Store'}


def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def sha(path):
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.replace(temporary, path)


def load_json(path):
    try:
        if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def native_identity(pid):
    """Precise birth identity even when Sawti's optional packages are broken."""
    if sys.platform == 'darwin':
        # Apple's xnu/bsd/sys/proc_info.h: struct proc_bsdinfo, PROC_PIDTBSDINFO=3.
        class BSDInfo(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint32) for n in (
                'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid', 'rgid', 'svuid', 'svgid', 'reserved')]
            _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
            _fields_ += [(n, ctypes.c_uint32) for n in ('nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
            _fields_ += [('nice', ctypes.c_int32), ('seconds', ctypes.c_uint64), ('microseconds', ctypes.c_uint64)]
        lib = ctypes.CDLL('/usr/lib/libproc.dylib')
        info = BSDInfo()
        if lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
            return None
        buffer = ctypes.create_string_buffer(4096)
        if lib.proc_pidpath(pid, buffer, len(buffer)) <= 0:
            return None
        return dict(pid=pid, created=info.seconds + info.microseconds / 1000000,
                    uid=info.ruid, exe=os.fsdecode(buffer.value))
    try:
        import psutil
        proc = psutil.Process(pid)
        return dict(pid=pid, created=proc.create_time(), uid=proc.uids().real, exe=proc.exe())
    except Exception:
        return None


class Processes:
    def identity_matches(self, record):
        expected = record.get('identity') or {}
        if not isinstance(expected, dict):
            return False
        pid = expected.get('pid', record.get('pid'))
        if (type(pid) is not int or pid <= 1 or not isinstance(expected.get('exe'), str)
                or not isinstance(expected.get('created'), (int, float))):
            return False
        current = native_identity(pid)
        return bool(current and current['uid'] == os.getuid() == expected.get('uid')
                    and abs(current['created'] - expected.get('created', -1)) < 0.0001
                    and current['exe'] == expected['exe'])

    def related(self, source, support):
        """Conservative detection only. A name/path match NEVER grants kill permission."""
        proc = subprocess.run(['/bin/ps', '-U', str(os.getuid()), '-o', 'pid=,command='], capture_output=True,
                              text=True, timeout=5, check=True)
        needles = (str(source / 'app.py'), str(support / 'runtime' / 'Ollama.app'))
        found = set()
        for line in proc.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if (len(parts) == 2 and not parts[1].startswith(('/bin/sh -c ', '/bin/bash -lc '))
                    and (any(n in parts[1] for n in needles)
                         or parts[1].startswith(str(support / 'venv/bin/python') + ' '))):
                pid = int(parts[0])
                if pid != os.getpid():
                    found.add(pid)
        return found

    def stop(self, record):
        if not self.identity_matches(record):
            raise RuntimeError('Process identity changed; no signal was sent.')
        pid = (record.get('identity') or {}).get('pid', record.get('pid'))
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if not self.identity_matches(record):
                return
            time.sleep(0.1)
        # Do not force-kill or signal a process group from an uninstall inventory.
        raise RuntimeError('Sawti did not exit. Close it in Activity Monitor and retry; no files were removed.')


class Devices:
    def __init__(self, helper, expected_hash):
        self.helper, self.expected_hash = helper, expected_hash

    def call(self, *args):
        if (not self.expected_hash or not self.helper.is_file() or self.helper.is_symlink()
                or sha(self.helper) != self.expected_hash):
            raise RuntimeError('Trusted audio helper unavailable; audio devices are retained.')
        result = subprocess.run([str(self.helper), *args], capture_output=True, text=True, timeout=20)
        value = json.loads(result.stdout.strip().splitlines()[-1])
        if result.returncode or value.get('ok') is not True:
            raise RuntimeError(value.get('error', 'Audio helper refused cleanup.'))
        return value

    def preview(self):
        return self.call('list')['devices']

    def remove(self, uid):
        if uid not in DEVICE_UIDS:
            raise RuntimeError('Not a Sawti virtual-device UID.')
        # The helper repeats activity/default/reference checks immediately before
        # destruction; a stale GUI preview cannot bypass the final guard.
        return self.call('destroy', '--uid', uid, '--if-unused')


class Uninstaller:
    def __init__(self, home, source, processes=None, devices=None):
        self.home = Path(home).absolute()
        self.source = Path(source).absolute()
        self.support = self.home / 'Library/Application Support/Sawti'
        self.manifest_path = self.support / 'installation.json'
        self.processes = processes or Processes()
        self.manifest = load_json(self.manifest_path)
        self.devices = devices or Devices(self.support / 'bin/sawti-audio', self.manifest.get('helper_sha256'))

    def safe_path(self, path):
        path = Path(path).absolute()
        if '..' in path.parts or not inside(path, self.home) or path == self.home:
            raise RuntimeError('Cleanup path must be below this user\'s home.')
        parent = path.parent
        while parent != self.home:
            if parent.is_symlink():
                raise RuntimeError('Symlinked parent directory is not safe to traverse: ' + str(parent))
            parent = parent.parent
        return path

    def register(self):
        self.safe_path(self.support)
        if self.support.is_symlink() or self.source.is_symlink():
            raise RuntimeError('Installation/source roots must not be symlinks.')
        # A directory scan would wrongly claim user files copied into the source
        # folder before installation. Only packaged, unchanged files are owned.
        packaged_path = self.source / 'install-source-manifest.json'
        packaged = load_json(packaged_path)
        if packaged.get('schema') != 1 or not isinstance(packaged.get('files'), dict):
            raise RuntimeError('Packaged source inventory is missing. Download the complete current ZIP.')
        files = {}
        for name, expected in packaged['files'].items():
            path = self.source / name
            if not inside(path, self.source) or '..' in Path(name).parts:
                raise RuntimeError('Invalid packaged source path.')
            if (set(Path(name).parts) & EXCLUDED or path.is_symlink()
                    or (path.suffix.lower() in MEDIA and name != 'tests/fixtures/podcast_template.sesx')):
                continue
            self.safe_path(path)
            if path.is_file() and sha(path) == expected:
                files[name] = expected
        files['install-source-manifest.json'] = sha(packaged_path)
        helper = self.support / 'bin/sawti-audio'
        value = dict(schema=1, source=str(self.source), source_files=files, installed=time.time(),
                     helper_sha256=sha(helper) if helper.is_file() and not helper.is_symlink() else None,
                     shared_components='BlackHole, FFmpeg, Homebrew and Apple Command Line Tools are shared; not owned.')
        save_json(self.manifest_path, value)
        self.manifest = value
        return value

    def recording_roots(self):
        roots = [self.home / 'Music/Sawti Recordings']
        for dbpath in (self.support / 'sawti.sqlite3', self.support / 'simulation/sawti.sqlite3'):
            if not dbpath.is_file() or dbpath.is_symlink():
                continue
            connection = None
            try:
                connection = sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True)
                for key, raw in connection.execute("SELECT key,value FROM settings WHERE key IN ('recording_root','state')"):
                    value = json.loads(raw)
                    path = value if key == 'recording_root' else (value.get('session') or {}).get('folder')
                    if isinstance(path, str) and Path(path).is_absolute():
                        roots.append(Path(path).resolve())
            except (sqlite3.Error, ValueError, AttributeError):
                # Media and unknown-file protection still applies to legacy or
                # damaged databases. Never load pickle or execute app settings.
                pass
            finally:
                if connection is not None:
                    connection.close()
        return roots

    def records(self):
        records = []
        for folder in (self.support / 'run', self.support / 'simulation/run'):
            if folder.is_symlink():
                continue
            for name in ('server.json', 'ollama.json', 'caffeinate.json', 'model-worker.json'):
                record = load_json(folder / name)
                ident = record.get('identity') or {}
                if not isinstance(ident, dict):
                    continue
                exe = ident.get('exe', '')
                command = ident.get('command') or []
                if not isinstance(exe, str) or not isinstance(command, list):
                    continue
                private = exe and inside(Path(exe), self.support)
                server = name == 'server.json' and record.get('source') == str(self.source)
                awake = name == 'caffeinate.json' and exe == '/usr/bin/caffeinate' and '-w' in command
                if record and (private or server or awake):
                    records.append(record)
        return records

    def stop_owned(self):
        records = [r for r in self.records() if self.processes.identity_matches(r)]
        # Stop the server first so its normal shutdown closes capture/services.
        records.sort(key=lambda r: 0 if r.get('source') else 1)
        related = self.processes.related(self.source, self.support)
        proven = {(r.get('identity') or {}).get('pid', r.get('pid')) for r in records}
        if related - proven:
            raise RuntimeError('Unverified Sawti-related process(es) still running: ' +
                               ', '.join(map(str, sorted(related - proven))) +
                               '. Close them in Activity Monitor; no files were removed.')
        for record in records:
            if self.processes.identity_matches(record):
                self.processes.stop(record)
        if self.processes.related(self.source, self.support):
            raise RuntimeError('A Sawti process is still running; no files were removed.')

    def bundle_owned(self, path):
        if path.is_symlink():
            return False
        try:
            with open(path / 'Contents/Info.plist', 'rb') as stream:
                return plistlib.load(stream).get('CFBundleIdentifier') in ('com.imi.sawti', 'com.imi.sawti.uninstall')
        except (OSError, ValueError, plistlib.InvalidFileException):
            return False

    def partition(self, path, roots, personal=False):
        """Split a known private container; never follow links or consume recordings."""
        if not path.exists() and not path.is_symlink():
            return [], []
        self.safe_path(path)
        if any(path == root or inside(path, root) for root in roots):
            return [], [dict(path=str(path), reason='recording location')]
        if path.suffix.lower() in MEDIA and not (personal and path.parent == self.support / 'templates'
                                               and path.name in ('local_template.sesx', 'zoom_template.sesx')):
            return [], [dict(path=str(path), reason='audio/session file')]
        if path.is_symlink() or not path.is_dir():
            return [path], []
        try:
            children = sorted(path.iterdir())
        except OSError:
            return [], [dict(path=str(path), reason='cannot completely inspect directory')]
        removable, kept = [], []
        for child in children:
            remove, preserve = self.partition(child, roots, personal)
            removable += remove
            kept += preserve
        return (removable, kept) if kept else ([path], [])

    def plan(self, components):
        if not set(components) <= set(COMPONENTS):
            raise ValueError('Unknown uninstall component.')
        self.safe_path(self.support)
        if self.support.is_symlink():
            raise RuntimeError('Sawti data root is a symlink; retain it for manual review.')
        candidates, kept = [], []
        roots = self.recording_roots()
        if 'app' in components:
            apps = self.home / 'Applications'
            for pattern in ('Sawti.app', 'Uninstall Sawti.app', 'Sawti-backup-*.app', 'Sawti-install-*.app'):
                for path in apps.glob(pattern):
                    if self.bundle_owned(path):
                        remove, preserve = self.partition(path, roots)
                        candidates += remove
                        kept += preserve
                    else:
                        kept.append(dict(path=str(path), reason='application ownership unverified'))
            for name in ('Sawti.app', 'Uninstall Sawti.app', 'Sawti'):
                path = self.home / 'Desktop' / name
                if path.is_symlink() and Path(os.readlink(path)) in (apps / 'Sawti.app', apps / 'Uninstall Sawti.app'):
                    candidates.append(path)
                elif path.exists():
                    kept.append(dict(path=str(path), reason='desktop item ownership unverified'))
        known = set()
        if 'runtime' in components:
            known.update(('runtime', 'models', 'venv', 'bin', 'cache', 'run', 'install.log', 'installation.json'))
        if 'data' in components:
            known.update(('sawti.sqlite3', 'sawti.sqlite3-wal', 'sawti.sqlite3-shm', 'sawti-before-v3.sqlite3',
                          'templates', 'simulation', 'learning_reports', 'knowledge'))
        for name in sorted(known):
            if name == 'learning_reports':
                folder = self.support / name
                if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
                    kept.append(dict(path=str(folder), reason='report folder ownership unverified'))
                    continue
                if folder.is_dir():
                    for child in folder.iterdir():
                        if child.name == 'Sawti-Learnings.json' and (child.is_file() or child.is_symlink()):
                            remove, preserve = self.partition(child, roots, personal=True)
                            candidates += remove
                            kept += preserve
                        else:
                            kept.append(dict(path=str(child), reason='unknown file in learning report folder'))
                continue
            remove, preserve = self.partition(self.support / name, roots, personal='data' in components)
            candidates += remove
            kept += preserve
        if self.support.exists():
            for child in self.support.iterdir():
                if child.name not in known:
                    kept.append(dict(path=str(child), reason='unselected data or unknown file'))
        if 'source' in components:
            self.safe_path(self.source)
            if self.source.is_symlink() or (self.source / '.git').exists():
                kept.append(dict(path=str(self.source), reason='source is a symlink or Git checkout; preserve local work'))
            elif self.manifest.get('source') != str(self.source):
                kept.append(dict(path=str(self.source), reason='source inventory unavailable; remove manually after review'))
            else:
                for name, expected in self.manifest.get('source_files', {}).items():
                    path = self.source / name
                    if not inside(path, self.source) or '..' in Path(name).parts:
                        raise RuntimeError('Invalid source inventory path.')
                    self.safe_path(path)
                    if path.is_file() and not path.is_symlink() and sha(path) == expected:
                        if not any(path == root or inside(path, root) for root in roots):
                            candidates.append(path)
                    elif path.exists() or path.is_symlink():
                        kept.append(dict(path=str(path), reason='source file changed; preserve local work'))
                inventory = self.manifest.get('source_files', {})
                for directory, dirs, files in os.walk(self.source, followlinks=False):
                    for name in list(dirs):
                        child = Path(directory) / name
                        if name in EXCLUDED or child.is_symlink():
                            kept.append(dict(path=str(child), reason='untracked source directory retained'))
                            dirs.remove(name)
                    for name in files:
                        child = Path(directory) / name
                        if str(child.relative_to(self.source)) not in inventory:
                            kept.append(dict(path=str(child), reason='untracked source file retained'))
        devices, device_errors = [], []
        if 'devices' in components:
            try:
                all_devices = self.devices.preview()
                for dev in all_devices:
                    if dev.get('uid') not in DEVICE_UIDS:
                        continue
                    referenced = any(dev['uid'] in d.get('subdevices', []) for d in all_devices if d is not dev)
                    if (dev.get('running_somewhere') is not False or referenced or
                            any(dev.get(k) is not False for k in ('default_input', 'default_output', 'default_system'))):
                        device_errors.append(dict(uid=dev['uid'], reason='active, default, referenced, or status unknown'))
                    else:
                        devices.append(dict(uid=dev['uid'], name=dev.get('name', dev['uid'])))
            except Exception as exc:
                device_errors.append(dict(reason=str(exc)))
        # UI previews show scope and paths, not credentials, command lines or database contents.
        return dict(schema=1, components=list(components), source=str(self.source),
                    remove=[str(p) for p in dict.fromkeys(candidates)], preserved=kept,
                    devices=devices, retained_devices=device_errors,
                    shared_retained=['BlackHole driver', 'FFmpeg', 'Homebrew', 'Apple Command Line Tools',
                                     'pre-existing Ollama', 'legacy shared voice-model caches', 'macOS privacy permissions'])

    def fingerprint(self, path):
        value = hashlib.sha256()
        def visit(p):
            s = p.lstat()
            value.update(repr((str(p), s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns)).encode())
            if stat.S_ISDIR(s.st_mode):
                for child in sorted(p.iterdir()):
                    visit(child)
        visit(path)
        return value.hexdigest()

    def execute(self, preview, confirm_idle=False):
        if confirm_idle is not True:
            raise RuntimeError('Explicit confirmation that all production recording is stopped is required.')
        if preview.get('schema') != 1 or preview.get('source') != str(self.source):
            raise RuntimeError('Invalid uninstall review.')
        components = preview.get('components', [])
        identifier = 'Sawti-Uninstall-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        report_path = self.home / 'Documents/Sawti Uninstall Reports' / (identifier + '.json')
        self.safe_path(report_path)
        # Establish a writable report before changing processes, files or devices.
        save_json(report_path, dict(state='started', components=components, moved=[]))
        # Reconstruct from a whitelist; never execute arbitrary paths supplied in a plan file.
        self.plan(components)
        self.stop_owned()
        current = self.plan(components)
        # Only reviewed devices may be removed, even if a different one becomes idle later.
        reviewed_uids = {d['uid'] for d in preview.get('devices', [])}
        removed_devices, errors = [], []
        for device in current['devices']:
            if device['uid'] in reviewed_uids:
                try:
                    self.devices.remove(device['uid'])
                    removed_devices.append(device['uid'])
                except Exception as exc:
                    errors.append(str(exc))
                    current['retained_devices'].append(dict(uid=device['uid'], reason=str(exc)))
        paths = [Path(p) for p in current['remove']]
        if 'devices' in components and (current['retained_devices'] or errors):
            retry = (self.support / 'bin', self.manifest_path, self.home / 'Applications/Uninstall Sawti.app')
            retained = [p for p in paths if any(p == r or inside(p, r) for r in retry)]
            paths = [p for p in paths if p not in retained]
            current['preserved'] += [dict(path=str(p), reason='retained for blocked audio-device cleanup retry') for p in retained]
        retry_controls = (self.support / 'bin', self.home / 'Applications/Uninstall Sawti.app', self.manifest_path)
        def priority(path):
            for i, control in enumerate(retry_controls):
                if path == control or inside(path, control):
                    return i + 1
            return 0
        paths.sort(key=priority)
        fingerprints = {str(p): self.fingerprint(p) for p in paths}
        trash = self.home / '.Trash'
        self.safe_path(trash)
        if trash.is_symlink():
            raise RuntimeError('Trash is a symlink; no files were moved.')
        trash.mkdir(exist_ok=True, mode=0o700)
        destination = trash / identifier
        destination.mkdir(mode=0o700)
        moved = []
        for i, path in enumerate(paths):
            try:
                if errors and priority(path):
                    current['preserved'].append(dict(path=str(path), reason='retained to retry incomplete cleanup'))
                    continue
                self.safe_path(path)
                if self.fingerprint(path) != fingerprints[str(path)]:
                    raise RuntimeError('File changed during uninstall; retained: ' + str(path))
                # Rename only, no cross-volume copy/delete fallback. Open the
                # parent without following a final symlink and verify identity.
                parent_stat = path.parent.stat()
                fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
                try:
                    opened = os.fstat(fd)
                    if (opened.st_dev, opened.st_ino) != (parent_stat.st_dev, parent_stat.st_ino):
                        raise RuntimeError('Parent directory changed; retained: ' + str(path))
                    target = destination / ('%04d-' % i + path.name)
                    os.rename(path.name, str(target), src_dir_fd=fd)
                finally:
                    os.close(fd)
                moved.append(dict(original=str(path), trash=str(target)))
                save_json(report_path, dict(state='in_progress', moved=moved, errors=errors))
            except (OSError, RuntimeError) as exc:
                errors.append(str(exc))
        # Remove only empty containers left by reviewed removals, never rmtree.
        parents = set()
        for item in moved:
            parent = Path(item['original']).parent
            for base in (self.support, self.source if 'source' in components else None):
                if base is not None and inside(parent, base):
                    while inside(parent, base):
                        parents.add(parent)
                        parent = parent.parent
                    break
        for parent in sorted(parents, key=lambda p: len(p.parts), reverse=True):
            try:
                parent.rmdir()
            except OSError:
                pass
        report = dict(moved=moved, trash=str(destination), preserved=current['preserved'], errors=errors,
                      removed_devices=removed_devices, retained_devices=current['retained_devices'],
                      shared_retained=current['shared_retained'], recordings_deleted=False,
                      note='Moved to Trash, not securely erased. Empty Trash after reviewing preserved files to reclaim space.')
        save_json(report_path, report)
        report['report'] = str(report_path)
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('register', 'preview', 'execute', 'stop'))
    parser.add_argument('--source', required=True)
    parser.add_argument('--home', default=str(Path.home()))
    parser.add_argument('--components', default='app,runtime,data')
    parser.add_argument('--plan')
    parser.add_argument('--confirm-idle', action='store_true')
    parser.add_argument('--gui', action='store_true', help='Return structured errors for the native dialog')
    args = parser.parse_args()
    engine = Uninstaller(args.home, args.source)
    if args.command == 'register':
        result = engine.register()
    elif args.command == 'stop':
        if not args.confirm_idle:
            raise RuntimeError('Confirm production recording is stopped before stopping Sawti.')
        engine.stop_owned()
        result = dict(stopped=True)
    elif args.command == 'preview':
        result = engine.plan(args.components.split(','))
        if args.plan:
            save_json(Path(args.plan), result)
    else:
        if not args.plan:
            parser.error('--plan is required')
        result = engine.execute(load_json(Path(args.plan)), args.confirm_idle)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps(dict(error=str(exc)), ensure_ascii=False))
        sys.exit(0 if '--gui' in sys.argv else 1)
