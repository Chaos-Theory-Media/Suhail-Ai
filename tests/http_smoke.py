"""Launch an isolated simulation server and exercise the real HTTP boundary.

No real devices, production files, user services or browser microphones are used.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix='sawti-http-') as temporary:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, SAWTI_DATA=temporary, SAWTI_INSTALL=temporary,
                   SAWTI_SIMULATE='1', SAWTI_PORT=str(port))
        logpath = Path(temporary) / 'server.log'
        with logpath.open('wb') as log:
            child = subprocess.Popen([sys.executable, str(ROOT / 'app.py'), '--simulate'], cwd=ROOT,
                                     env=env, stdout=log, stderr=log, start_new_session=True)
        def request(path, data=None, expect=200, extra=None):
            headers = {'Content-Type': 'application/json', 'X-Sawti': '1', **(extra or {})}
            req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                                         headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    status, payload = response.status, response.read()
            except urllib.error.HTTPError as response:
                status, payload = response.code, response.read()
            assert status == expect, (path, status, payload)
            results.append(dict(path=path, method=req.get_method(), status=status))
            return json.loads(payload) if payload.startswith(b'{') else payload
        try:
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError(logpath.read_text())
                try:
                    with urllib.request.urlopen(base + '/api/app', timeout=1) as response:
                        assert json.load(response)['simulated'] is True
                    break
                except urllib.error.URLError:
                    time.sleep(0.05)
            else:
                raise RuntimeError('Simulation server did not start')
            assert b'Sawti Studio' in request('/')
            request('/static/app.js')
            request('/static/app.css')
            assert request('/api/power')['on'] is False
            model_status = request('/api/models')
            assert model_status['hardware_qualified'] is False and model_status['chat']['available'] is False
            assert 'qwen3:30b-a3b-q4_K_M' in model_status['supported_chat_models']
            request('/api/knowledge', expect=503)
            request('/api/checks', expect=503)
            request('/api/power/on', {}, expect=403, extra={'Origin': 'https://foreign.example'})
            request('/api/settings', {'recording_root': str(Path(temporary) / 'Recordings')})
            assert request('/api/power/on', {'mode': 'local'})['on'] is True
            saved_templates = request('/api/audition/templates/search', {})
            assert saved_templates['files'] == [] and saved_templates['limited'] is False
            request('/api/audition/templates/inspect', {'id': 'not-found'}, expect=422)
            request('/api/audition/templates/use', {'id': 'not-found'}, expect=400)
            request('/api/audition/template', {'path': '/missing/template.sesx'}, expect=400)
            assert request('/api/knowledge')['documents'] == []
            request('/api/models/check', {'studio_idle': False}, expect=400)
            request('/api/models/check', {'studio_idle': True}, expect=400)
            request('/api/knowledge/ask', {'message': 'How should headphones be routed?'}, expect=400)
            request('/api/settings', {'llm_model': 'qwen3:30b-a3b-q4_K_M'}, expect=409)
            assert request('/api/status')['meter']['running'] is False
            assert request('/api/presenter-speech/state')['enabled'] is False
            assert request('/api/presenter-speech')['voices'] == []
            request('/api/presenter-speech/configure', {'uid': 'not-production', 'pair': [3,4],
                    'voice': {'en': 'Samantha'}, 'studio_idle': True, 'headphone_mapping_confirmed': True}, expect=422)
            request('/api/presenter-speech/test', {'studio_idle': True, 'operator_confirmed': True}, expect=422)
            request('/api/presenter-speech/enable', {'studio_idle': True, 'attestations': {}}, expect=422)
            request('/api/presenter-speech/speak', {'text': 'Hello'}, expect=422)
            assert request('/api/presenter-speech/mute', {})['enabled'] is False
            assert request('/api/chat', {'message': 'Has recording started?'})['intent'] == 'record_status'
            assert request('/api/chat', {'message': 'Is the audio good?'})['intent'] == 'audio_quality'
            identity = request('/api/chat', {'message': 'What is your name?'})
            assert identity['intent'] == 'identity' and identity['actions'] == []
            assert identity['reply'] == 'I’m Sawti (صوتي), your studio assistant.'
            for prompt, intent in [
                ('Can you help me with understanding how swati works?', 'help'),
                ('How can I use this system to do a zoom recroding?', 'zoom_guide'),
                ('كيف أسجل مقابلة زوم؟', 'zoom_guide'),
            ]:
                reply = request('/api/chat', {'message': prompt})
                assert reply['intent'] == intent and reply['actions'] == []
                assert '1.' in reply['reply']
            assert request('/api/power')['mode'] == 'local'
            report = request('/api/learning/report/refresh', {})
            assert report['available'] is True and report['stale'] is False
            assert request('/api/learning/report/download')['application'] == 'Sawti'
            assert request('/api/learning/report/folder', {})['opened'] is False
            request('/api/pretest/start', {}, expect=422)
            request('/api/podcast/microphones', {'inputs': [1, 4], 'studio_idle': True}, expect=422)
            plan = request('/api/podcast/microphones', {'inputs': [1, 3], 'studio_idle': True})['plan']
            assert plan['inputs'] == [1, 3] and plan['talkback_recorded'] is False
            template_folder = Path(temporary) / 'Saved Audition Templates'
            template_folder.mkdir()
            tree = ET.parse(ROOT / 'tests/fixtures/podcast_template.sesx')
            tracks = tree.find('.//tracks')
            tracks.remove(next(track for track in tracks if track.tag == 'audioTrack' and track.get('index') == '2'))
            tree.write(template_folder / 'Two people.sesx')
            choices = request('/api/audition/templates/search', {'folder': str(template_folder)})['files']
            assert len(choices) == 1
            selected_template_id = choices[0]['id']
            preview = request('/api/audition/templates/inspect', {'id': selected_template_id})
            assert preview['matches_plan'] is True and preview['template']['contains_media'] is False
            adopted = request('/api/audition/templates/use', {'id': selected_template_id,
                'sha256': preview['template']['sha256'], 'studio_idle': True, 'blank_template_confirmed': True})
            assert len(adopted['template']['tracks']) == 2
            episode = request('/api/session/prepare', {'title': 'Template Dropdown Test'})['session']
            assert Path(episode['path']).is_file()
            assert request('/api/audition')['template']['sample_rate'] == 48000
            assert request('/api/readiness')['full_autonomy_ready'] is False
            assert request('/api/audition/inspect', {})['status'] == 'simulation'
            assert request('/api/chat', {'message': 'صوتي، افحص الميكروفونات'})['source'] == 'rule'
            request('/api/action', {'action': 'set_scarlett_48k'}, expect=422)
            review = request('/api/action/review', {'action': 'set_scarlett_48k'})
            grant = dict(action='set_scarlett_48k', approval=review['token'], operator_confirmed=True, studio_idle=True)
            request('/api/action', grant)
            request('/api/action', grant, expect=422)
            request('/api/mode', {'mode': 'zoom'})
            request('/api/audition/templates/inspect', {'id': selected_template_id}, expect=422)
            assert request('/api/power')['microphone_plan'] is None
            for action in ('create_show_input', 'create_zoom_speaker'):
                review = request('/api/action/review', {'action': action})
                request('/api/action', dict(action=action, approval=review['token'],
                                            operator_confirmed=True, studio_idle=True))
            meter = request('/api/meter/start', {})['meter']
            assert next(s for s in meter['sources'] if s['id'] == 'guests')['chans'] == [19, 20]
            request('/api/live/start', {})
            live_reply = request('/api/chat', {'message': 'Has recording started?'})
            assert 'can’t confirm' in live_reply['reply'] and live_reply['actions'] == []
            request('/api/action/review', {'action': 'set_scarlett_48k'}, expect=422)
            request('/api/power/off', {})
            assert request('/api/power')['on'] is False
            request('/api/status', expect=503)
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(5)
    output = dict(requests=len(results), results=results, real_audio_capture=False)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(output, indent=2) + '\n')
    print(f'PASS: {len(results)} live HTTP checks; simulation server stopped; no real audio capture.')


if __name__ == '__main__':
    main()
