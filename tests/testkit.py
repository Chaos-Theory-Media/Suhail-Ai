"""Shared test setup: isolated data folder, simulation mode, synthetic speech."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SAWTI_DATA", tempfile.mkdtemp(prefix="sawti-test-"))
os.environ.setdefault("SAWTI_INSTALL", tempfile.mkdtemp(prefix="sawti-install-"))
os.environ["SAWTI_SIMULATE"] = "1"
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

FS = 48000


def speech(seconds, peak_db, channels=1, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * FS)) / FS
    env = (0.5 + 0.5 * np.sin(2 * np.pi * 3.7 * t)) ** 2 * (np.sin(2 * np.pi * 0.23 * t) > -0.3)
    x = rng.standard_normal((len(t), channels)) * env[:, None]
    b, a = signal.butter(2, [150, 4000], "bandpass", fs=FS)
    x = signal.lfilter(b, a, x, axis=0)
    return x / np.max(np.abs(x)) * 10 ** (peak_db / 20)


def client(studio):
    from sawti.server import create_app
    return create_app(studio).test_client()


BASE = "http://127.0.0.1:8765"
H = {"X-Sawti": "1"}
