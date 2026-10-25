"""Own only Sawti-managed processes and capture streams; never touch DAW/Zoom/Focusrite."""
import os, shutil, subprocess, threading, time, urllib.request

class Lifecycle:
 def __init__(self, monitor):
  self.monitor=monitor
  self.lock=threading.RLock()
  self.on=False
  self.child=None
  self.mode='local'
  self.messages=[]

 def snapshot(self):
  with self.lock:
   return {'on':self.on,'mode':self.mode,'ollama_managed':bool(self.child and self.child.poll() is None),'messages':list(self.messages),'meter_running':self.monitor.snapshot()['running']}

 def start(self,mode):
  if mode not in ('local','zoom'):raise ValueError('Invalid operating mode')
  with self.lock:
   if self.on:
    return self.snapshot()
   self.on=True;self.mode=mode;self.messages=[]
   # Dedicated local port prevents interference with an Ollama instance used by other apps.
   binary=os.path.expanduser('~/Library/Application Support/Sawti/runtime/Ollama.app/Contents/Resources/ollama')
   if not os.path.isfile(binary): binary=shutil.which('ollama')
   if binary:
    try:
     env=os.environ.copy();env['OLLAMA_HOST']='127.0.0.1:11439';env['OLLAMA_MODELS']=os.path.expanduser('~/Library/Application Support/Sawti/models')
     self.child=subprocess.Popen([binary,'serve'],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
     self.messages.append('Dedicated Sawti Ollama service started on port 11439. Qwen3 4B is installed by Sawti Setup.')
    except Exception as exc:self.messages.append('Ollama not started: '+str(exc))
   else:self.messages.append('Ollama not installed. Rule-based text diagnostics remain available.')
   # Metering is opt-in via the existing Start metering button. Never grab audio on activation.
   self.messages.append('Live microphone capture is OFF until operator requests Start metering.')
   return self.snapshot()

 def stop(self):
  with self.lock:
   # Prevent further work while releasing capture resources.
   self.on=False
   self.monitor.stop()
   if self.child is not None:
    child=self.child;self.child=None
    if child.poll() is None:
     child.terminate()
     try:child.wait(timeout=5)
     except subprocess.TimeoutExpired:
      child.kill();child.wait(timeout=3)
   self.messages=['Sawti audio capture stopped. Sawti-managed AI service stopped. Audition, Zoom, Scarlett, BlackHole and external Ollama are untouched.']
   return self.snapshot()
