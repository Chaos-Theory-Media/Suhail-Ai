"""Explicit, bounded, read-only discovery of saved Audition sessions.

Audition's unsaved windows are not a filesystem catalogue. A .sesx extension
does not prove a file is an empty reusable template. Never launch Audition here.
"""
import os
import time
import uuid
from pathlib import Path

from . import paths


def context(studio):
    return (studio.power_epoch, studio.mode, (studio.mic_plan or {}).get('id'))


def default_roots(studio):
    if studio.audio.simulated:
        return [paths.data_dir() / 'templates', paths.data_dir() / 'AuditionTemplates']
    home = Path.home()
    return [home / 'Library/Preferences/Adobe/Audition',
            home / 'Library/Application Support/Adobe/Audition', paths.data_dir() / 'templates',
            home / 'Documents', home / 'Music', Path(studio.settings('recording_root')).expanduser()]


def scan(roots, *, max_entries=5000, max_files=150, max_depth=7, seconds=4, cancelled=lambda: False):
    rows, warnings, visited, seen_files = [], [], set(), set()
    entries, limited = 0, False
    deadline = time.monotonic() + seconds
    stack = [(Path(root), 0) for root in reversed(roots)]
    while stack:
        if cancelled():
            raise RuntimeError('Studio state changed; the template search was cancelled.')
        if entries >= max_entries or len(rows) >= max_files or time.monotonic() >= deadline:
            limited = True
            break
        folder, depth = stack.pop()
        try:
            if folder.is_symlink():
                warnings.append('Skipped linked folder: ' + str(folder))
                continue
            if not folder.exists():
                continue
            canonical = str(folder.resolve())
            if canonical in visited:
                continue
            visited.add(canonical)
            with os.scandir(folder) as children:
                for child in children:
                    if cancelled():
                        raise RuntimeError('Studio state changed; the template search was cancelled.')
                    entries += 1
                    if entries > max_entries or len(rows) >= max_files or time.monotonic() >= deadline:
                        limited = True
                        break
                    if child.name.startswith('.') or child.is_symlink():
                        continue
                    if child.is_dir(follow_symlinks=False):
                        if depth < max_depth:
                            stack.append((Path(child.path), depth + 1))
                        else:
                            limited = True
                    elif child.name.lower().endswith('.sesx') and child.is_file(follow_symlinks=False):
                        path = str(Path(child.path).resolve())
                        if path not in seen_files:
                            seen_files.add(path)
                            rows.append(dict(path=path, name=child.name, folder=str(Path(path).parent)))
        except OSError:
            warnings.append('Could not read folder (permission or availability): ' + str(folder))
    return dict(files=sorted(rows, key=lambda r: (r['name'].casefold(), r['path'])),
                warnings=warnings[:20], limited=limited, entries_checked=entries)


class TemplateCatalog:
    def __init__(self, studio):
        self.studio = studio
        self.generation = 0
        self.bound_context = None
        self.choices = {}

    def search(self, folder=None):
        studio = self.studio
        if folder is not None and (not isinstance(folder, str) or len(folder) > 4096):
            raise ValueError('Choose a specific folder path.')
        chosen = None
        if folder and folder.strip():
            chosen = Path(folder.strip()).expanduser()
            if chosen.is_absolute() and not chosen.is_symlink():
                chosen = chosen.resolve()
            if not chosen.is_absolute() or chosen == Path(chosen.anchor) or chosen == Path.home():
                raise ValueError('Choose a specific folder, not an entire drive or home folder.')
            if not chosen.is_dir() or chosen.is_symlink():
                raise ValueError('That folder is unavailable or is a link. Choose its actual location.')
        with studio.lock:
            studio.require_on()
            self.generation += 1
            generation, current = self.generation, context(studio)
            self.choices = {}
            self.bound_context = None
            roots = default_roots(studio)
            if chosen is not None:
                roots = [chosen]
        def cancelled():
            return not studio.lifecycle.on or current != context(studio) or generation != self.generation
        result = scan(roots, cancelled=cancelled)
        with studio.lock:
            if cancelled():
                raise RuntimeError('Studio state changed; search again for the current microphone plan.')
            self.bound_context = current
            self.choices = {}
            for row in result['files']:
                row['id'] = uuid.uuid4().hex
                self.choices[row['id']] = row['path']
            result['searched_folders'] = list(map(str, roots))
            return result

    def resolve(self, choice):
        with self.studio.lock:
            self.studio.require_on()
            if self.bound_context != context(self.studio):
                raise RuntimeError('Power, mode or microphones changed. Find saved sessions again.')
            if not isinstance(choice, str) or choice not in self.choices:
                raise ValueError('Choose a file from the latest saved-session search.')
            return self.choices[choice]
