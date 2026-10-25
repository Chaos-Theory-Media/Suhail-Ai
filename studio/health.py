"""Read-only status observations. Hardware controls not readable via CoreAudio are marked unverified."""
import os, subprocess, time
from pathlib import Path
from studio.engine import select_device, profile

def processes():
    try:
        # macOS process list. No Accessibility permission or UI automation needed.
        out=subprocess.run(['/bin/ps','-axo','comm='],capture_output=True,text=True,timeout=3,check=True).stdout
        return [x.strip().lower() for x in out.splitlines()]
    except Exception:return []

def running(names,procs):return any(any(n in line for n in names) for line in procs)

def audit(mode,ds,meter,procs=None):
    if mode not in ('local','zoom'):raise ValueError('Invalid mode')
    procs=processes() if procs is None else procs
    result=[]
    def add(code,severity,message,detail):result.append(dict(code=code,severity=severity,message=message,detail=detail))
    scarlett=next((d for d in ds if 'scarlett' in d['name'].lower() and d['inputs']>=4),None)
    if scarlett is None:add('SCARLETT_MISSING','critical','Scarlett audio interface not detected','Check USB connection and power. No automatic re-routing attempted.')
    target=select_device(ds,profile(mode))
    if target is None:add('CAPTURE_DEVICE_MISSING','critical','Recording capture device not found','Check the selected local / Zoom profile and input-channel count.')
    if not running(['adobe audition','adobeaudition'],procs):add('AUDITION_NOT_RUNNING','warning','Adobe Audition is not running','Open Audition and verify the recording session. Process detection cannot prove application responsiveness.')
    if mode=='zoom':
        if not any('blackhole' in d['name'].lower() for d in ds):add('BLACKHOLE_MISSING','critical','BlackHole is not detected','Check the virtual driver and Audio MIDI Setup.')
        if not running(['/zoom.us','/zoom workplace','/zoom.app','zoom.us.app'],procs):add('ZOOM_NOT_RUNNING','warning','Zoom is not detected','Open Zoom and confirm microphone and speaker assignments.')
        add('ZOOM_SELECTION_UNVERIFIED','manual','Zoom audio device selection not verified','This version cannot read the chosen Zoom microphone/speaker device. Check BlackHole Multi-Output routing manually.')
    if not meter.get('running'):
        add('METER_OFF','warning','Input meter is not running','Start metering for signal checks.')
    elif meter.get('last_audio_age') is None or meter['last_audio_age']>4:
        add('METER_STALLED','critical','Audio meter has stopped receiving samples','Possible audio-device disconnection or capture interruption.')
    else:
        for c in meter.get('channels',[]):
            if c['clip']:add('CLIP_'+str(c['channel']),'critical',c['label']+' clipping','Check input preamp/source level. Agent does not adjust analogue gain.')
        # A transient quiet channel is not proof of muted audio or zero gain.
    add('PHANTOM_UNVERIFIED','manual','Phantom power cannot be verified','CoreAudio does not reliably expose this Scarlett hardware setting. Check 48V on the interface for microphones that require it.')
    add('GAIN_UNVERIFIED','manual','Analogue gain knob positions cannot be verified','A quiet input could mean no speech, a disconnected cable, or low gain. Ask each participant for an active microphone test.')
    add('AUDITION_RESPONSE_UNVERIFIED','manual','Audition responsiveness is not verified','Process presence alone is not a heartbeat. Operator should verify the Audition interface and a test recording.')
    add('ROUTING_UNVERIFIED','manual','Physical talkback isolation not verified','Confirm Input 4 is heard in the headphones but absent from recording and Zoom send.')
    return {'mode':mode,'checked_at':time.time(),'alerts':result,'counts':{s:sum(a['severity']==s for a in result) for s in ('critical','warning','manual')},'read_only':True}
