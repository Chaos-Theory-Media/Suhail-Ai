"""Local web API and UI. Listens on 127.0.0.1 only.

Security (QA fixes): requests must carry the local Host header (blocks DNS rebinding); every state-changing
request needs the X-Sawti header (a cross-site page cannot add it without a CORS pre-flight, which is refused);
no inline scripts (Content-Security-Policy); presenters are addressed by id.
"""
import os
import threading
import time
from pathlib import Path

from flask import Flask, g, jsonify, request, send_file, send_from_directory

from . import VERSION, knowledge, learning_report, models, paths, presenter_speech, readiness, store, voice
from .agents import audition, chat, learning, levels, post

PORT = int(os.environ.get("SAWTI_PORT", "8765"))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}
ALWAYS_OPEN = ("/api/app", "/api/power", "/api/power/on", "/api/power/off", "/api/quit", "/api/settings", '/api/models')

SETTING_RULES = {
    "recording_root": str, "loudness_target": float, "true_peak": float, "speech_target": float,
    "leveler_enabled": bool, "leveler_output": str, "auto_prepare": bool, "llm_model": str,
    "source_names": dict, "show_name": dict,
}


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def create_app(studio):
    app = Flask(__name__, static_folder=str(paths.APP_ROOT / "static"), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

    def body():
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ApiError("Expected a JSON object.")
        return data

    @app.before_request
    def guard():
        if request.host not in ALLOWED_HOSTS:
            return jsonify(error="Forbidden host"), 403
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if request.headers.get("X-Sawti") != "1" or (origin and origin not in ALLOWED_ORIGINS):
                return jsonify(error="Forbidden"), 403
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.path.startswith('/api/'):
            epoch = studio.power_epoch
            studio.lock.acquire()
            g.studio_locked = True
            if epoch != studio.power_epoch and request.path not in ALWAYS_OPEN:
                return jsonify(error="Sawti power changed while this request was waiting."), 409
            # Read-only inference/conversion may take seconds. Do not delay OFF
            # behind it; discard the response if its admission epoch changes.
            if request.path in ('/api/chat', '/api/voice', '/api/audition/inspect',
                                '/api/models/check', '/api/knowledge/import', '/api/knowledge/ask',
                                '/api/audition/templates/search', '/api/audition/templates/inspect',
                                '/api/audition/template', '/api/audition/templates/use',
                                '/api/presenter-speech/speak', '/api/presenter-speech/test'):
                g.admitted_epoch = epoch
                g.studio_locked = False
                studio.lock.release()
        if request.path.startswith("/api/") and request.path not in ALWAYS_OPEN and not studio.lifecycle.on:
            return jsonify(error="Sawti is OFF. Switch it ON first."), 503

    @app.teardown_request
    def release_lock(error):
        if g.pop('studio_locked', False):
            studio.lock.release()

    @app.after_request
    def headers(resp):
        if hasattr(g, 'admitted_epoch') and (g.admitted_epoch != studio.power_epoch or not studio.lifecycle.on):
            resp = jsonify(error='Sawti was switched OFF; this result was discarded.')
            resp.status_code = 503
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
                                                   "style-src 'self'; script-src 'self'; connect-src 'self'; "
                                                   "frame-ancestors 'none'")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(ApiError)
    def api_error(e):
        studio.learn('operation_failed', operation=request.url_rule.rule if request.url_rule else None,
                     error_type='ApiError', error_status=e.status)
        return jsonify(error=str(e)), e.status

    def run(fn):
        try:
            return fn()
        except ApiError:
            raise
        except (ValueError, RuntimeError, OSError) as exc:
            raise ApiError(str(exc), 422)

    @app.errorhandler(ValueError)
    @app.errorhandler(RuntimeError)
    @app.errorhandler(OSError)
    def operation_error(exc):
        studio.learn('operation_failed', operation=request.url_rule.rule if request.url_rule else None,
                     error_type=next(t.__name__ for t in (ValueError, RuntimeError, OSError) if isinstance(exc, t)),
                     error_status=422)
        return jsonify(error=str(exc)), 422

    # ------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return send_from_directory(str(paths.APP_ROOT / "static"), "index.html")

    @app.get("/api/app")
    def app_info():
        info = studio.snapshot()
        capability = dict(transcribe=False, identify=False) if studio.audio.simulated else voice.available()
        info.update(version=VERSION, voice=capability, helper=studio.audio.helper_available())
        return jsonify(info)

    # ------------------------------------------------------------ power
    @app.get("/api/power")
    def power():
        return jsonify(studio.snapshot())

    @app.post("/api/power/on")
    def power_on():
        mode = body().get("mode", studio.mode)
        run(lambda: studio.power_on(mode))
        return jsonify(studio.snapshot())

    @app.post("/api/power/off")
    def power_off():
        studio.power_off()
        return jsonify(studio.snapshot())

    @app.post("/api/quit")
    def quit_app():
        studio.power_off()

        def bye():
            studio.lifecycle.shutdown()
            os._exit(0)
        threading.Timer(0.4, bye).start()
        return jsonify(ok=True, message="Sawti has closed. You can close this tab.")

    # ------------------------------------------------------------ live status
    @app.get("/api/status")
    def status():
        snap = studio.monitor.snapshot()
        coach = levels.coach(studio, snap) if snap["running"] else []
        return jsonify(studio=studio.snapshot(), meter=snap, coach=coach)

    @app.get("/api/checks")
    def checks():
        return jsonify(findings=studio.check_all(), mode=studio.mode)

    @app.post("/api/action")
    def action():
        d = body()
        name = str(d.get("action", ""))
        msg = run(lambda: studio.apply(name, approval=d.get('approval'),
                                      operator_confirmed=d.get('operator_confirmed'),
                                      studio_idle=d.get('studio_idle')))
        return jsonify(message=msg, findings=studio.check_all())

    @app.post('/api/action/review')
    def action_review():
        return jsonify(run(lambda: studio.approvals.review(str(body().get('action', '')))))

    @app.post("/api/confirm")
    def confirm():
        studio.confirm(str(body().get("id", ""))[:60])
        return jsonify(findings=studio.check_all())

    @app.post("/api/mode")
    def mode():
        msg = run(lambda: studio.set_mode(body().get("mode")))
        return jsonify(message=msg, studio=studio.snapshot())

    @app.post("/api/meter/start")
    def meter_start():
        ok = studio.start_meter()
        snap = studio.monitor.snapshot()
        if not ok:
            raise ApiError(snap.get("error") or "Meters could not start.", 422)
        return jsonify(meter=snap)

    @app.post("/api/meter/stop")
    def meter_stop():
        studio.stop_meter()
        return jsonify(ok=True)

    @app.post("/api/live/start")
    def live_start():
        return jsonify(message=studio.go_live())

    @app.post("/api/live/end")
    def live_end():
        return jsonify(message=studio.end_live())

    # ------------------------------------------------------------ pre-test
    @app.get("/api/pretest")
    def pretest_state():
        return jsonify(studio.pretest.state())

    @app.post("/api/pretest/<step>")
    def pretest_step(step):
        fns = dict(start=studio.pretest.start, next=studio.pretest.next, skip=studio.pretest.skip,
                   retest=studio.pretest.retest, cancel=studio.pretest.cancel,
                   recording=studio.pretest.check_recording)
        if step not in fns:
            raise ApiError("Unknown step", 404)
        return jsonify(run(fns[step]))

    # ------------------------------------------------------------ Audition
    @app.get('/api/presenter-speech')
    def presenter_speech_info():
        devices = [d for d in studio.devices(fresh=True) if presenter_speech.is_scarlett(d)]
        return jsonify(state=studio.presenter_speech.snapshot(), devices=devices,
                       voices=[] if studio.audio.simulated else run(presenter_speech.installed_voices))

    @app.get('/api/presenter-speech/state')
    def presenter_speech_state():
        return jsonify(studio.presenter_speech.snapshot())

    @app.post('/api/presenter-speech/configure')
    def presenter_speech_configure():
        d = body()
        result = run(lambda: studio.presenter_speech.configure(d.get('uid'), d.get('pair'), d.get('voice'),
                     idle=d.get('studio_idle'), mapped=d.get('headphone_mapping_confirmed')))
        studio.approvals.invalidate()
        studio.learn('presenter_voice_configured', mode=studio.mode)
        return jsonify(result)

    @app.post('/api/presenter-speech/test')
    def presenter_speech_test():
        d = body()
        started = run(lambda: studio.presenter_speech.start('', test=True, idle=d.get('studio_idle'),
                      confirmed=d.get('operator_confirmed'), epoch=g.admitted_epoch))
        return jsonify(started=started, state=studio.presenter_speech.snapshot())

    @app.post('/api/presenter-speech/enable')
    def presenter_speech_enable():
        d = body()
        result = run(lambda: studio.presenter_speech.authorise(d.get('attestations'), idle=d.get('studio_idle')))
        studio.approvals.invalidate()
        studio.learn('presenter_voice_enabled', mode=studio.mode)
        return jsonify(result)

    @app.post('/api/presenter-speech/speak')
    def presenter_speech_speak():
        started = run(lambda: studio.presenter_speech.start(body().get('text'), epoch=g.admitted_epoch))
        return jsonify(started=started, state=studio.presenter_speech.snapshot())

    @app.post('/api/presenter-speech/mute')
    def presenter_speech_mute():
        studio.presenter_speech.stop()
        studio.learn('presenter_voice_muted', mode=studio.mode)
        return jsonify(studio.presenter_speech.snapshot())

    @app.post('/api/podcast/microphones')
    def podcast_microphones():
        d = body()
        return jsonify(run(lambda: studio.select_microphones(d.get('inputs'), d.get('studio_idle'))))

    @app.get('/api/readiness')
    def autonomy_readiness():
        return jsonify(run(lambda: readiness.report(studio)))

    @app.post('/api/audition/inspect')
    def audition_inspect():
        return jsonify(run(lambda: readiness.inspect_audition(studio)))

    @app.get("/api/audition")
    def audition_info():
        app_ = audition.find_app() if not studio.audio.simulated else dict(name="Adobe Audition (simulated)")
        return jsonify(app=app_, template=audition.template_info(studio, studio.mode),
                       session=audition.today_session(studio, studio.mode),
                       microphone_plan=studio.mic_plan,
                       suggested_name=learning.suggest_name(studio, studio.mode),
                       accessibility=studio.accessibility_ok)

    @app.post("/api/audition/template")
    def audition_template():
        data = body()
        if studio.live or data.get('studio_idle') is not True or data.get('blank_template_confirmed') is not True:
            raise ApiError('Confirm all recording is idle and this is an empty reusable template.')
        if not isinstance(data.get('path'), str):
            raise ApiError('Choose a saved .sesx file path.')
        from .template_catalog import context
        with studio.lock:
            if g.admitted_epoch != studio.power_epoch:
                raise ApiError('Studio power changed; the template was not adopted.')
            bound, mode = context(studio), studio.mode
        info = run(lambda: audition.adopt_template(studio, mode, data['path'], expected_context=bound))
        return jsonify(template=info)

    @app.post('/api/audition/templates/search')
    def audition_templates_search():
        return jsonify(run(lambda: studio.template_catalog.search(body().get('folder'))))

    @app.post('/api/audition/templates/inspect')
    def audition_templates_inspect():
        choice = body().get('id')
        source = run(lambda: studio.template_catalog.resolve(choice))
        info = run(lambda: audition.parse_sesx(source))
        run(lambda: studio.template_catalog.resolve(choice))
        expected = len(studio.mic_plan['inputs']) if studio.mode == 'local' and studio.mic_plan else None
        return jsonify(template=info, expected_tracks=expected,
                       matches_plan=None if expected is None else len(info['tracks']) == expected)

    @app.post('/api/audition/templates/use')
    def audition_templates_use():
        data = body()
        if studio.live or data.get('studio_idle') is not True or data.get('blank_template_confirmed') is not True:
            raise ApiError('Confirm all recording is idle and this is an empty reusable template.')
        if not isinstance(data.get('sha256'), str) or len(data['sha256']) != 64:
            raise ApiError('Inspect the selected file before using it as a template.')
        with studio.lock:
            if g.admitted_epoch != studio.power_epoch:
                raise ApiError('Studio power changed; the template was not adopted.')
            source = run(lambda: studio.template_catalog.resolve(data.get('id')))
            bound, mode = studio.template_catalog.bound_context, studio.mode
        info = run(lambda: audition.adopt_template(studio, mode, source, expected_sha256=data['sha256'], expected_context=bound))
        return jsonify(template=info)

    @app.post("/api/session/prepare")
    def session_prepare():
        title = body().get("title", "")
        if not isinstance(title, str):
            raise ApiError('Session title must be text.')
        title = title.strip()
        if title:
            import re
            title = re.sub(r"[^\w\- ]+", "", title).strip().replace(" ", "_")[:80] or None
        msg = run(lambda: audition.prepare_session(studio, studio.mode, title or None))
        return jsonify(message=msg, session=studio.state.get("session"))

    # ------------------------------------------------------------ post-production
    @app.get("/api/post/files")
    def post_files():
        folder = request.args.get("folder") or (studio.state.get("session") or {}).get("folder")
        if not folder or not Path(folder).expanduser().is_dir():
            return jsonify(folder=folder, files=[])
        return jsonify(folder=folder, files=post.session_tracks(Path(folder).expanduser()))

    def _wav(p):
        p = Path(str(p)).expanduser()
        if p.suffix.lower() not in (".wav", ".aif", ".aiff", ".flac") or not p.is_file():
            raise ApiError(f"Not an audio file: {p.name}")
        return str(p)

    @app.post("/api/post/master")
    def post_master():
        return jsonify(job=post.start_master(studio, _wav(body().get("path", ""))))

    @app.post("/api/post/automix")
    def post_automix():
        d = body()
        files = [_wav(f) for f in file_list(d, 16)]
        name = d.get("name") or (studio.state.get("session") or {}).get("name") or "Episode"
        return jsonify(job=post.start_automix(studio, files, name))

    @app.post("/api/post/qc")
    def post_qc():
        files = [_wav(f) for f in file_list(body(), 32)]
        return jsonify(job=post.start_qc(files))

    def file_list(data, maximum):
        files = data.get('files')
        if not isinstance(files, list) or not 1 <= len(files) <= maximum or not all(isinstance(f, str) for f in files):
            raise ApiError(f"Select 1–{maximum} audio files.")
        return files

    @app.get("/api/jobs/<jid>")
    def job(jid):
        j = post.job(jid)
        if not j:
            raise ApiError("Unknown job", 404)
        return jsonify(j)

    # ------------------------------------------------------------ learning
    @app.get("/api/learning")
    def learning_info():
        return jsonify(**learning.insights(studio), report=learning_report.status())

    @app.post('/api/learning/report/refresh')
    def learning_report_refresh():
        run(learning_report.refresh)
        return jsonify(learning_report.status())

    @app.get('/api/learning/report/download')
    def learning_report_download():
        state = learning_report.status()
        if state['stale'] or not state['available']:
            raise ApiError('Refresh the learning report before downloading it.', 409)
        return send_file(learning_report.report_path(), as_attachment=True,
                         download_name='Sawti-Learnings.json', mimetype='application/json')

    @app.post('/api/learning/report/folder')
    def learning_report_folder():
        if studio.audio.simulated:
            return jsonify(folder=str(learning_report.folder()), opened=False)
        import subprocess
        import sys
        if sys.platform != 'darwin':
            raise ApiError('Open folder is available on the Mac. Use Download report instead.')
        target = run(learning_report.folder)
        result = subprocess.run(['/usr/bin/open', str(target)], capture_output=True, timeout=10)
        if result.returncode:
            raise ApiError('Finder could not open the learning report folder.')
        return jsonify(folder=str(target), opened=True)

    @app.post("/api/learning/scan")
    def learning_scan():
        return jsonify(run(lambda: learning.scan_folder(studio, str(body().get("folder", "")))))

    @app.post("/api/learning/autofix")
    def learning_autofix():
        d = body()
        if type(d.get('enabled', True)) is not bool:
            raise ApiError('enabled must be true or false.')
        run(lambda: studio.approve_autofix(str(d.get("action", "")), d.get("enabled", True)))
        return jsonify(learning.insights(studio))

    @app.post("/api/learning/reset")
    def learning_reset():
        store.clear_learning()
        return jsonify(learning.insights(studio))

    # ------------------------------------------------------------ settings
    @app.get("/api/settings")
    def settings_get():
        s = store.all_settings()
        return jsonify(settings={k: s[k] for k in SETTING_RULES}, profiles={m: studio.profile(m) for m in ("local", "zoom")})

    @app.post("/api/settings")
    def settings_post():
        updates = {}
        for k, v in body().items():
            if k not in SETTING_RULES:
                raise ApiError(f"Unknown setting {k}")
            typ = SETTING_RULES[k]
            try:
                if typ is bool and type(v) is not bool:
                    raise ValueError()
                if typ is str and not isinstance(v, str):
                    raise ValueError()
                if typ is dict and not isinstance(v, dict):
                    raise ValueError()
                v = typ(v) if typ is not dict else dict(v)
            except (TypeError, ValueError):
                raise ApiError(f"Invalid value for {k}")
            if k == "recording_root":
                p = Path(v).expanduser()
                if not p.is_absolute():
                    raise ApiError("Recording folder must be a full path, e.g. /Users/studio/Music/Recordings")
                v = str(p)
            if k == "loudness_target" and not -24 <= v <= -12:
                raise ApiError("Loudness target must be between -24 and -12 LUFS.")
            if k == "true_peak" and not -3 <= v <= 0:
                raise ApiError("True-peak ceiling must be between -3 and 0 dBTP.")
            if k == "speech_target" and not -26 <= v <= -14:
                raise ApiError("Speech target must be between -26 and -14 LUFS.")
            if k in ('source_names', 'show_name'):
                for mode, names in v.items():
                    if mode not in ('local', 'zoom'):
                        raise ApiError('Unknown show type in names.')
                    valid = (isinstance(names, str) and 0 < len(names) <= 80) if k == 'show_name' else (
                        isinstance(names, dict) and all(isinstance(n, str) and isinstance(t, str)
                                                      and len(t) <= 60 for n, t in names.items()))
                    if not valid:
                        raise ApiError(f'Invalid value for {k}')
            if k == 'llm_model' and v not in models.CHAT_MODELS:
                raise ApiError('Select an approved local Qwen3 model.')
            if k == 'llm_model' and studio.lifecycle.on and v != studio.settings(k):
                raise ApiError('Switch Sawti OFF before changing the chat model.', 409)
            if k == 'leveler_enabled' and v and not studio.audio.simulated:
                raise ApiError('Inline output is not qualified on this Mac. Use capture-only monitoring.')
            if (k in ('leveler_enabled', 'leveler_output', 'recording_root') and studio.live
                    and v != studio.settings(k)):
                raise ApiError('End the live show before changing audio or recording settings.', 409)
            updates[k] = v
        for k, v in updates.items():
            if k == 'recording_root':
                Path(v).mkdir(parents=True, exist_ok=True)
        with store.closing(store.connect()) as db, db:
            import json
            db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)',
                           [(k, json.dumps(v)) for k, v in updates.items()])
        studio.approvals.invalidate()
        return settings_get()

    # ------------------------------------------------------------ presenters & voice (optional)
    @app.get("/api/presenters")
    def presenters():
        return jsonify(people=store.people(), voice=voice.available())

    @app.post("/api/presenters")
    def presenter_add():
        d = body()
        run(lambda: store.add_person(d.get("name", ""), d.get("consent")))
        studio.learn("presenter_added")
        return jsonify(people=store.people())

    @app.delete("/api/presenters/<int:pid>")
    def presenter_delete(pid):
        store.remove_person(pid)
        return jsonify(people=store.people())

    @app.post("/api/presenters/<int:pid>/voice")
    def presenter_voice(pid):
        if studio.audio.simulated:
            raise ApiError('Simulation does not capture or enrol real voices.')
        f = request.files.get("audio")
        if not f:
            raise ApiError("No audio received.")
        run(lambda: voice.enrol(pid, f.read()))
        return jsonify(people=store.people())

    @app.post("/api/chat")
    def chat_msg():
        text = body().get("message", "")
        if not isinstance(text, str):
            raise ApiError('Message must be text.')
        text = text.strip()[:2000]
        if not text:
            raise ApiError("Type a question first.")
        return jsonify(run(lambda: chat.answer(studio, text)))

    @app.post("/api/voice")
    def voice_cmd():
        if studio.audio.simulated:
            raise ApiError('Simulation does not use real microphones or voice models.')
        f = request.files.get("audio")
        if not f:
            raise ApiError("No audio received.")
        audio = f.read()
        text = run(lambda: voice.transcribe(audio, request.form.get("language"), studio=studio))
        try:
            speaker = voice.identify(audio)
        except Exception:
            speaker = dict(name=None)
        res = chat.answer(studio, text) if text else dict(reply="I did not catch that.", actions=[])
        return jsonify(text=text, speaker=speaker, **res)

    @app.get('/api/models')
    def model_status():
        return jsonify(**studio.local_models.snapshot(), chat=chat.llm_status(studio))

    @app.post('/api/models/check')
    def model_check():
        if body().get('studio_idle') is not True or studio.live:
            raise ApiError('Confirm production is idle before running model checks.')
        if not chat.llm_status(studio)['available']:
            raise ApiError('The selected local chat model is not available.')
        result = run(lambda: studio.local_models.run('selftest', {}, timeout=180))
        with studio.local_models.chat_slot() as admitted:
            if not admitted or g.admitted_epoch != studio.power_epoch:
                raise ApiError('Studio state changed; model check was cancelled.')
            probe = run(lambda: chat._ollama({'model': studio.settings('llm_model'), 'stream': False,
                'think': False, 'messages': [{'role': 'user', 'content': 'Reply with READY.'}],
                'keep_alive': '2m', 'options': {'num_ctx': 8192, 'num_predict': 16}}, timeout=90))
        if not chat.clean_ai_reply(probe.get('message', {}).get('content', '')):
            studio.local_models.last_check = None
            raise ApiError('Specialists passed but the chat model did not return a usable answer.')
        with studio.lock:
            if g.admitted_epoch != studio.power_epoch or not studio.lifecycle.on:
                raise ApiError('Studio state changed; model check was cancelled.')
            studio.local_models.last_check = dict(passed=True, time=time.time(), hardware_qualified=False)
        result['message'] += ' The selected chat model also returned a synthetic test response.'
        return jsonify(result)

    @app.get('/api/knowledge')
    def knowledge_list():
        return jsonify(documents=knowledge.inventory())

    @app.post('/api/knowledge/import')
    def knowledge_import():
        if request.form.get('rights_confirmed') != 'true' or request.form.get('studio_idle') != 'true':
            raise ApiError('Confirm you may use this reference and production is idle.')
        upload = request.files.get('file')
        if not upload:
            raise ApiError('Choose a reference file.')
        return jsonify(documents=run(lambda: knowledge.import_document(studio, upload.read(), upload.filename,
                       request.form.get('title'), request.form.get('version'))))

    @app.delete('/api/knowledge/<doc_id>')
    def knowledge_remove(doc_id):
        run(lambda: knowledge.remove(doc_id))
        return jsonify(documents=knowledge.inventory())

    @app.post('/api/knowledge/ask')
    def knowledge_ask():
        text = body().get('message')
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ApiError('Enter a question of at most 2,000 characters.')
        if studio.live:
            raise ApiError('Reference inference is reserved for production-idle use until Mac performance is qualified.')
        references = run(lambda: knowledge.retrieve(studio, text))
        if not references:
            raise ApiError('Import relevant reference documents in Settings first.')
        result = run(lambda: chat.llm_answer(studio, text, references=references))
        if not result:
            raise ApiError('The selected local chat model did not answer. Check its download and service status.')
        result.update(actions=[], references=[dict(number=i, **{k: ref[k] for k in ('title', 'version', 'page')})
                                             for i, ref in enumerate(references, 1)])
        return jsonify(result)

    @app.get("/api/devices")
    def devices():
        devs = studio.devices(fresh=True)
        diagnostic = studio.audio.diagnostics() if hasattr(studio.audio, 'diagnostics') else {'simulated': True}
        return jsonify(devices=devs, diagnostics=diagnostic, helper=studio.audio.helper_available())

    return app
