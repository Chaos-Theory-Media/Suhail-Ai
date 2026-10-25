import json, math, re, shutil, subprocess, threading, time
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
PROFILE_DIR=BASE/'profiles'

def devices():
    import sounddevice as sd
    result=[]
    for i,d in enumerate(sd.query_devices()):
        result.append(dict(index=i,name=d['name'],inputs=d['max_input_channels'],outputs=d['max_output_channels'],default_rate=int(d['default_samplerate'])))
    return result

def profile(name):
    if name not in ('local','zoom'): raise ValueError('Unknown profile')
    return json.loads((PROFILE_DIR/(name+'.json')).read_text())

def select_device(items, profile_data):
    text=profile_data['meter_device_pattern']
    return next((d for d in items if d['inputs']>=profile_data['required_input_channels'] and re.search(text,d['name'],re.I)),None)

class Monitor:
    def __init__(self):
        self.lock=threading.RLock(); self.stream=None; self.active=None; self.error=None
        self.channels=[]; self.peaks=[]; self.rms=[]; self.holds=[]; self.last_sample=0
        self.selection='local'; self.sample_rate=None

    def stop(self):
        with self.lock:
            old=self.stream; self.stream=None; self.active=None
        if old:
            try: old.stop(); old.close()
            except Exception: pass

    def start(self, mode):
        self.stop(); p=profile(mode); self.selection=mode
        try:
            import numpy as np
            import sounddevice as sd
            ds=devices(); d=select_device(ds,p)
            if d is None: raise RuntimeError('No matching input device found. Select device pattern in profiles/%s.json.'%mode)
            channels=p['required_input_channels']; rate=int(d['default_rate'])
            labels={int(x['channel']):x['name'] for x in p['sources']}
            def callback(indata, frames, time_info, status):
                # Capture only. No writes to any audio device and no audio saved or transmitted.
                arr=indata.astype(np.float64,copy=False)
                peaks=np.max(np.abs(arr),axis=0)
                rms=np.sqrt(np.mean(arr*arr,axis=0))
                with self.lock:
                    self.peaks=[max(-120.,20*math.log10(max(float(x),1e-6))) for x in peaks]
                    self.rms=[max(-120.,20*math.log10(max(float(x),1e-6))) for x in rms]
                    self.holds=[max(pv,old-0.08) for pv,old in zip(self.peaks,self.holds)] if self.holds else list(self.peaks)
                    self.last_sample=time.monotonic()
                    if status:self.error=str(status)
            stream=sd.InputStream(device=d['index'],channels=channels,samplerate=rate,blocksize=1024,callback=callback,dtype='float32')
            stream.start()
            with self.lock:
                self.stream=stream; self.active=dict(device=d,channels=channels,labels=labels);self.sample_rate=rate
                self.peaks=[-120.]*channels;self.rms=[-120.]*channels;self.holds=[-120.]*channels;self.error=None
            return True
        except Exception as exc:
            with self.lock:self.error=str(exc)
            return False

    def snapshot(self):
        with self.lock:
            age=(time.monotonic()-self.last_sample) if self.last_sample else None
            channels=[]
            if self.active:
                for i in range(self.active['channels']):
                    channels.append(dict(channel=i+1,label=self.active['labels'].get(i+1,'Input '+str(i+1)),peak=round(self.peaks[i],1),rms=round(self.rms[i],1),hold=round(self.holds[i],1),clip=self.peaks[i]>=-0.3))
            return dict(running=self.stream is not None,device=self.active['device'] if self.active else None,sample_rate=self.sample_rate,channels=channels,error=self.error,last_audio_age=round(age,1) if age is not None else None)

def preflight(mode, ds, meter):
    p=profile(mode); checks=[]
    def add(label,status,detail):checks.append(dict(label=label,status=status,detail=detail))
    focus=next((d for d in ds if 'scarlett' in d['name'].lower() and d['inputs']>=4),None)
    add('Scarlett 18i8 visible','pass' if focus else 'fail',focus['name'] if focus else 'No Scarlett input device detected')
    target=select_device(ds,p)
    add('Capture input device available','pass' if target else 'fail',target['name'] if target else 'Required input device missing or insufficient channels')
    if mode=='zoom':
        black=any('blackhole' in d['name'].lower() for d in ds)
        add('BlackHole visible','pass' if black else 'fail','BlackHole device detected' if black else 'BlackHole is not listed')
        add('Aggregate channel order','manual','Verify actual Scarlett and BlackHole channel indices in Audio MIDI Setup')
        add('Zoom mix-minus and talkback isolation','manual','Have a remote guest confirm they hear no return or talkback')
    else:
        add('Mic 1–3 assignment','manual','Test each mic against its labelled meter and Audition track')
    add('Outputs 1–2 speakers; 3–4 headset amplifier','manual','Check physical output mapping in Focusrite Control 2; never auto-modified')
    add('Talkback excluded from recording','manual','Verify Input 4 is not armed and no programme/Zoom bus contains talkback')
    add('Audition recording and playback','manual','Record and listen to a 20–30 second test, check source files')
    add('48 kHz expected','pass' if target and target['default_rate']==48000 else 'warning','Device nominal default rate: '+str(target['default_rate'] if target else 'unknown')+' Hz; current operating rate not verified')
    add('Live metering','pass' if meter['running'] and meter['last_audio_age'] is not None and meter['last_audio_age']<3 else 'warning','Meter is running' if meter['running'] else 'Meter not started')
    add('Disk space','pass' if shutil.disk_usage(str(BASE)).free>5*1024**3 else 'warning','Available %.1f GB on application disk'%(shutil.disk_usage(str(BASE)).free/1024**3))
    return checks
