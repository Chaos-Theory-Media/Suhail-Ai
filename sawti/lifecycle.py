"""Processes Sawti owns: the private Ollama service and the keep-awake assertion.

Fixes from QA:
* Child processes are recorded in pid files and cleaned up on the next start if Sawti crashed.
* SIGINT / SIGTERM / SIGHUP and normal exit all stop Sawti-owned children (no orphaned Ollama).
* Status reports what is actually running, not what was attempted.
"""
import atexit
import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.request

from . import paths

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11439


def port_open(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _pid_alive(pid):
    try:
        import psutil
        return psutil.Process(pid).is_running() and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def _identity(pid):
    try:
        import psutil
        p = psutil.Process(pid)
        return dict(pid=pid, created=p.create_time(), command=p.cmdline(), uid=p.uids().real, exe=p.exe())
    except Exception:
        return None


def _cmdline(pid):
    try:
        import psutil
        return " ".join(psutil.Process(pid).cmdline())
    except Exception:
        return ""


class Managed:
    """A child process Sawti started, tracked with a pid file."""

    def __init__(self, name):
        self.name = name
        self.proc = None
        self.pidfile = paths.run_dir() / f"{name}.json"

    def cleanup_stale(self):
        """Stop a leftover child from a previous Sawti run (only if it is really ours)."""
        if not self.pidfile.exists():
            return False
        try:
            info = json.loads(self.pidfile.read_text())
        except Exception:
            info = {}
        pid = info.get("pid")
        killed = False
        # Old marker-only pidfiles are insufficient proof of ownership. PID reuse
        # must never terminate a foreign Ollama/caffeinate process.
        identity = _identity(pid) if isinstance(pid, int) and pid > 1 else None
        if (identity and info.get('identity') == identity and identity['uid'] == os.getuid()
                and os.getpgid(pid) == pid):
            try:
                os.killpg(pid, signal.SIGTERM)
                for _ in range(30):
                    if not _pid_alive(pid):
                        break
                    time.sleep(0.1)
                if _pid_alive(pid):
                    os.killpg(pid, signal.SIGKILL)
                killed = True
            except OSError:
                pass
        self.pidfile.unlink(missing_ok=True)
        return killed

    def start(self, argv, env=None, marker=None):
        self.stop()
        with open(paths.run_dir() / f"{self.name}.log", "ab") as log:
            self.proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=log, start_new_session=True)
        self.pidfile.write_text(json.dumps({"pid": self.proc.pid, "identity": _identity(self.proc.pid)}))
        self.pidfile.chmod(0o600)
        return self.proc

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        p, self.proc = self.proc, None
        if p is not None and p.poll() is None:
            # start_new_session gives this owned child its own process group.
            # Never send signals by executable name or an occupied port.
            group = False
            try:
                group = os.getpgid(p.pid) == p.pid
                if group:
                    os.killpg(p.pid, signal.SIGTERM)
                else:
                    p.terminate()
            except ProcessLookupError:
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if group:
                    os.killpg(p.pid, signal.SIGKILL)
                else:
                    p.kill()
                p.wait(timeout=3)
        self.pidfile.unlink(missing_ok=True)


class Lifecycle:
    def __init__(self, allow_ai=True):
        self.lock = threading.RLock()
        self.on = False
        self.ollama = Managed("ollama")
        self.awake = Managed("caffeinate")
        self.ollama_state = "stopped"   # stopped | starting | ready | failed | missing | external
        self.ollama_detail = ""
        self._installed = False
        self.allow_ai = allow_ai

    def install_handlers(self):
        """Make sure Sawti-owned children die with Sawti, whatever way it ends."""
        if self._installed:
            return
        self._installed = True
        self.ollama.cleanup_stale()
        self.awake.cleanup_stale()
        atexit.register(self.shutdown)

        def handler(signum, frame):
            self.shutdown()
            raise SystemExit(0)

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):  # not main thread (tests)
                pass

    # ------------------------------------------------------------ power
    def power_on(self):
        with self.lock:
            if self.on:
                return
            self.on = True
            self.start_ollama()

    def power_off(self):
        with self.lock:
            self.on = False
            try:
                self.ollama.stop()
            finally:
                self.ollama_state = "stopped"
                self.keep_awake(False)

    def shutdown(self):
        try:
            self.power_off()
        except Exception:
            pass

    # ------------------------------------------------------------ Ollama
    def start_ollama(self):
        if not self.allow_ai:
            self.ollama_state, self.ollama_detail = 'disabled', 'Simulation uses built-in agents; real AI services are untouched.'
            return
        binary = paths.ollama_binary()
        if not binary:
            self.ollama_state, self.ollama_detail = "missing", "Local AI not installed — Sawti works with its built-in agents."
            return
        if port_open(OLLAMA_PORT):
            self.ollama_state, self.ollama_detail = "failed", "Port 11439 is occupied by an unverified service. It was not contacted or stopped."
            return
        env = os.environ.copy()
        env["OLLAMA_HOST"] = f"{OLLAMA_HOST}:{OLLAMA_PORT}"
        env["OLLAMA_MODELS"] = str(paths.models_dir())
        env['OLLAMA_NO_CLOUD'] = '1'
        try:
            self.ollama.start([binary, "serve"], env=env, marker=binary)
        except OSError as exc:
            self.ollama_state, self.ollama_detail = "failed", f"Local AI could not start: {exc}"
            return
        self.ollama_state, self.ollama_detail = "starting", "Local AI is starting…"
        threading.Thread(target=self._wait_ollama, args=(self.ollama.proc,), daemon=True).start()

    def _wait_ollama(self, owned):
        for _ in range(60):
            with self.lock:
                if not self.on or self.ollama.proc is not owned:
                    return
                if not self.ollama.running():
                    self.ollama_state, self.ollama_detail = "failed", "Local AI stopped unexpectedly. See run/ollama.log."
                    return
            try:
                with urllib.request.urlopen(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags", timeout=1) as response:
                    names = [m.get('name') for m in json.load(response).get('models', [])]
                with self.lock:
                    if not self.on or self.ollama.proc is not owned or not self.ollama.running():
                        return
                    self.ollama_state = 'ready' if 'qwen3:4b' in names else 'missing'
                    self.ollama_detail = 'Local Qwen3 4B ready.' if self.ollama_state == 'ready' else 'Install the exact local qwen3:4b model.'
                return
            except Exception:
                time.sleep(0.5)
        with self.lock:
            if self.on and self.ollama.proc is owned:
                self.ollama_state, self.ollama_detail = "failed", "Local AI did not answer within 30 seconds."

    # ------------------------------------------------------------ keep the Mac awake during shows
    def keep_awake(self, enable=True):
        if enable:
            if not self.allow_ai:
                return False  # training mode never creates real background services
            if self.awake.running():
                return True
            if not os.path.exists("/usr/bin/caffeinate"):
                return False
            self.awake.start(["/usr/bin/caffeinate", "-dimsu", "-w", str(os.getpid())], marker="caffeinate")
            return True
        self.awake.stop()
        return False

    def snapshot(self):
        return dict(on=self.on, ollama=self.ollama_state, ollama_detail=self.ollama_detail,
                    keep_awake=self.awake.running())
