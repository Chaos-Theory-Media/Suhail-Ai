"""Optional offline speech: MLX Whisper on enhanced Macs, existing faster-whisper otherwise.
Tentative voluntary presenter recognition uses Resemblyzer.
Installed only if the operator chose voice features in the installer. Models load once and stay cached.
Speaker recognition is a convenience label, never authentication.
"""
import functools
import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import store, paths

THRESHOLD = 0.79   # provisional; calibrate on your presenters
MARGIN = 0.06


def available():
    from .models import installed
    enhanced = installed('speech')
    return dict(transcribe=(enhanced or importlib.util.find_spec("faster_whisper") is not None) and shutil.which("ffmpeg") is not None,
                backend='mlx-whisper-large-v3-turbo' if enhanced else 'faster-whisper-small',
                identify=importlib.util.find_spec("resemblyzer") is not None and shutil.which("ffmpeg") is not None)


def as_wav(audio):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Voice needs ffmpeg. Re-run the installer and choose voice features.")
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.audio", Path(d) / "out.wav"
        src.write_bytes(audio)
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar",
                            "16000", "-t", "61", "-c:a", "pcm_s16le", str(dst)], capture_output=True, timeout=40)
        if r.returncode != 0 or not dst.exists():
            raise ValueError("Could not read the recording from the browser. Try again.")
        if dst.stat().st_size > 60 * 16000 * 2 + 4096:
            raise ValueError('Voice samples must be at most 60 seconds.')
        return dst.read_bytes()


@functools.lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel
    private = paths.install_dir() / 'models/whisper'
    # Keep legacy local caches working without claiming ownership of them.
    download_root = str(private) if private.is_dir() else None
    return WhisperModel(os.environ.get("SAWTI_WHISPER", "small"), device="cpu", compute_type="int8",
                        local_files_only=True, download_root=download_root)


@functools.lru_cache(maxsize=1)
def _encoder():
    from resemblyzer import VoiceEncoder
    return VoiceEncoder()


def transcribe(audio, language=None, studio=None):
    if not available()["transcribe"]:
        raise RuntimeError("Voice commands are not installed on this Mac.")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(as_wav(audio))
        path = f.name
    try:
        from .models import installed
        if installed('speech'):
            if studio is None:
                raise RuntimeError('Enhanced speech requires Sawti service ownership.')
            return studio.local_models.run('transcribe', {'path': path,
                'language': language if language in ('en', 'ar') else None})['text']
        segs, _ = _whisper().transcribe(path, language=language if language in ("en", "ar") else None, vad_filter=True)
        return " ".join(s.text.strip() for s in segs).strip()
    finally:
        Path(path).unlink(missing_ok=True)


def embed(audio):
    from resemblyzer import preprocess_wav
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(as_wav(audio))
        path = f.name
    try:
        wav = preprocess_wav(Path(path))
        if len(wav) < 16000 * 4:
            raise ValueError("Record at least 5 seconds of clear speech.")
        return _encoder().embed_utterance(wav).tolist()
    finally:
        Path(path).unlink(missing_ok=True)


def enrol(person_id, audio):
    if not available()["identify"]:
        raise RuntimeError("Presenter recognition is not installed on this Mac.")
    store.set_embedding(person_id, embed(audio))


def identify(audio):
    if not available()["identify"]:
        return dict(name=None, confidence=None)
    v = np.array(embed(audio))
    scores = sorted(((float(np.dot(a, v) / (np.linalg.norm(a) * np.linalg.norm(v) + 1e-9)), n)
                     for n, a in ((n, np.array(e)) for n, e in store.embeddings())), reverse=True)
    if not scores or scores[0][0] < THRESHOLD or (len(scores) > 1 and scores[0][0] - scores[1][0] < MARGIN):
        return dict(name=None, confidence=round(scores[0][0], 3) if scores else None)
    return dict(name=scores[0][1], confidence=round(scores[0][0], 3))
