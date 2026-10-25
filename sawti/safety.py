"""Operator approvals are single-use, short-lived, and bound to observed state.

Recording transport is not observable through Audition's process name. Never
interpret Sawti's LIVE flag as proof that external recording is idle.
"""
import hashlib
import json
import secrets
import time
from functools import wraps


def serialised(fn):
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            return fn(self, *args, **kwargs)
    return wrapped


def powered(fn):
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            self.require_on()
            return fn(self, *args, **kwargs)
    return wrapped


class Approvals:
    def __init__(self, studio):
        self.studio = studio
        self.pending = {}

    def invalidate(self):
        self.pending.clear()

    def fingerprint(self):
        st = self.studio
        state = dict(mode=st.mode, live=st.live, session=st.state.get('session'),
                     devices=st.devices(fresh=True), settings=st.settings('leveler_enabled'))
        return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()

    def review(self, action):
        st = self.studio
        with st.lock:
            st.require_on()
            a = st.actions.get(action)
            if not a or not a.impact:
                raise ValueError('This action does not require an audio-impact approval.')
            if st.live and not a.live_safe:
                raise RuntimeError('End the live show before reviewing device changes.')
            token = secrets.token_urlsafe(32)
            now = time.monotonic()
            self.pending = {k: v for k, v in self.pending.items() if v['expires'] > now}
            # Bound memory even if a faulty client repeatedly opens reviews.
            if len(self.pending) >= 32:
                self.pending.pop(next(iter(self.pending)))
            self.pending[token] = dict(action=action, expires=now + 30, fingerprint=self.fingerprint())
            return dict(token=token, action=action, label=a.label, impact=a.impact,
                        requires_idle=action != 'stop', expires_in=30,
                        recording_state='unknown',
                        warning='Sawti cannot observe Audition recording state. Check all recording apps. '
                                'This action may interrupt audio or change the active session. '
                                'Device changes also stop Sawti meters and invalidate prior sound checks.')

    def consume(self, action, token, confirmed, studio_idle):
        grant = self.pending.pop(token, None) if isinstance(token, str) else None
        if confirmed is not True or not grant or grant['action'] != action:
            raise RuntimeError('Review and explicitly authorise this specific action first.')
        if grant['expires'] <= time.monotonic() or grant['fingerprint'] != self.fingerprint():
            raise RuntimeError('Approval expired or studio state changed. Review the action again.')
        if action != 'stop' and studio_idle is not True:
            raise RuntimeError('Confirm that all production recording is idle before this action.')
