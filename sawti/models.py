"""Local model policy and a cancellable, serial, private specialist worker.

No model downloads during normal use. No audio-device or transport operations.
The optional model venv is separate from the production monitoring venv.
"""
import json
import os
import platform
import shutil
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from . import paths

CHAT_MODEL = 'qwen3:30b-a3b-q4_K_M'
CHAT_MODELS = ('qwen3:4b', CHAT_MODEL)
REPOSITORIES = {
    'speech': 'mlx-community/whisper-large-v3-turbo',
    'embedding': 'BAAI/bge-m3',
    'reranker': 'BAAI/bge-reranker-v2-m3',
}


def compatibility(system=None, machine=None, version=None, memory=None, free=None, required_free_gb=60):
    """Conservative Sawti policy, not a benchmark or a vendor minimum."""
    import psutil
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    version = platform.mac_ver()[0] if version is None else version
    memory = psutil.virtual_memory().total if memory is None else memory
    free = shutil.disk_usage(paths.install_dir().parent).free if free is None else free
    try:
        major = int(version.split('.')[0])
    except (ValueError, AttributeError):
        major = 0
    reasons = []
    if system != 'Darwin' or machine != 'arm64':
        reasons.append('The enhanced stack requires native Apple Silicon macOS (not Rosetta).')
    if major < 14:
        reasons.append('macOS 14 or newer is required.')
    if memory < 64 * 1024**3:
        reasons.append('Sawti reserves this profile for Macs with at least 64 GB memory.')
    if free < required_free_gb * 1024**3:
        reasons.append(f'At least {required_free_gb} GB free is required before downloading these models.')
    return dict(eligible=not reasons, reasons=reasons, memory_gb=round(memory / 1024**3),
                free_gb=round(free / 1024**3), macos=version, machine=machine,
                hardware_qualified=False)


def profile():
    try:
        value = json.loads((paths.install_dir() / 'runtime/model-profile.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def specialist_path(role):
    if role not in REPOSITORIES:
        raise ValueError('Unknown specialist model.')
    return paths.install_dir() / 'models/specialists' / role


def installed(role):
    p = specialist_path(role)
    records = profile().get('specialists', {})
    metadata = records.get(role, {}) if isinstance(records, dict) else {}
    if not isinstance(metadata, dict):
        return False
    weights = ('weights.safetensors', 'weights.npz') if role == 'speech' else ('model.safetensors',)
    return (metadata.get('repository') == REPOSITORIES[role]
            and (p / 'config.json').is_file()
            and any((p / name).is_file() for name in weights)
            and (paths.install_dir() / 'runtime/models-venv/bin/python').is_file())


class LocalModels:
    def __init__(self, studio):
        self.studio = studio
        self.serial = threading.Lock()
        self.process_lock = threading.RLock()
        self.busy = False
        self.last_check = None

    def snapshot(self):
        return dict(chat_model=self.studio.settings('llm_model'), supported_chat_models=list(CHAT_MODELS),
                    specialists={role: dict(repository=repo, downloaded=installed(role))
                                 for role, repo in REPOSITORIES.items()}, busy=self.busy,
                    simulated=self.studio.audio.simulated, hardware_qualified=False,
                    offline=True, last_check=self.last_check)

    def stop(self):
        with self.process_lock:
            self.studio.lifecycle.model_worker.stop()

    @contextmanager
    def chat_slot(self):
        """Keep enhanced inference serial and prevent a show starting midway through a task."""
        if not self.serial.acquire(blocking=False):
            yield False
            return
        admitted = False
        try:
            with self.studio.lock:
                admitted = self.studio.lifecycle.on and not self.studio.live
                if admitted:
                    self.busy = True
            yield admitted
        finally:
            if admitted:
                self.busy = False
            self.serial.release()

    def run(self, operation, payload, timeout=90):
        if operation not in ('transcribe', 'retrieve', 'extract', 'selftest'):
            raise ValueError('Unknown model operation.')
        if self.studio.audio.simulated or platform.system() != 'Darwin' or platform.machine() != 'arm64':
            raise RuntimeError('Native model inference is disabled in simulation and on non-Apple-Silicon hosts.')
        roles = {'transcribe': ('speech',), 'retrieve': ('embedding', 'reranker'), 'extract': (),
                 'selftest': tuple(REPOSITORIES)}[operation]
        if not all(installed(role) for role in roles):
            raise RuntimeError('The required local models are not downloaded. Re-run the installer and select the enhanced model stack.')
        if not self.serial.acquire(blocking=False):
            raise RuntimeError('A local voice or document task is running. Please wait and try again.')
        self.busy = True
        if operation == 'selftest':
            self.last_check = None
        epoch = self.studio.power_epoch
        worker = self.studio.lifecycle.model_worker
        try:
            with tempfile.TemporaryDirectory(prefix='model-job-', dir=paths.sub('cache')) as folder, ExitStack() as cleanup:
                cleanup.callback(self.stop)  # Stop the writer before deleting private job files.
                root = Path(folder)
                request_file, result_file = root / 'request.json', root / 'result.json'
                request_file.write_text(json.dumps(dict(operation=operation, payload=payload,
                                                        models=str(paths.install_dir() / 'models/specialists'))))
                request_file.chmod(0o600)
                env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                           TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2',
                           HF_HOME=str(paths.install_dir() / 'cache/huggingface'))
                with self.studio.lock, self.process_lock:
                    if not self.studio.lifecycle.on or epoch != self.studio.power_epoch:
                        raise RuntimeError('Sawti was switched OFF; the task was cancelled.')
                    if self.studio.live:
                        raise RuntimeError('Enhanced model tasks are reserved for production-idle use until Mac performance is qualified.')
                    proc = worker.start([str(paths.install_dir() / 'runtime/models-venv/bin/python'),
                                         str(paths.APP_ROOT / 'helpers/model_worker.py'), str(request_file), str(result_file)], env=env)
                deadline = time.monotonic() + timeout
                while proc.poll() is None:
                    if (not self.studio.lifecycle.on or epoch != self.studio.power_epoch
                            or time.monotonic() >= deadline):
                        raise RuntimeError('Local model task cancelled or timed out; no studio settings were changed.')
                    time.sleep(0.05)
                if epoch != self.studio.power_epoch or not self.studio.lifecycle.on:
                    raise RuntimeError('Sawti was switched OFF; the result was discarded.')
                if proc.returncode or not result_file.is_file():
                    raise RuntimeError('The local model could not complete this task. Check model setup; existing audio is unaffected.')
                result = json.loads(result_file.read_text())
                if not result.get('ok'):
                    raise RuntimeError(result.get('error', 'Local model task failed.'))
                return result['result']
        finally:
            self.stop()
            self.busy = False
            self.serial.release()
