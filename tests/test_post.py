import os
import tempfile
import time
import unittest

import testkit as helpers
import soundfile as sf

from sawti.agents import post
from sawti.studio import Studio


class PostTests(unittest.TestCase):
    def test_session_mix_and_master_job(self):
        st = Studio()
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "Show_Recorded")
        os.makedirs(rec)
        for i, peak in enumerate((-8, -20, -14), 1):
            sf.write(os.path.join(rec, f"Mic {i}_001.wav"), helpers.speech(40, peak, 1, seed=i), helpers.FS,
                     subtype="PCM_24")
        sf.write(os.path.join(rec, "Talkback_001.wav"), helpers.speech(40, -10, 1), helpers.FS)
        files = post.session_tracks(d)
        self.assertEqual(len(files), 3)  # talkback never mixed
        job = post.start_automix(st, files, "Show")
        while job["state"] == "running":
            time.sleep(0.5)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertTrue(job["result"]["within_spec"])
        self.assertTrue(os.path.isfile(job["result"]["output"]))
        qc = post.qc_files(files)
        self.assertTrue(all(q["samplerate"] == 48000 for q in qc))


if __name__ == "__main__":
    unittest.main()
