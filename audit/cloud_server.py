"""Linux cloud inspection harness, not a macOS production launcher.

Uses isolated application data, starts OFF, and never invokes the Mac installer.
"""
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA_HOME = Path('/workspace/.sawti-cloud/data-home')
with patch('pathlib.Path.home', return_value=DATA_HOME):
    import app

if __name__ == '__main__':
    app.app.run(host='127.0.0.1', port=8765, debug=False, threaded=True)
