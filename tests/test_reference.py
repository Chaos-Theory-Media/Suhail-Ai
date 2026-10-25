"""Independent FFmpeg/EBU measurement smoke, not BS.1770 conformance certification."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

import testkit as helpers
import numpy as np
import soundfile as sf
from sawti import dsp


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg needed for an independent reference')
class IndependentMeasurementTests(unittest.TestCase):
    def test_loudness_and_true_peak_agree_with_ffmpeg_on_synthetic_programme(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'programme.wav'
            sf.write(path, helpers.speech(6, -8, 2), helpers.FS, subtype='PCM_24')
            measured = dsp.measure_file(path)
            proc = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(path), '-af',
                                   'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True,
                                  timeout=30, check=True)
            summary = proc.stderr.rsplit('Summary:', 1)[-1]
            loudness = float(re.search(r'I:\s*(-?[\d.]+) LUFS', summary).group(1))
            peak = float(re.search(r'Peak:\s*(-?[\d.]+) dBFS', summary).group(1))
            self.assertAlmostEqual(measured['integrated_lufs'], loudness, delta=0.3)
            self.assertAlmostEqual(measured['true_peak_dbtp'], peak, delta=0.3)


if __name__ == '__main__':
    unittest.main()
