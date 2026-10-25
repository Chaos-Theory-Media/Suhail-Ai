import os
import tempfile
import unittest

import testkit as helpers  # noqa: F401
import numpy as np
import soundfile as sf

from sawti import dsp

FS = helpers.FS


class LoudnessTests(unittest.TestCase):
    def test_ebu_reference_sine(self):
        # EBU Tech 3341: 1 kHz stereo sine at -23 dBFS (per channel) reads -23.0 LUFS
        t = np.arange(FS * 20) / FS
        x = np.sin(2 * np.pi * 1000 * t) * 10 ** (-23 / 20)
        acc = dsp.LoudnessAccumulator(FS, 2)
        acc.add(np.stack([x, x], axis=1))
        self.assertAlmostEqual(acc.integrated(), -23.0, delta=0.1)

    def test_chunked_equals_whole(self):
        x = helpers.speech(30, -12, 2)
        a = dsp.LoudnessAccumulator(FS, 2)
        a.add(x)
        b = dsp.LoudnessAccumulator(FS, 2)
        for i in range(0, len(x), 5001):
            b.add(x[i:i + 5001])
        self.assertAlmostEqual(a.integrated(), b.integrated(), places=6)

    def test_silence_is_gated(self):
        acc = dsp.LoudnessAccumulator(FS, 1)
        acc.add(np.zeros((FS * 5, 1)))
        self.assertEqual(acc.integrated(), dsp.NEG_INF)


class MasteringTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_master_hits_podcast_standard(self):
        src = os.path.join(self.d, "raw.wav")
        sf.write(src, helpers.speech(90, -2, 1), FS, subtype="PCM_24")
        r = dsp.master_file(src, os.path.join(self.d, "m.wav"), -16.0, -1.0)
        self.assertTrue(r["within_spec"], r)
        self.assertAlmostEqual(r["after"]["integrated_lufs"], -16.0, delta=0.5)
        self.assertLessEqual(r["after"]["true_peak_dbtp"], -0.95)
        self.assertEqual(r["after"]["channels"], 2)  # mono delivered as dual-mono stereo

    def test_master_quiet_file_is_limited_not_clipped(self):
        src = os.path.join(self.d, "quiet.wav")
        sf.write(src, helpers.speech(60, -30, 2), FS, subtype="PCM_24")
        r = dsp.master_file(src, os.path.join(self.d, "q.wav"), -16.0, -1.0)
        self.assertLessEqual(r["after"]["true_peak_dbtp"], -0.95)
        self.assertEqual(r["after"]["clipped_samples"], 0)

    def test_silent_file_rejected(self):
        src = os.path.join(self.d, "silent.wav")
        sf.write(src, np.zeros((FS * 5, 1)), FS)
        with self.assertRaises(ValueError):
            dsp.master_file(src, os.path.join(self.d, "s.wav"))

    def test_automix_balances_unequal_mics_with_bleed(self):
        a = helpers.speech(60, -6, 1, seed=2)[:, 0]
        b = helpers.speech(60, -24, 1, seed=3)[:, 0]
        a[: FS * 30] *= 0.05
        b[FS * 30:] *= 0.05
        p1, p2 = os.path.join(self.d, "m1.wav"), os.path.join(self.d, "m2.wav")
        sf.write(p1, a + 0.1 * b, FS, subtype="PCM_24")
        sf.write(p2, b + 0.1 * a, FS, subtype="PCM_24")
        out = os.path.join(self.d, "mix.wav")
        dsp.automix([p1, p2], out)
        y, _ = sf.read(out)
        first = dsp.LoudnessAccumulator(FS, 2)
        first.add(y[FS * 5: FS * 30])
        second = dsp.LoudnessAccumulator(FS, 2)
        second.add(y[FS * 35:])
        self.assertLess(abs(first.integrated() - second.integrated()), 3.0)  # was 18 dB apart in the raw tracks


class LevelerTests(unittest.TestCase):
    def test_leveler_raises_quiet_speech_and_never_overshoots(self):
        lv = dsp.Leveler(FS, 1)
        x = helpers.speech(30, -24, 1)
        y = np.concatenate([lv.process(x[i:i + 1024]) for i in range(0, len(x), 1024)])
        a, b = dsp.LoudnessAccumulator(FS, 1), dsp.LoudnessAccumulator(FS, 1)
        a.add(x[-FS * 10:])
        b.add(y[-FS * 10:])
        self.assertGreater(b.integrated() - a.integrated(), 8)
        self.assertLessEqual(np.max(np.abs(y)), 10 ** (-1 / 20) + 1e-6)

    def test_leveler_tames_hot_speech(self):
        lv = dsp.Leveler(FS, 1)
        x = helpers.speech(30, -0.5, 1)
        y = np.concatenate([lv.process(x[i:i + 1024]) for i in range(0, len(x), 1024)])
        self.assertLessEqual(np.max(np.abs(y)), 10 ** (-1 / 20) + 1e-6)


if __name__ == "__main__":
    unittest.main()
