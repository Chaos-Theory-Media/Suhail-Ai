import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

import testkit as helpers

from sawti.lifecycle import Lifecycle

FAKE = """#!/bin/sh
echo $$ > "{pidfile}"
while true; do sleep 1; done
"""


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.bin = tempfile.mkdtemp()
        self.pidfile = os.path.join(self.bin, "child.pid")
        with open(os.path.join(self.bin, "ollama"), "w") as f:
            f.write(FAKE.format(pidfile=self.pidfile))
        os.chmod(os.path.join(self.bin, "ollama"), 0o755)
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"])

    def _child(self):
        for _ in range(50):
            if os.path.exists(self.pidfile):
                with open(self.pidfile) as f:
                    text = f.read().strip()
                if text:
                    return int(text)
            time.sleep(0.1)
        self.fail("fake ollama did not start")

    def test_stale_child_cleaned_on_next_start(self):
        old = os.environ["PATH"]
        os.environ["PATH"] = self.env["PATH"]
        try:
            lc = Lifecycle()
            lc.power_on()
            child = self._child()
            orphan, lc.ollama.proc = lc.ollama.proc, None  # simulate Sawti crashing without cleanup
            self.assertTrue(alive(child))
            self.assertTrue(Lifecycle().ollama.cleanup_stale())
            orphan.wait(5)  # reap (in real life the dead Sawti's child is reaped by macOS)
            self.assertFalse(alive(child))
        finally:
            os.environ["PATH"] = old

    def test_terminal_close_and_ctrl_c_stop_ai(self):
        """QA defect: closing Terminal (SIGHUP) or Ctrl+C (SIGINT) left the private Ollama running."""
        for sig in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
            if os.path.exists(self.pidfile):
                os.remove(self.pidfile)
            env = dict(self.env, SAWTI_PORT="8799", SAWTI_DATA=tempfile.mkdtemp())
            p = subprocess.Popen([sys.executable, os.path.join(helpers.ROOT, "app.py"), "--simulate"], env=env,
                                 cwd=helpers.ROOT, start_new_session=True, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            try:
                for _ in range(60):
                    try:
                        urllib.request.urlopen("http://127.0.0.1:8799/api/app", timeout=1)
                        break
                    except Exception:
                        time.sleep(0.2)
                req = urllib.request.Request("http://127.0.0.1:8799/api/power/on", data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json", "X-Sawti": "1"})
                urllib.request.urlopen(req, timeout=5)
                child = self._child()
                os.killpg(p.pid, sig)
                p.wait(10)
                time.sleep(0.5)
                self.assertFalse(alive(child), f"AI service survived {sig.name}")
            finally:
                if p.poll() is None:
                    p.kill()


if __name__ == "__main__":
    unittest.main()
