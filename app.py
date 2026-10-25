from flask import Flask,jsonify,request,send_from_directory
from studio.engine import Monitor,devices,profile,preflight
from studio.lifecycle import Lifecycle
from studio.health import audit
from studio.learning import configure,scan,summary
from sawti import people,enrol_name,remove_person,enrol_voice,identify,transcribe,ollama_status,agent_status,respond,log
app=Flask(__name__,static_folder='static',static_url_path='')
app.config['MAX_CONTENT_LENGTH']=5*1024*1024
monitor=Monitor()
lifecycle=Lifecycle(monitor)

@app.get('/api/power')
def power_status():return jsonify(lifecycle.snapshot())
@app.post('/api/power/on')
def power_on():
 mode=(request.get_json(silent=True) or {}).get('mode','local')
 try:return jsonify(lifecycle.start(mode))
 except ValueError as exc:return jsonify(error=str(exc)),400
@app.post('/api/power/off')
def power_off():return jsonify(lifecycle.stop())

@app.before_request
def reject_while_off():
 if request.path.startswith('/api/') and request.path not in ('/api/power','/api/power/on','/api/power/off') and not lifecycle.on:
  return jsonify(error='Sawti is OFF. Switch ON to run agents and use microphones.'),503

def getdevices():
 try:return devices()
 except Exception:return []
@app.get('/')
def index():return send_from_directory('static','index.html')
@app.get('/api/status')
def status():return jsonify(monitor.snapshot())
@app.get('/api/devices')
def dev():return jsonify(getdevices())
@app.get('/api/agents/<mode>')
def agents(mode):
 if mode not in ('local','zoom'):return jsonify(error='Invalid mode'),400
 return jsonify(checks=agent_status(mode,getdevices(),monitor.snapshot(),{}),ollama=ollama_status())
@app.get('/api/profile/<mode>')
def prof(mode):
 try:return jsonify(profile(mode))
 except ValueError:return jsonify(error='Invalid mode'),400
@app.post('/api/meter/start')
def start():
 mode=(request.get_json(silent=True) or {}).get('mode','')
 if mode not in ('local','zoom'):return jsonify(error='Invalid mode'),400
 ok=monitor.start(mode);return jsonify(ok=ok,status=monitor.snapshot()),200 if ok else 422
@app.post('/api/meter/stop')
def stop():monitor.stop();return jsonify(ok=True)
@app.get('/api/preflight/<mode>')
def pre(mode):
 if mode not in ('local','zoom'):return jsonify(error='Invalid mode'),400
 return jsonify(preflight(mode,getdevices(),monitor.snapshot()))
@app.get('/api/learning')
def learning():return jsonify(summary())
@app.post('/api/learning/configure')
def learnconfig():
 d=request.get_json(silent=True) or {}
 try:return jsonify(configure(d.get('folder',''),bool(d.get('enabled',False))))
 except (ValueError,OSError) as e:return jsonify(error=str(e)),400
@app.post('/api/learning/scan')
def learnscan():return jsonify(scan())
@app.get('/api/presenters')
def presenters():return jsonify(people=people())
@app.post('/api/presenters')
def createpresenter():
 d=request.get_json(silent=True) or {}
 try:enrol_name(d.get('name',''),d.get('consent') is True);return jsonify(people=people())
 except ValueError as e:return jsonify(error=str(e)),400
@app.delete('/api/presenters/<name>')
def deletepresenter(name):remove_person(name);return jsonify(people=people())
@app.post('/api/presenters/voice')
def voiceenrol():
 name=request.form.get('name','');f=request.files.get('audio')
 if not f:return jsonify(error='No audio provided'),400
 try:enrol_voice(name,f.read());return jsonify(ok=True)
 except Exception as e:return jsonify(error=str(e)),422
@app.post('/api/voice')
def voice():
 mode=request.form.get('mode','local');f=request.files.get('audio')
 if not f:return jsonify(error='No audio'),400
 audio=f.read()
 try:
  text=transcribe(audio,request.form.get('language'))
  try:speaker=identify(audio)
  except Exception:speaker={'name':None,'verified':False}
  ctx={'checks':agent_status(mode,getdevices(),monitor.snapshot(),{})}
  ans=respond(text,mode,ctx)
  return jsonify(text=text,speaker=speaker,**ans)
 except Exception as e:return jsonify(error=str(e)),422
@app.post('/api/chat')
def chat():
 d=request.get_json(silent=True) or {};mode=d.get('mode','local')
 if mode not in ('local','zoom'):return jsonify(error='Invalid mode'),400
 text=(d.get('message') or '').strip()[:2000]
 if not text:return jsonify(error='Empty message'),400
 ctx={'checks':agent_status(mode,getdevices(),monitor.snapshot(),{}),'mode':mode}
 log('prompt',text[:200]);return jsonify(respond(text,mode,ctx))
if __name__=='__main__':
 print('Sawti 2.0: http://127.0.0.1:8765');app.run(host='127.0.0.1',port=8765,debug=False,threaded=True)
