"""Session microphone plans. These describe intent, never change hardware or Audition."""
import uuid


def microphone_plan(inputs):
    if (not isinstance(inputs, list) or not 1 <= len(inputs) <= 3
            or any(type(i) is not int or i not in (1, 2, 3) for i in inputs)
            or 1 not in inputs or len(set(inputs)) != len(inputs)):
        raise ValueError('Choose Mic 1 and up to two guest mics from inputs 2 and 3. Input 4 is talkback only.')
    return dict(id=uuid.uuid4().hex, inputs=sorted(inputs), presenter_input=1,
                talkback_input=4, talkback_recorded=False)


def require_plan(studio, mode=None):
    if (mode or studio.mode) == 'local' and not studio.mic_plan:
        raise RuntimeError('Confirm the Podcast microphones under Prepare before preparing or testing this session.')
    return studio.mic_plan if (mode or studio.mode) == 'local' else None


def template_key(studio, mode):
    plan = require_plan(studio, mode)
    return 'local:' + ','.join(map(str, plan['inputs'])) if plan else mode


def template_path(studio, mode):
    templates = studio.settings('templates') or {}
    if mode != 'local':
        return templates.get(mode)
    if not studio.mic_plan:
        return None
    key = template_key(studio, mode)
    # Preserve the existing three-mic template without claiming it fits smaller shows.
    return templates.get(key) or (templates.get('local') if studio.mic_plan['inputs'] == [1, 2, 3] else None)
