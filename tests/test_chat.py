import unittest

import testkit as helpers  # noqa: F401

from sawti.agents.chat import detect, normalise

CASES = {
    'What is your name?': 'identity',
    "What's your name?": 'identity',
    'Swati, who are you?': 'identity',
    'صوتي، ما اسمك؟': 'identity',
    'Can you help me with understanding how swati works?': 'help',
    'How do I use this system?': 'help',
    'كيف أستخدم صوتي؟': 'help',
    'How can I use this system to do a zoom recroding?': 'zoom_guide',
    'How do I start recording in Zoom?': 'zoom_guide',
    'Can you help me record a Zoom interview?': 'zoom_guide',
    'كيف أسجل مقابلة زوم؟': 'zoom_guide',
    'How do I start recording a podcast?': 'recording_guide',
    'How do I stop recording in Zoom?': 'stop_guide',
    'How do I stop clipping while recording?': 'clip',
    'How are the Zoom guest levels?': 'guest_level',
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
    def test_identity_is_one_direct_sentence_without_hardware_or_ai_queries(self):
        from unittest.mock import Mock, patch
        from sawti.agents.chat import answer
        studio = Mock()
        with patch('sawti.agents.chat.llm_answer') as ai:
            reply = answer(studio, 'What is your name?')
        self.assertEqual(reply['reply'], 'I’m Sawti (صوتي), your studio assistant.')
        self.assertEqual(reply['actions'], [])
        studio.check_all.assert_not_called()
        studio.monitor.snapshot.assert_not_called()
        studio.apply.assert_not_called()
        ai.assert_not_called()

    def test_guides_teach_without_offering_transport_or_switching_mode(self):
        from unittest.mock import Mock, patch
        from sawti.agents.chat import answer
        studio = Mock(mode='local')
        for prompt in ('How do I use Sawti?', 'How do I start recording in Zoom?', 'كيف أسجل مقابلة زوم؟'):
            with self.subTest(prompt=prompt), patch('sawti.agents.chat.llm_answer') as ai:
                response = answer(studio, prompt)
                self.assertEqual(response['actions'], [])
                self.assertIn('1.', response['reply'])
                ai.assert_not_called()
        studio.apply.assert_not_called()
        studio.set_mode.assert_not_called()
        studio.check_all.assert_not_called()

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

    def test_explicit_reasoning_blocks_removed_but_operating_advice_preserved(self):
        from sawti.agents.chat import clean_ai_reply
        self.assertEqual(clean_ai_reply('<THINK>private reasoning</THINK>Use a mono track.'), 'Use a mono track.')
        self.assertEqual(clean_ai_reply('<analysis>private reasoning</analysis>Use a mono track.'), 'Use a mono track.')
        self.assertEqual(clean_ai_reply('<think>unfinished internal reasoning'), '')
        self.assertEqual(clean_ai_reply('Internal preamble</think>A mono track stores one channel.'),
                         'A mono track stores one channel.')
        self.assertEqual(clean_ai_reply('Check that recording is idle before changing routing.'),
                         'Check that recording is idle before changing routing.')

    def test_model_request_disables_thinking_and_does_not_display_separate_reasoning(self):
        from unittest.mock import Mock, patch
        from sawti.agents.chat import llm_answer, SYSTEM
        studio = Mock()
        studio.lifecycle.on = True
        with patch('sawti.agents.chat.llm_status', return_value={'running': True, 'available': True, 'model': 'qwen3:4b'}), \
                patch('sawti.agents.chat._ollama', return_value={'message': {
                    'thinking': 'PRIVATE_REASONS', 'content': '<think>PRIVATE_REASONS</think>A mono track stores one channel.'}}) as call:
            result = llm_answer(studio, 'What is a mono track?')
        self.assertEqual(result['reply'], 'A mono track stores one channel.')
        self.assertFalse(call.call_args.args[0]['think'])
        self.assertEqual(call.call_args.args[0]['options']['num_predict'], 512)
        self.assertIn('Answer the question directly', SYSTEM)
        studio.apply.assert_not_called()

    def test_ai_tools_can_propose_but_never_execute_recording(self):
        from unittest.mock import Mock, patch
        from sawti.agents.chat import llm_answer
        studio = Mock()
        studio.lifecycle.on = True
        studio.actions = {'record': Mock(label='Record')}
        responses = [
            {'message': {'tool_calls': [{'function': {'name': 'propose_action', 'arguments': {'action': 'record'}}}]}},
            {'message': {'content': 'Verify the active Audition session before approving Record.'}},
        ]
        with patch('sawti.agents.chat.llm_status', return_value={'running': True, 'available': True, 'model': 'qwen3:4b'}), \
                patch('sawti.agents.chat._ollama', side_effect=responses):
            result = llm_answer(studio, 'Offer the recording control.')
        self.assertEqual(result['actions'], [{'action': 'record', 'label': 'Record'}])
        studio.apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
