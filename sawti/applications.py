"""Read installed macOS bundle metadata; do not launch or modify audio here."""
import glob
import plistlib
from pathlib import Path
import subprocess


def discover(kind):
    if kind not in ('focusrite', 'audition'):
        raise ValueError('Unknown studio application')
    pattern = 'Focusrite Control*.app' if kind == 'focusrite' else '*Audition*.app'
    candidates = []
    for root in (Path('/Applications'), Path.home() / 'Applications'):
        candidates += [str(p) for p in root.glob(pattern)]
        candidates += glob.glob(str(root / '*' / pattern))
    if not candidates:
        try:
            result = subprocess.run(['/usr/bin/mdfind', "kMDItemFSName == '%s'" % pattern],
                                    capture_output=True, text=True, timeout=5)
            candidates += result.stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            pass
    found = []
    for name in dict.fromkeys(candidates):
        path = Path(name)
        try:
            with (path / 'Contents/Info.plist').open('rb') as stream:
                info = plistlib.load(stream)
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        bid = info.get('CFBundleIdentifier', '')
        title = info.get('CFBundleDisplayName') or info.get('CFBundleName') or path.stem
        if not isinstance(bid, str) or not isinstance(title, str):
            continue
        if kind == 'focusrite':
            # Scarlett 18i8 3rd Gen uses the original Focusrite Control. Do not
            # silently substitute Control 2, which supports different hardware.
            if path.stem.replace(' ', '').lower() != 'focusritecontrol':
                continue
        elif not (bid.lower().startswith('com.adobe.') and 'audition' in bid.lower()):
            continue
        found.append(dict(path=str(path), bundle_id=bid, name=title,
                          version=info.get('CFBundleShortVersionString', 'unknown'),
                          build=info.get('CFBundleVersion', 'unknown')))
    found.sort(key=lambda a: a['path'], reverse=True)
    found.sort(key=lambda a: 'beta' in a['path'].lower())
    return found[0] if found else None
