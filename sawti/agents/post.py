"""Post-production agent: QC of recorded files, automatic multitrack mix, mastering to the house loudness
standard. Runs as background jobs; never overwrites the original recordings."""
import threading
import time
import uuid
import re
from pathlib import Path

from .. import dsp

AGENT = "Post"
_jobs = {}
_lock = threading.Lock()


def _job(kind, fn, *args):
    jid = uuid.uuid4().hex[:10]
    job = dict(id=jid, kind=kind, state="running", progress=0.0, started=time.time(), result=None, error=None)
    with _lock:
        _jobs[jid] = job

    def progress(p):
        job["progress"] = round(min(1.0, max(job["progress"], p)), 2)

    def run():
        try:
            job["result"] = fn(*args, progress=progress)
            job["state"] = "done"
            job["progress"] = 1.0
        except Exception as exc:  # report, do not crash the server
            job["state"], job["error"] = "failed", str(exc)
    threading.Thread(target=run, daemon=True).start()
    return job


def job(jid):
    return _jobs.get(jid)


def session_tracks(folder):
    """Recorded audio in a session folder (Sawti's own outputs excluded)."""
    folder = Path(folder)
    files = []
    for p in sorted(folder.rglob("*.wav")):
        n = p.name.lower()
        if n.endswith(("_master.wav", "_mix.wav")) or "talkback" in n:
            continue
        files.append(str(p))
    return files


def qc_files(paths_, progress=None):
    out = []
    for i, p in enumerate(paths_):
        m = dsp.measure_file(p)
        issues = []
        if m["clipped_samples"] > 10:
            issues.append(f"{m['clipped_samples']} clipped samples")
        if m["integrated_lufs"] < -60:
            issues.append("track is silent")
        elif m["integrated_lufs"] < -40:
            issues.append("very quiet track")
        if m["samplerate"] != 48000:
            issues.append(f"{m['samplerate']} Hz, expected 48000")
        m["issues"] = issues
        out.append(m)
        if progress:
            progress((i + 1) / len(paths_))
    return out


def master(studio, src, progress=None):
    src = Path(src).expanduser()
    if not src.is_file():
        raise ValueError("File not found.")
    if studio.live:
        raise RuntimeError('End the live show before post-production.')
    dst = _export_folder(src.parent) / (src.stem + "_master.wav")
    r = dsp.master_file(src, dst, studio.settings("loudness_target"), studio.settings("true_peak"), progress=progress)
    r["output"] = str(dst)
    studio.learn("mastered", lufs=r["after"]["integrated_lufs"], within=r["within_spec"])
    return r


def automix_and_master(studio, files, out_name, progress=None):
    files = [str(Path(f).expanduser()) for f in files]
    if not files:
        raise ValueError("No recorded tracks found.")
    if studio.live:
        raise RuntimeError('End the live show before post-production.')
    out_name = _export_name(out_name)
    folder = _export_folder(Path(files[0]).parent)
    mix = folder / f"{out_name}_mix.wav"
    dsp.automix(files, mix, progress=lambda p: progress and progress(0.4 * p))
    dst = folder / f"{out_name}_master.wav"
    r = dsp.master_file(mix, dst, studio.settings("loudness_target"), studio.settings("true_peak"),
                        progress=lambda p: progress and progress(0.4 + 0.6 * p))
    r.update(output=str(dst), mix=str(mix), tracks=files)
    studio.learn("mastered", lufs=r["after"]["integrated_lufs"], within=r["within_spec"], tracks=len(files))
    return r


def _export_name(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError('Enter an output name of 1–80 characters.')
    if name in ('.', '..') or re.search(r'[/\\\x00-\x1f]', name):
        raise ValueError('The output name must be a filename, not a path.')
    return name.strip()


def _export_folder(parent):
    # Each job owns a fresh directory. Concurrent/repeated exports cannot
    # overwrite original tracks, previous exports, or symlink destinations.
    folder = parent / ('Sawti-Export-' + uuid.uuid4().hex)
    folder.mkdir(exist_ok=False)
    return folder


def start_master(studio, src):
    studio.require_on()
    if studio.live:
        raise RuntimeError('End the live show before post-production.')
    return _job("master", lambda progress: master(studio, src, progress))


def start_automix(studio, files, out_name):
    studio.require_on()
    if studio.live:
        raise RuntimeError('End the live show before post-production.')
    _export_name(out_name)
    return _job("automix", lambda progress: automix_and_master(studio, files, out_name, progress))


def start_qc(files):
    return _job("qc", lambda progress: qc_files(files, progress))
