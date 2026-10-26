"""A local, redacted snapshot for manually sharing product feedback.

Never export the database itself: it contains private names and paths. Only
recognised event types, closed-set tokens and numeric measurements leave it.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
import platform
import re
import tempfile
import threading

from . import VERSION, paths

_lock = threading.RLock()
_errors = {}
KINDS = set('template_saved session_prepared session_opened chat_intent pretest_started pretest_done '
            'gain_advice mastered microphones_selected manual_confirmed fix_applied autofix_run '
            'mode_selected show_started show_ended auto_prepared presenter_added sawti_started operation_failed'.split())
ACTIONS = set('keep_awake open_mic_privacy open_accessibility open_focusrite open_studio_apps open_zoom '
              'open_audio_midi set_scarlett_48k set_blackhole_48k set_show_input_48k create_show_input '
              'repair_show_input create_zoom_speaker open_audition prepare_session open_session record stop'.split())
ENUMS = {
    'mode': {'local', 'zoom'}, 'action': ACTIONS, 'by': {'operator', 'auto'},
    'source': {'operator', 'sawti', 'mic1', 'mic2', 'mic3', 'talkback', 'guests'},
    'reason': {'power-on', 'auto-prep'},
    'intent': set('identity zoom_guide recording_guide stop_guide guided_recording record_start record_stop pretest clip talkback mixminus guest_level blackhole '
                  'zoom audition session filename save_where master mic_silent levels ready fix awake help'.split()),
    'error_type': {'ValueError', 'RuntimeError', 'OSError', 'ApiError'},
    'operation': {'/api/action', '/api/action/review', '/api/podcast/microphones', '/api/session/prepare',
                  '/api/audition/template', '/api/audition/inspect', '/api/meter/start', '/api/pretest/<step>',
                  '/api/voice', '/api/chat', '/api/mode', '/api/post/master', '/api/post/automix', '/api/post/qc'},
}
NUMBERS = {'delta', 'tracks', 'actions', 'count', 'minutes', 'lufs', 'error_status'}
BOOLEANS = {'ok', 'within', 'live', 'simulated'}
STEPS = {'checks', 'mic:mic1', 'mic:mic2', 'mic:mic3', 'talkback', 'remote', 'record'}


def folder():
    base = paths.data_dir() / 'learning_reports'
    if base.is_symlink():
        raise OSError('The learning report folder is a symlink; no report was written.')
    base.mkdir(mode=0o700, exist_ok=True)
    return base


def report_path():
    return folder() / 'Sawti-Learnings.json'


def sanitise(event):
    kind = event.get('kind')
    clean = {'kind': kind if kind in KINDS else 'unclassified_event'}
    timestamp = event.get('ts')
    if type(timestamp) in (float, int) and math.isfinite(timestamp):
        clean['time_utc'] = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    if kind not in KINDS:
        return clean
    for key, value in event.items():
        if key in ENUMS and isinstance(value, str) and value in ENUMS[key]:
            clean[key] = value
        elif key in NUMBERS and type(value) in (float, int) and math.isfinite(value):
            clean[key] = value
        elif key in BOOLEANS and type(value) is bool:
            clean[key] = value
        elif key == 'inputs' and isinstance(value, list) and all(type(v) is int and v in (1, 2, 3) for v in value):
            clean[key] = value[:3]
        elif key == 'failed' and isinstance(value, list):
            clean[key] = [v for v in value if isinstance(v, str) and v in STEPS]
        elif key == 'sawti_version' and isinstance(value, str) and re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}', value):
            clean[key] = value
    return clean


def refresh():
    from . import store
    with _lock:
        target = report_path()
        if target.is_symlink():
            raise OSError('The learning report file is a symlink; no report was written.')
        events = [sanitise(e) for e in store.events(limit=None)]
        payload = dict(schema=1, application='Sawti', application_version=VERSION,
                       generated_utc=datetime.now(timezone.utc).isoformat(),
                       platform=platform.system(), simulation=paths.simulate(),
                       macos_version=platform.mac_ver()[0] or None, architecture=platform.machine(),
                       retention_days=store.RETENTION_DAYS, event_count=len(events),
                       event_counts=dict(Counter(e['kind'] for e in events)),
                       scope='All retained event rows; private fields omitted. Not the full private learning database.',
                       excluded=['recordings', 'voice_signatures', 'presenter_names', 'chat_text',
                                 'file_paths', 'session_names', 'filenames', 'raw_error_messages'],
                       events=events)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                             prefix='.learning-', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
            os.replace(temporary, target)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        _errors.pop(str(paths.data_dir()), None)
        return target


def refresh_safely():
    try:
        return refresh()
    except (OSError, ValueError, OverflowError) as exc:
        # Reporting must never break studio operation or discard SQLite history.
        _errors[str(paths.data_dir())] = type(exc).__name__
        return None


def status():
    target = paths.data_dir() / 'learning_reports' / 'Sawti-Learnings.json'
    error = _errors.get(str(paths.data_dir()))
    return dict(folder=str(target.parent), filename=target.name,
                available=target.is_file() and not target.is_symlink(),
                error=error, stale=bool(error), automatic=True, retention_days=180)
