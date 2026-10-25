"""Audio measurement and processing to podcast standards.

* Loudness per ITU-R BS.1770-4 / EBU R128 (K-weighting, 400 ms blocks, absolute + relative gating).
* True peak by 4x oversampling (BS.1770 Annex 2 approach).
* Offline mastering: rumble high-pass, gain to target LUFS, look-ahead true-peak limiter.
* Offline auto-mix: per-speaker levelling + gain-sharing (Dugan-style) to suppress bleed.
* Live leveler: slow speech-gated gain rider + safety limiter (used only when inline mode is ON).

Everything streams in chunks so hour-long shows never load fully into memory.
"""
import math
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d, uniform_filter1d

NEG_INF = -120.0


def _distinct_output(src, dst):
    source, target = Path(src), Path(dst)
    if source.resolve() == target.resolve() or (target.exists() and source.samefile(target)):
        raise ValueError('Output must not replace a source recording.')


def db(x):
    return 20.0 * math.log10(max(float(x), 1e-6))


def lufs_from_power(p):
    return -0.691 + 10.0 * math.log10(p) if p > 0 else NEG_INF


# ---------------------------------------------------------------- K-weighting
def k_weighting_sos(fs):
    """Two biquads: high-shelf pre-filter (+4 dB @1.5 kHz) and RLB high-pass (38 Hz)."""
    def shelf():
        G, Q, fc = 4.0, 1 / math.sqrt(2), 1500.0
        A = 10 ** (G / 40)
        w0 = 2 * math.pi * fc / fs
        al = math.sin(w0) / (2 * Q)
        c = math.cos(w0)
        b = [A * ((A + 1) + (A - 1) * c + 2 * math.sqrt(A) * al),
             -2 * A * ((A - 1) + (A + 1) * c),
             A * ((A + 1) + (A - 1) * c - 2 * math.sqrt(A) * al)]
        a = [(A + 1) - (A - 1) * c + 2 * math.sqrt(A) * al,
             2 * ((A - 1) - (A + 1) * c),
             (A + 1) - (A - 1) * c - 2 * math.sqrt(A) * al]
        return b, a

    def highpass():
        Q, fc = 0.5, 38.0
        w0 = 2 * math.pi * fc / fs
        al = math.sin(w0) / (2 * Q)
        c = math.cos(w0)
        return [(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + al, -2 * c, 1 - al]

    rows = []
    for b, a in (shelf(), highpass()):
        rows.append([b[0] / a[0], b[1] / a[0], b[2] / a[0], 1.0, a[1] / a[0], a[2] / a[0]])
    return np.array(rows)


class KWeighter:
    """Stateful K-weighting filter for (frames, channels) blocks."""

    def __init__(self, fs, channels):
        self.sos = k_weighting_sos(fs)
        self.zi = np.zeros((self.sos.shape[0], 2, channels))

    def process(self, x):
        y, self.zi = signal.sosfilt(self.sos, x, axis=0, zi=self.zi)
        return y


class LoudnessAccumulator:
    """Integrated loudness (BS.1770-4) fed chunk by chunk. Channel weights 1.0 (L, R, mono)."""

    def __init__(self, fs, channels):
        self.kw = KWeighter(fs, channels)
        self.hop = int(round(0.1 * fs))
        self.carry = np.zeros((0, channels))
        self.sub = []  # summed-over-channels mean square for each 100 ms hop

    def add(self, x):
        y = np.concatenate([self.carry, self.kw.process(np.asarray(x, dtype=np.float64))])
        n = len(y) // self.hop
        if n:
            blocks = y[: n * self.hop].reshape(n, self.hop, -1)
            self.sub.extend((blocks ** 2).mean(axis=1).sum(axis=1).tolist())
            self.carry = y[n * self.hop:]
        else:
            self.carry = y

    def block_powers(self):
        s = np.asarray(self.sub)
        if len(s) < 4:
            return np.zeros(0)
        return (s[:-3] + s[1:-2] + s[2:-1] + s[3:]) / 4.0  # 400 ms blocks, 75 % overlap

    def integrated(self):
        z = self.block_powers()
        if not len(z):
            return NEG_INF
        lz = -0.691 + 10 * np.log10(np.maximum(z, 1e-20))
        g1 = lz > -70.0
        if not g1.any():
            return NEG_INF
        rel = -0.691 + 10 * math.log10(z[g1].mean()) - 10.0
        g2 = g1 & (lz > rel)
        return lufs_from_power(float(z[g2].mean())) if g2.any() else NEG_INF


def true_peak_db(x, carry=None):
    """dBTP of a block via 4x polyphase oversampling."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if not len(x):
        return NEG_INF
    up = signal.resample_poly(x, 4, 1, axis=0)
    return db(np.max(np.abs(up)))


# ---------------------------------------------------------------- file helpers
def _sf():
    import soundfile as sf
    return sf


def measure_file(path, block_seconds=30):
    """Loudness/peak QC of a file without loading it all."""
    sf = _sf()
    info = sf.info(str(path))
    acc = LoudnessAccumulator(info.samplerate, info.channels)
    tp, sp, clipped, frames = NEG_INF, 0.0, 0, 0
    pad = 64
    prev_tail = None
    for block in sf.blocks(str(path), blocksize=int(block_seconds * info.samplerate), dtype="float64",
                           always_2d=True):
        acc.add(block)
        ext = block if prev_tail is None else np.concatenate([prev_tail, block])
        tp = max(tp, true_peak_db(ext))
        sp = max(sp, float(np.max(np.abs(block))) if len(block) else 0.0)
        clipped += int(np.sum(np.abs(block) >= 0.999))
        frames += len(block)
        prev_tail = block[-pad:]
    z = acc.block_powers()
    silent = float(np.mean(z < 10 ** ((-60 + 0.691) / 10))) if len(z) else 1.0
    return dict(path=str(path), samplerate=info.samplerate, channels=info.channels,
                subtype=info.subtype, duration=round(frames / info.samplerate, 2),
                integrated_lufs=round(acc.integrated(), 2), true_peak_dbtp=round(tp, 2),
                sample_peak_dbfs=round(db(sp), 2), clipped_samples=clipped,
                silent_ratio=round(silent, 3))


# ---------------------------------------------------------------- limiter
def limiter_gain(x, fs, ceiling_db, lookahead_ms=5.0, release_ms=60.0):
    """Gain curve (frames,) that keeps the 4x-oversampled peak of x under ceiling. Zero-phase (offline)."""
    ceiling = 10 ** (ceiling_db / 20)
    up = np.abs(signal.resample_poly(x, 4, 1, axis=0))
    if up.ndim == 2:
        up = up.max(axis=1)
    n = len(x)
    env = up[: n * 4].reshape(n, 4).max(axis=1) if len(up) >= n * 4 else np.pad(up, (0, n * 4 - len(up))).reshape(n, 4).max(axis=1)
    g = np.minimum(1.0, ceiling / np.maximum(env, 1e-9))
    L = max(3, int(fs * lookahead_ms / 1000))
    R = max(3, int(fs * release_ms / 1000))
    g = uniform_filter1d(minimum_filter1d(g, size=2 * L + 1, mode="nearest"), size=L, mode="nearest")
    g = uniform_filter1d(minimum_filter1d(g, size=R, mode="nearest"), size=R, mode="nearest")
    return g


def _process_file(src, dst, fn, out_channels=None, block_seconds=20, margin_seconds=0.25):
    """Run fn(block, fs) over a file in overlapping chunks and write PCM-24 WAV."""
    sf = _sf()
    _distinct_output(src, dst)
    info = sf.info(str(src))
    fs = info.samplerate
    bs, m = int(block_seconds * fs), int(margin_seconds * fs)
    with sf.SoundFile(str(src)) as f_in:
        total = f_in.frames
        ch = out_channels or info.channels
        with sf.SoundFile(str(dst), "w", samplerate=fs, channels=ch, subtype="PCM_24", format="WAV") as f_out:
            start = 0
            while start < total:
                lo = max(0, start - m)
                hi = min(total, start + bs + m)
                f_in.seek(lo)
                chunk = f_in.read(hi - lo, dtype="float64", always_2d=True)
                y = fn(chunk, fs, lo)
                y = y[start - lo: start - lo + min(bs, total - start)]
                f_out.write(np.clip(y, -1.0, 1.0))
                start += bs
    return dst


def master_file(src, dst, target_lufs=-16.0, ceiling_dbtp=-1.0, progress=None):
    """High-pass 60 Hz, gain to target, true-peak limit. Mono input is output as dual-mono stereo."""
    sf = _sf()
    info = sf.info(str(src))
    before = measure_file(src)
    if before["integrated_lufs"] <= -69:
        raise ValueError("The file is silent; nothing to master.")
    hp = signal.butter(2, 60.0, "highpass", fs=info.samplerate, output="sos")
    stereo = info.channels == 1
    # Mono is measured 3 dB lower than the same signal played on two speakers.
    offset = 3.0103 if stereo else 0.0
    gain_db = target_lufs - (before["integrated_lufs"] + offset)
    ceiling = ceiling_dbtp - 0.3   # small safety margin for inter-sample overs from the gain curve
    result = None
    for attempt in range(3):
        def fn(chunk, fs, lo, g=10 ** (gain_db / 20)):
            y = signal.sosfiltfilt(hp, chunk, axis=0) if len(chunk) > 15 else chunk
            y = y * g
            if stereo:
                y = np.repeat(y, 2, axis=1)
            return y * limiter_gain(y, fs, ceiling)[:, None]

        _process_file(src, dst, fn, out_channels=2 if stereo else info.channels)
        result = measure_file(dst)
        if progress:
            progress(0.33 * (attempt + 1))
        err = target_lufs - result["integrated_lufs"]
        if abs(err) <= 0.3 and result["true_peak_dbtp"] <= ceiling_dbtp + 0.05:
            break
        gain_db += err
        if result["true_peak_dbtp"] > ceiling_dbtp:
            ceiling -= (result["true_peak_dbtp"] - ceiling_dbtp) + 0.1
    return dict(before=before, after=result, target_lufs=target_lufs, ceiling_dbtp=ceiling_dbtp,
                within_spec=abs(result["integrated_lufs"] - target_lufs) <= 0.5
                and result["true_peak_dbtp"] <= ceiling_dbtp + 0.05)


# ---------------------------------------------------------------- auto-mix
def _short_term_curve(path, hop_s=0.1):
    """Speech-gated per-100 ms K-weighted power for a (mono-summed) track."""
    sf = _sf()
    info = sf.info(str(path))
    acc = LoudnessAccumulator(info.samplerate, 1)
    for block in sf.blocks(str(path), blocksize=info.samplerate * 30, dtype="float64", always_2d=True):
        acc.add(block.mean(axis=1, keepdims=True) * math.sqrt(block.shape[1]))
    return np.asarray(acc.sub), info


def automix(tracks, dst, speech_target=-23.0, max_boost=20.0, max_cut=15.0, floor_db=-18.0, progress=None):
    """Level every speaker track, share gain between open mics, sum to a dual-mono mix (pre-master).

    tracks: list of file paths (one per microphone / remote guest feed).
    """
    sf = _sf()
    if not tracks:
        raise ValueError('Select at least one track.')
    for source in tracks:
        _distinct_output(source, dst)
    curves, infos = [], []
    for p in tracks:
        c, info = _short_term_curve(p)
        curves.append(c)
        infos.append(info)
    fs = infos[0].samplerate
    if any(i.samplerate != fs for i in infos):
        raise ValueError("All tracks must have the same sample rate.")
    n_hops = max(len(c) for c in curves)
    if n_hops == 0:
        raise ValueError('Tracks are too short for loudness analysis (minimum 100 ms).')
    P = np.zeros((len(tracks), n_hops))
    for i, c in enumerate(curves):
        P[i, : len(c)] = c
    # 3 s short-term power (centred) per track
    st = uniform_filter1d(P, size=30, axis=1, mode="nearest")
    st_l = -0.691 + 10 * np.log10(np.maximum(st, 1e-20))
    # 1) who is talking: the mic with the loudest raw short-term level owns that moment.
    #    Bleed of the same voice into other mics is quieter there, so it never "owns" the moment.
    mom_raw = uniform_filter1d(P, size=4, axis=1, mode="nearest")
    mom_l = -0.691 + 10 * np.log10(np.maximum(mom_raw, 1e-20))
    dominant = (mom_l >= mom_l.max(axis=0, keepdims=True) - 6.0) & (mom_l > -55)
    # 2) static normalisation from each mic's own speech (90th percentile while it owns the moment)
    static = np.zeros(len(tracks))
    for i in range(len(tracks)):
        own = st_l[i][dominant[i] & (st_l[i] > -55)]
        if len(own) >= 10:
            static[i] = np.clip(speech_target - np.percentile(own, 90), -max_cut, max_boost)
    gains_db = np.zeros_like(st_l)
    for i in range(len(tracks)):
        g, out = float(static[i]), []
        for v, own in zip(st_l[i], dominant[i]):
            if own and v > -55:  # ride slowly toward target only on the talker's own speech
                want = float(np.clip(speech_target - v, -max_cut, max_boost))
                g += float(np.clip(want - g, -0.6, 0.3))  # dB per 100 ms: faster down than up
            out.append(g)
        gains_db[i] = out
    # 3) gain sharing on momentary (400 ms) power, smoothed: the person talking stays open
    mom = uniform_filter1d(P * (10 ** (gains_db / 10)), size=4, axis=1, mode="nearest") + 1e-12
    share = mom / mom.sum(axis=0, keepdims=True)
    share_db = np.maximum(10 * np.log10(share), floor_db)
    # mics that are only carrying someone else's voice (bleed) are closed down to the floor
    share_db = np.where(dominant, share_db, floor_db)
    share_db = uniform_filter1d(share_db, size=4, axis=1, mode="nearest")
    total_db = gains_db + share_db
    hop = int(round(0.1 * fs))
    files = [sf.SoundFile(str(p)) for p in tracks]
    try:
        total = max(f.frames for f in files)
        with sf.SoundFile(str(dst), "w", samplerate=fs, channels=2, subtype="FLOAT", format="WAV") as out:
            bs = fs * 20
            pos = 0
            while pos < total:
                n = min(bs, total - pos)
                mix = np.zeros(n)
                t = (pos + np.arange(n)) / hop
                for i, f in enumerate(files):
                    blk = f.read(n, dtype="float64", always_2d=True)
                    mono = blk.mean(axis=1) if len(blk) else np.zeros(0)
                    if len(mono) < n:
                        mono = np.pad(mono, (0, n - len(mono)))
                    g = np.interp(t, np.arange(n_hops) + 0.5, total_db[i])
                    mix += mono * 10 ** (g / 20)
                out.write(np.repeat(mix[:, None], 2, axis=1))
                pos += n
                if progress:
                    progress(pos / total)
    finally:
        for f in files:
            f.close()
    return dict(tracks=len(tracks), duration=round(total / fs, 2))


# ---------------------------------------------------------------- live leveler
class Leveler:
    """Live speech-gated gain rider with safety limiter. Block-based, no look-ahead (≈ 0 latency)."""

    def __init__(self, fs, channels, target=-20.0, max_boost=12.0, max_cut=12.0,
                 up_db_per_s=3.0, down_db_per_s=8.0, gate=-55.0, ceiling_db=-1.0):
        self.fs, self.target, self.gate = fs, target, gate
        self.max_boost, self.max_cut = max_boost, max_cut
        self.up, self.down = up_db_per_s, down_db_per_s
        self.ceiling = 10 ** (ceiling_db / 20)
        self.kw = KWeighter(fs, channels)
        self.ms = np.full(channels, 1e-10)
        self.gain_db = np.zeros(channels)

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        n = len(x)
        dt = n / self.fs
        k = self.kw.process(x)
        alpha = min(1.0, dt / 0.4)  # ~400 ms momentary
        self.ms = (1 - alpha) * self.ms + alpha * (k ** 2).mean(axis=0)
        lufs = -0.691 + 10 * np.log10(np.maximum(self.ms, 1e-20))
        old = self.gain_db.copy()
        want = np.clip(self.target - lufs, -self.max_cut, self.max_boost)
        delta = np.clip(want - old, -self.down * dt, self.up * dt)
        new = np.where(lufs > self.gate, old + delta, old)
        ramp = np.linspace(0, 1, n, endpoint=False)[:, None]
        g = 10 ** ((old + (new - old) * ramp) / 20)
        y = x * g
        peak = np.max(np.abs(y), axis=0)
        over = peak > self.ceiling
        if over.any():
            cut = np.where(over, self.ceiling / np.maximum(peak, 1e-9), 1.0)
            y = y * cut
            new = new + np.where(over, 20 * np.log10(cut), 0.0)
        self.gain_db = new
        return y
