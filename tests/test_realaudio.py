"""The real-Mac code path (RealAudio + PortAudio stream) with a fake helper binary and a fake sounddevice."""
import json
import os
import stat
import sys
import tempfile
import threading
import time
import types
import unittest

import testkit as helpers  # noqa: F401
import numpy as np

from sawti import paths
from sawti.coreaudio import RealAudio, input_layout

DEVICES = [
    dict(id=50, uid="SCARLETT", name="Scarlett 18i8 USB", manufacturer="Focusrite", transport="usb", inputs=18,
         outputs=8, rate=48000.0, rates=[44100.0, 48000.0], subdevices=[]),
    dict(id=60, uid="BH2", name="BlackHole 2ch", manufacturer="Existential", transport="virtual", inputs=2,
         outputs=2, rate=48000.0, rates=[48000.0], subdevices=[]),
    dict(id=70, uid="com.imi.sawti.show-input", name="Sawti Show Input", manufacturer="Apple", transport="aggregate",
         inputs=20, outputs=10, rate=48000.0, rates=[48000.0], subdevices=["SCARLETT", "BH2"]),
]


class FakeStream:
    def __init__(self, device, channels, samplerate, blocksize, dtype, callback):
        self.cb, self.ch, self.run = callback, channels, False

    def start(self):
        self.run = True

        def go():
            while self.run:
                x = np.zeros((1024, self.ch), dtype=np.float32)
                x[:, 0] = 0.1 * np.sin(np.arange(1024) / 5)
                self.cb(x, 1024, None, None)
                time.sleep(0.02)
        threading.Thread(target=go, daemon=True).start()

    def stop(self):
        self.run = False

    def close(self):
        pass


class RealAudioTests(unittest.TestCase):
    def setUp(self):
        self.old_install = os.environ.get("SAWTI_INSTALL")
        os.environ["SAWTI_INSTALL"] = tempfile.mkdtemp()
        helper = paths.helper_path()
        helper.parent.mkdir(parents=True, exist_ok=True)
        log = os.path.join(os.environ["SAWTI_INSTALL"], "calls.log")
        helper.write_text("#!%s\nimport sys, json\nopen(%r,'a').write(' '.join(sys.argv[1:])+'\\n')\n"
                          "print(json.dumps({'ok': True, 'devices': %s}) if sys.argv[1]=='list' else json.dumps({'ok': True}))\n"
                          % (sys.executable, log, json.dumps(DEVICES).replace("true", "True").replace("false", "False")))
        helper.chmod(helper.stat().st_mode | stat.S_IEXEC)
        self.log = log
        fake = types.ModuleType("sounddevice")
        fake.query_devices = lambda: [dict(name=d["name"], max_input_channels=d["inputs"],
                                           max_output_channels=d["outputs"], default_samplerate=d["rate"]) for d in DEVICES]
        fake._terminate = fake._initialize = lambda: None
        fake.InputStream = FakeStream
        sys.modules["sounddevice"] = fake

    def tearDown(self):
        sys.modules.pop("sounddevice", None)
        if self.old_install is None:
            os.environ.pop("SAWTI_INSTALL", None)
        else:
            os.environ["SAWTI_INSTALL"] = self.old_install

    def test_devices_merge_and_layout(self):
        ra = RealAudio()
        devs = ra.devices()
        self.assertEqual([d["index"] for d in devs], [0, 1, 2])
        agg = devs[2]
        self.assertEqual(input_layout(agg, devs), {"scarlett": 0, "blackhole": 18})

    def test_helper_commands(self):
        ra = RealAudio()
        ra.create_aggregate("Sawti Show Input", "com.imi.sawti.show-input", "SCARLETT", ["SCARLETT", "BH2"])
        ra.set_rate("SCARLETT", 48000)
        calls = open(self.log).read()
        self.assertIn("create --name Sawti Show Input --uid com.imi.sawti.show-input --main SCARLETT --sub SCARLETT --sub BH2", calls)
        self.assertIn("set-rate --uid SCARLETT --rate 48000", calls)

    def test_real_meter_stream_zoom(self):
        os.environ.pop("SAWTI_SIMULATE", None)
        try:
            from sawti.studio import Studio
            st = Studio(audio=RealAudio())
            st.mode = "zoom"
            self.assertTrue(st.start_meter(), st.monitor.error)
            time.sleep(0.6)
            snap = st.monitor.snapshot()
            self.assertEqual(snap["device"], "Sawti Show Input")
            mic1 = next(s for s in snap["sources"] if s["id"] == "mic1")
            guests = next(s for s in snap["sources"] if s["id"] == "guests")
            self.assertGreater(mic1["peak"], -30)
            self.assertEqual(guests["chans"], [19, 20])
            st.stop_meter()
            self.assertFalse(st.audio.stream_open)
        finally:
            os.environ["SAWTI_SIMULATE"] = "1"


if __name__ == "__main__":
    unittest.main()
