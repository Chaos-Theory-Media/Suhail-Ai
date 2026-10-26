"""Read-only commissioning evidence. Observing controls never qualifies transport."""
import json
import platform
import subprocess

from . import applications, paths
from .agents import audition


def system_info():
    if platform.system() != 'Darwin':
        return dict(platform=platform.system(), macos_version=None, macos_build=None)
    def query(command):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
            return result.stdout.strip()[:160] if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None
    return dict(platform='Darwin', macos_version=query(['/usr/bin/sw_vers', '-productVersion']),
                macos_build=query(['/usr/bin/sw_vers', '-buildVersion']),
                cpu=query(['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string']),
                memory_bytes=query(['/usr/sbin/sysctl', '-n', 'hw.memsize']))


def report(studio):
    session = audition.today_session(studio, studio.mode)
    snap = studio.monitor.snapshot()
    blocks = []
    if studio.mode != 'local':
        blocks.append('Hands-free qualification currently targets Podcast; Zoom needs separate routing/privacy trials.')
    if not studio.mic_plan:
        blocks.append('Confirm 1–3 programme microphones; Mic 1 is presenter and input 4 is talkback only.')
    if not session:
        blocks.append('Prepare a session from the matching microphone template.')
    if not snap.get('running') or snap.get('stale'):
        blocks.append('Fresh microphone measurements are unavailable.')
    blocks += [
        'Active Audition session, input assignments, armed tracks and transport are not yet automatically verified.',
        'The Mic 1 hands-free listener, spoken responses and cancellable countdown are not implemented.',
        'The full recording workflow needs physical Mac qualification; simulation is insufficient.',
    ]
    def bundle(kind):
        found = applications.discover(kind) if not studio.audio.simulated else None
        return {k: found[k] for k in ('name', 'bundle_id', 'version', 'build')} if found else None
    return dict(schema=1, simulated=studio.audio.simulated, system=system_info(),
                applications=dict(audition=bundle('audition'), focusrite=bundle('focusrite')),
                microphone_plan=studio.mic_plan, session_prepared=bool(session),
                monitoring_fresh=bool(snap.get('running') and not snap.get('stale')),
                recording_state='unknown', full_autonomy_ready=False, blockers=blocks,
                routing_changed=False,
                note='Installed versions are observations, not evidence of automation compatibility.')


def inspect_audition(studio):
    if studio.audio.simulated:
        return dict(status='simulation', read_only=True, nodes=[], transport_state='unknown')
    if platform.system() != 'Darwin':
        raise RuntimeError('Audition control inspection must run on the Mac, not the cloud environment.')
    app = audition.find_app()
    if not app:
        raise RuntimeError('Adobe Audition was not found. Inspection does not launch applications.')
    try:
        result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript',
                                 str(paths.APP_ROOT / 'helpers/inspect-audition.js'), app['bundle_id']],
                                capture_output=True, text=True, timeout=20, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Read-only inspection timed out. No recording command was sent.') from exc
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:600] or 'macOS refused read-only Accessibility inspection.')
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError('The Mac returned an unreadable control inspection result.') from exc
    if (not isinstance(data, dict) or data.get('status') not in ('observed', 'not_running', 'unavailable')
            or not isinstance(data.get('nodes'), list) or len(data['nodes']) > 200):
        raise RuntimeError('The Mac returned an invalid control inspection result.')
    data.update(read_only=True, transport_state='unknown', qualified_for_recording=False)
    return data
