"""Run original or audit tests with isolated temporary application data.

No audio devices or external services are started by this runner.
"""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('suite', choices=('original', 'audit'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='sawti-checks-') as folder:
        # sawti.py creates a macOS user-data directory during import. Isolate it
        # without changing the user's HOME or modifying application source.
        with patch('pathlib.Path.home', return_value=Path(folder)):
            import sawti
        directory = ROOT / ('tests' if args.suite == 'original' else 'audit/checks')
        suite = unittest.defaultTestLoader.discover(str(directory))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
