import unittest

import testkit as helpers  # noqa: F401

from sawti.agents.chat import detect, normalise

CASES = {
    "Sawti, check the studio before recording": "ready",
    "Check the studio before recording": "ready",
    "Sawti, why is microphone one silent?": "mic_silent",
    "Sawti, check my three microphones": "levels",
    "How are the mic levels?": "levels",
    "Sawti, help me name and save this recording": "filename",
    "Suggest a filename": "filename",
    "Sawti, suggest a filename for today's podcast": "filename",
    "Sawti, where do we usually save recordings?": "save_where",
    "Sawti, what should we test before starting?": "pretest",
    "Run the pre-test": "pretest",
    "Sawti, is BlackHole available?": "blackhole",
    "Sawti, check the Zoom setup": "zoom",
    "Sawti, can the guest hear the talkback?": "talkback",
    "Sawti, how do I test mix-minus?": "mixminus",
    "Sawti, is Audition running?": "audition",
    "Sawti, what should we do if a microphone clips?": "clip",
    "Sawti, check the remote guest return level": "guest_level",
    "Start recording now": "record_start",
    "Sawti please test the mics and if all is good count me down and start recording": "guided_recording",
    "Start recording after you check the microphones": "guided_recording",
    "Count down and begin recording": "guided_recording",
    "صوتي، افحص الميكروفونات ثم ابدأ التسجيل": "guided_recording",
    "Stop the recording": "record_stop",
    "Prepare and open today's session": "session",
    "Master the episode to -16 LUFS": "master",
    "صوتي، افحص الميكروفونات": "levels",
    "صوتي، هل برنامج أوديشن يعمل؟": "audition",
    "صوتي، افحص إعدادات زوم": "zoom",
    "صوتي، هل الاستوديو جاهز؟": "ready",
}


class ChatRoutingTests(unittest.TestCase):
    def test_conditional_recording_never_offers_transport(self):
        from unittest.mock import Mock
        from sawti.agents.chat import answer
        studio = Mock()
        studio.check_all.return_value = []
        studio.events.return_value = []
        studio.observations.return_value = []
        studio.settings.return_value = {}
        studio.mode = 'local'
        for prompt in (
            'Sawti please test the mics and if all is good count me down and start recording',
            'صوتي، افحص الميكروفونات ثم ابدأ التسجيل',
        ):
            with self.subTest(prompt=prompt):
                result = answer(studio, prompt)
                self.assertEqual(result['intent'], 'guided_recording')
                self.assertEqual([a['action'] for a in result['actions']], ['pretest'])
                studio.apply.assert_not_called()

    def test_every_suggested_prompt_routes_correctly(self):
        wrong = {q: (detect(q), want) for q, want in CASES.items() if detect(q) != want}
        self.assertEqual(wrong, {})

    def test_wake_word_removed(self):
        # QA defect: 'صوتي' contains 'صوت', which used to trigger the microphone answer for every Arabic prompt
        self.assertEqual(normalise("صوتي، هل برنامج أوديشن يعمل؟"), "هل برنامج أوديشن يعمل")
        self.assertEqual(normalise("Sawti, is Audition running?"), "is audition running")


if __name__ == "__main__":
    unittest.main()
