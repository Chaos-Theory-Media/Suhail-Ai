import datetime
import os
import tempfile
import time
import unittest

import testkit as helpers

from sawti import store
from sawti.agents import audition, learning
from sawti.studio import Studio


class StudioSimulationTests(unittest.TestCase):
    def setUp(self):
        self.st = Studio()
        self.root = tempfile.mkdtemp()
        store.put("recording_root", self.root)
        self.st.state = {}
        self.st.power_on("local")
        self.st.select_microphones([1, 2, 3], studio_idle=True)

    def tearDown(self):
        self.st.power_off()

    def test_fix_all_leaves_rate_for_individual_approval(self):
        self.assertTrue(any(f["id"] == "scarlett_rate" for f in self.st.check_all()))
        self.st.fix_all()
        self.assertTrue(any(f["id"] == "scarlett_rate" for f in self.st.check_all()))
        helpers.approved_action(self.st, 'set_scarlett_48k')
        self.assertFalse(any(f["id"] == "scarlett_rate" for f in self.st.check_all()))

    def test_zoom_devices_created_and_guest_channels_mapped(self):
        self.st.set_mode("zoom")
        helpers.prepare_sim_audio(self.st)
        ids = {f["id"]: f["severity"] for f in self.st.check_all()}
        self.assertEqual(ids["show_input"], "ok")
        self.assertEqual(ids["zoom_speaker"], "ok")
        cfg = self.st.meter_config("zoom")
        guests = next(s for s in cfg["sources"] if s["id"] == "guests")
        self.assertEqual([c + 1 for c in guests["chans"]], [19, 20])  # 18 Scarlett inputs, then BlackHole

    def test_live_guard_blocks_device_changes(self):
        self.st.go_live()
        with self.assertRaises(RuntimeError):
            self.st.apply("set_scarlett_48k")
        self.st.end_live()
        helpers.approved_action(self.st, "set_scarlett_48k")

    def test_template_and_session(self):
        info = audition.adopt_template(self.st, "local", os.path.join(helpers.FIXTURES, "podcast_template.sesx"))
        self.assertEqual([t["name"] for t in info["tracks"]], ["Mic 1", "Mic 2", "Mic 3"])
        self.assertTrue(all(t["armed"] for t in info["tracks"]))
        msg = audition.prepare_session(self.st, "local")
        self.assertIn("Prepared", msg)
        sess = self.st.state["session"]
        self.assertTrue(os.path.isfile(sess["path"]))
        self.assertTrue(sess["folder"].startswith(self.root))
        self.assertIn("Today's session", audition.prepare_session(self.st, "local"))  # idempotent

    def test_meters_and_coaching(self):
        helpers.prepare_sim_audio(self.st)
        self.assertTrue(self.st.start_meter())
        self.st.monitor.sim_focus = "mic2"
        time.sleep(4)
        from sawti.agents import levels
        c = {x["id"]: x for x in levels.coach(self.st, self.st.monitor.snapshot())}
        self.assertIn(c["mic2"]["status"], ("low", "very_low"))
        self.assertGreater(c["mic2"]["delta"], 0)
        self.assertIn("Gain 2", c["mic2"]["message"])

    def test_permission_block_detected(self):
        helpers.prepare_sim_audio(self.st)
        self.st.monitor.sim_faults.add("permission")
        self.st.start_meter()
        time.sleep(3.5)
        self.assertTrue(self.st.monitor.snapshot()["digital_silence"])
        self.assertTrue(any(f["id"] == "mic_permission" for f in self.st.check_all()))
        self.st.monitor.sim_faults.clear()

    def test_pretest_full_run(self):
        helpers.prepare_sim_audio(self.st)
        p = self.st.pretest.start()
        self.assertEqual(p["steps"][0]["id"], "checks")
        self.st.pretest.next()
        seen = {}
        while True:
            s = self.st.pretest.state()
            if s["done"]:
                break
            step = s["steps"][s["index"]]
            if step["kind"] == "record":
                self.st.pretest.check_recording()
            else:
                time.sleep(5)
                step = self.st.pretest.state()["steps"][s["index"]]
            seen[step["id"]] = (step["status"], step["detail"])
            self.st.pretest.next()
        self.assertEqual(seen["mic:mic1"][0], "pass", seen)
        self.assertEqual(seen["mic:mic2"][0], "warn")          # simulated quiet mic is coached
        self.assertIn("Gain 2 up", seen["mic:mic2"][1])
        self.assertEqual(seen["talkback"][0], "pass")

    def test_auto_prepare_predicted_show(self):
        audition.adopt_template(self.st, "local", os.path.join(helpers.FIXTURES, "podcast_template.sesx"))
        store.clear_learning()
        store.put("autofix", {"set_scarlett_48k": True})
        store.put('auto_prepare', True)
        soon = datetime.datetime.now() + datetime.timedelta(minutes=20)
        slot = soon.replace(minute=0, second=0, microsecond=0)
        if slot < datetime.datetime.now():
            slot += datetime.timedelta(hours=1)
        with store.connect() as db:
            for weeks in (1, 2, 3):
                ts = (slot - datetime.timedelta(weeks=weeks)).timestamp()
                db.execute("INSERT INTO events(ts,kind,data) VALUES (?,?,?)", (ts, "show_started", '{"mode":"local"}'))
        pred = learning.predict_next(self.st)
        self.assertEqual(pred["seen"], 3)
        self.st.state = {}
        done = learning.tick(self.st) if 0 <= pred["minutes_away"] <= learning.PREP_WINDOW_MIN else None
        if done is not None:
            self.assertFalse(any("Scarlett set to 48 kHz" in d for d in done))
            self.assertEqual(self.st.audio.devices()[0]['rate'], 44100)
            self.assertIsNotNone(self.st.state.get("session"))

    def test_autofix_suggested_after_repeats(self):
        store.clear_learning()
        for _ in range(2):
            store.log("fix_applied", action="prepare_session", by="operator", mode="zoom")
        sug = learning.autofix_suggestions(self.st)
        self.assertEqual(sug[0]["action"], "prepare_session")
        self.st.approve_autofix("prepare_session")
        self.assertFalse(learning.autofix_suggestions(self.st))
        with self.assertRaises(ValueError):
            self.st.approve_autofix("record")  # never automatic

    def test_learned_naming_pattern(self):
        store.clear_learning()
        store.save_observations([(f"/r/EP{i}_2026-0{i}-01.sesx", "/r", f"IMI_Talks_2026-0{i}-01.sesx", ".sesx", i, i)
                                 for i in range(1, 4)])
        name = learning.suggest_name(self.st, "local", datetime.date(2026, 10, 25))
        self.assertEqual(name, "IMI_Talks_2026-10-25")

    def test_folder_scan_refuses_home(self):
        with self.assertRaises(ValueError):
            learning.scan_folder(self.st, os.path.expanduser("~"))


if __name__ == "__main__":
    unittest.main()
