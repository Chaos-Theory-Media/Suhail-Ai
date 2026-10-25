"""Build the uninstall source inventory from Git membership, never a folder scan.

Developer use after staging new files: python helpers/build_source_manifest.py
CI verifies the committed inventory with --check. ZIP users do not run this.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'install-source-manifest.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    top = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT, text=True).strip()
    if Path(top).resolve() != ROOT:
        raise RuntimeError('Run this in the real Sawti Git checkout.')
    names = subprocess.check_output(['git', 'ls-files', '--cached', '-z'], cwd=ROOT).decode().split('\0')
    files = {}
    for name in sorted(filter(None, names)):
        path = ROOT / name
        if path == TARGET or path.is_symlink():
            continue
        if not path.is_file():
            raise RuntimeError('Tracked source is missing: ' + name)
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    version = re.search(r'VERSION = "([^"]+)"', (ROOT / 'sawti/__init__.py').read_text()).group(1)
    text = json.dumps(dict(schema=1, application_version=version, files=files), indent=2, sort_keys=True) + '\n'
    if args.check:
        if not TARGET.is_file() or TARGET.read_text() != text:
            raise RuntimeError('Source inventory is stale; stage files and rebuild it before packaging.')
        print('Packaged source inventory verified: %d files.' % len(files))
    else:
        TARGET.write_text(text)
        print('Packaged source inventory generated: %d files.' % len(files))


if __name__ == '__main__':
    main()
