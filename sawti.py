"""Sawti 2.0. Local orchestration only. Audio routing is never changed."""
import json,sqlite3,time,urllib.request,urllib.error,re,subprocess,sys,tempfile,os
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
DATA=Path.home()/"Library"/"Application Support"/"Sawti"
DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/"sawti.sqlite3"
MODEL=os.environ.get("SAWTI_MODEL","qwen3:4b")

def connect():
 c=sqlite3.connect(DB);c.execute("create table if not exists people(id integer primary key, name text unique not null, consent integer not null default 0, embedding text, created integer)");c.execute("create table if not exists events(id integer primary key, date integer, category text, message text)");c.commit();return c

def log(category,message):
 with connect() as db:db.execute("insert into events(date,category,message) values(?,?,?)",(int(time.time()),category,message[:500]))

def people():
 with connect() as db:return [dict(id=x[0],name=x[1],enrolled=bool(x[2] and x[3])) for x in db.execute('select id,name,consent,embedding from people order by name')]

def enrol_name(name,consent):
 name=' '.join(name.strip().split())
 if not (1<=len(name)<=80) or not consent:raise ValueError('Provide a presenter name and explicit voice-consent confirmation')
 with connect() as db:db.execute('insert into people(name,consent,created) values(?,?,?) on conflict(name) do update set consent=excluded.consent',(name,1,int(time.time())))
 log('presenter','Presenter profile registered: '+name)

def remove_person(name):
 with connect() as db:db.execute('delete from people where name=?',(name,))
 log('presenter','Presenter profile deleted')

def as_wav(audio):
 """Convert browser-encoded speech into mono 16 kHz PCM using local ffmpeg."""
 import shutil
 if not shutil.which('ffmpeg'):
  raise RuntimeError('ffmpeg is required for browser voice messages. Install with brew install ffmpeg')
 with tempfile.TemporaryDirectory() as folder:
  source=Path(folder)/'sample.audio';target=Path(folder)/'sample.wav'
  source.write_bytes(audio)
  result=subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(source),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(target)],capture_output=True,timeout=40)
  if result.returncode!=0 or not target.exists():raise ValueError('Audio conversion failed; please check microphone permissions and ffmpeg')
  return target.read_bytes()

def voice_embed(audio):
 try:
  from resemblyzer import VoiceEncoder,preprocess_wav
  import soundfile as sf
 except ImportError:raise RuntimeError('Voice verification option not installed. pip install -r requirements-voice.txt')
 with tempfile.NamedTemporaryFile(suffix='.wav',delete=False) as tmp:path=tmp.name
 try:
  Path(path).write_bytes(as_wav(audio))
  wav=preprocess_wav(Path(path))
  if len(wav)<16000*4:raise ValueError('Provide at least 4 seconds of clear presenter speech')
  return VoiceEncoder().embed_utterance(wav).tolist()
 finally:Path(path).unlink(missing_ok=True)

def enrol_voice(name,audio):
 vector=voice_embed(audio)
 with connect() as db:
  cur=db.execute('update people set embedding=? where name=? and consent=1',(json.dumps(vector),name))
  if cur.rowcount==0:raise ValueError('Register presenter with consent first')
 log('presenter','Voice profile enrolled for '+name)

def identify(audio):
 v=np.array(voice_embed(audio));matches=[]
 with connect() as db:
  for name,emb in db.execute('select name,embedding from people where consent=1 and embedding is not null'):
   a=np.array(json.loads(emb));sim=float(np.dot(a,v)/(np.linalg.norm(a)*np.linalg.norm(v)+1e-9));matches.append((sim,name))
 matches.sort(reverse=True)
 # Conservative provisional threshold, requires site calibration; do not use as authentication.
 if not matches or matches[0][0]<0.79 or (len(matches)>1 and matches[0][0]-matches[1][0]<0.06):return dict(name=None,confidence=matches[0][0] if matches else None,verified=False)
 return dict(name=matches[0][1],confidence=round(matches[0][0],3),verified=False)

def transcribe(audio,language=None):
 try:from faster_whisper import WhisperModel
 except ImportError:raise RuntimeError('Offline transcription not installed. pip install -r requirements-voice.txt')
 model=WhisperModel(os.environ.get('SAWTI_WHISPER','small'),device='cpu',compute_type='int8')
 with tempfile.NamedTemporaryFile(suffix='.wav',delete=False) as f:path=f.name
 try:
  Path(path).write_bytes(as_wav(audio))
  segs,_=model.transcribe(path,language=language if language in ('en','ar') else None,vad_filter=True)
  return ' '.join(s.text.strip() for s in segs).strip()
 finally:Path(path).unlink(missing_ok=True)

def ollama_status():
 try:
  with urllib.request.urlopen('http://127.0.0.1:11439/api/tags',timeout=1.6) as f:
   models=json.load(f).get('models',[])
  return {'running':True,'model':MODEL,'available':any(x.get('name','').split(':')[0]==MODEL.split(':')[0] for x in models)}
 except Exception:return {'running':False,'model':MODEL,'available':False}

def llm_reply(question,context):
 status=ollama_status()
 if not(status['running'] and status['available']):return None
 system='You are Sawti, a local studio operator assistant. Be concise and practical. Use only diagnostic facts provided. Never claim hardware settings have been read when they are not. No actions to change routing, gains, recording or devices are authorised. You may suggest human checks. Answer in the language of the user.'
 body=json.dumps({'model':MODEL,'stream':False,'messages':[{'role':'system','content':system},{'role':'user','content':'Status: '+json.dumps(context)[:6000]+'\nPresenter: '+question}]},ensure_ascii=False).encode()
 req=urllib.request.Request('http://127.0.0.1:11439/api/chat',data=body,headers={'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=50) as f:return json.load(f).get('message',{}).get('content','')
 except Exception:return None

def agent_status(mode,devices,meter,health):
 # Each agent produces an inspection result, not an action on equipment.
 names=[d.get('name','').lower() for d in devices]
 scarlett=any('scarlett' in n for n in names)
 blackhole=any('blackhole' in n for n in names)
 try:
  import psutil
  running=[(p.info.get('name') or '').lower() for p in psutil.process_iter(['name'])]
  audition=any('audition' in p for p in running);zoom=any('zoom' in p for p in running)
 except Exception:audition=zoom=None
 checks=[{'agent':'Hardware','label':'Scarlett attached','state':'pass' if scarlett else 'fail'},
         {'agent':'Capture','label':'Audio metering','state':'pass' if meter.get('running') else 'unknown'},
         {'agent':'Recording','label':'Audition process','state':'pass' if audition is True else 'fail' if audition is False else 'unknown'},
         {'agent':'Routing','label':'BlackHole available','state':'pass' if blackhole else 'fail'} if mode=='zoom' else {'agent':'Routing','label':'Three microphones assigned','state':'manual'},
         {'agent':'Remote','label':'Zoom process','state':'pass' if zoom is True else 'fail' if zoom is False else 'unknown'} if mode=='zoom' else {'agent':'Preflight','label':'Talkback isolated','state':'manual'},
         {'agent':'Recording','label':'Audition responsive','state':'manual'},
         {'agent':'Hardware','label':'Physical gain/48V','state':'manual'}]
 if isinstance(meter.get('channels'),list) and any(c.get('clip') for c in meter['channels']):checks.append({'agent':'Audio','label':'Input clipping','state':'fail'})
 return checks

def respond(text,mode,context):
 q=text.lower();checks=context.get('checks',[]);failed=[c for c in checks if c['state']=='fail']
 # Deterministic first-line actions; no arbitrary shell execution or dynamic tool calling.
 if any(x in q for x in ['ready','preflight','check studio','جاهز','افحص']):
  answer='Preflight: '+('; '.join(c['label']+' needs attention' for c in failed) if failed else 'no measured faults reported')+'. Manual checks remain necessary for gain, phantom power, track assignment and talkback isolation.'
 elif any(x in q for x in ['mic','microphone','مايك','ميكروفون','gain','silent','صوت']):answer='Ask the presenter to speak into the selected microphone. If its meter remains silent, first check the physical Scarlett gain knob and XLR cable, then check the correct 48V group if that microphone requires phantom power. Silence alone does not prove the knob is at zero.'
 elif any(x in q for x in ['zoom','blackhole','زوم']):answer='Verify Zoom speaker uses your validated Multi-Output Device, BlackHole is present, and Audition uses the validated Aggregate Device. Ask a remote guest to confirm mix-minus and that talkback is private.'
 elif any(x in q for x in ['record','تسجيل','save','folder','حفظ']):answer='Check Audition is running, its tracks are armed, and recording inputs match the selected profile. Record and replay a short test. Sawti does not press Record or change Audition routing in this release.'
 else:answer=None
 if answer is not None:return dict(reply=answer,source='rule',agents=checks)
 llm=llm_reply(text,context)
 return dict(reply=llm or 'I can check studio readiness, microphone silence, Zoom/BlackHole and recording setup. Install and download a local Ollama model for broader conversations.',source='ollama' if llm else 'rule',agents=checks)
