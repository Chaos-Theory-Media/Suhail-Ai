"""Local web API and UI. Listens on 127.0.0.1 only.

Security (QA fixes): requests must carry the local Host header (blocks DNS rebinding); every state-changing
request needs the X-Sawti header (a cross-site page cannot add it without a CORS pre-flight, which is refused);
no inline scripts (Content-Security-Policy); presenters are addressed by id.
"""
import os
import threading
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from . import VERSION, paths, store, voice
from .agents import audition, chat, learning, levels, post

PORT = int(os.environ.get("SAWTI_PORT", "8765"))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}
ALWAYS_OPEN = ("/api/app", "/api/power", "/api/power/on", "/api/power/off", "/api/quit", "/api/settings")

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
            if request.path in ('/api/chat', '/api/voice'):
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
    @app.get("/api/audition")
    def audition_info():
        app_ = audition.find_app() if not studio.audio.simulated else dict(name="Adobe Audition (simulated)")
        return jsonify(app=app_, template=audition.template_info(studio, studio.mode),
                       session=audition.today_session(studio, studio.mode),
                       suggested_name=learning.suggest_name(studio, studio.mode),
                       accessibility=studio.accessibility_ok)

    @app.post("/api/audition/template")
    def audition_template():
        info = run(lambda: audition.adopt_template(studio, studio.mode, str(body().get("path", ""))))
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
        return jsonify(learning.insights(studio))

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
            if k == 'llm_model' and v != 'qwen3:4b':
                raise ApiError('Only the approved local qwen3:4b model is supported.')
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
        text = run(lambda: voice.transcribe(audio, request.form.get("language")))
        try:
            speaker = voice.identify(audio)
        except Exception:
            speaker = dict(name=None)
        res = chat.answer(studio, text) if text else dict(reply="I did not catch that.", actions=[])
        return jsonify(text=text, speaker=speaker, **res)

    @app.get("/api/devices")
    def devices():
        devs = studio.devices(fresh=True)
        diagnostic = studio.audio.diagnostics() if hasattr(studio.audio, 'diagnostics') else {'simulated': True}
        return jsonify(devices=devs, diagnostics=diagnostic, helper=studio.audio.helper_available())

    return app
