// Executes the actual UI script. DOM/media/network are substitutes, not a claim
// of Safari or macOS permission qualification.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const source = readFileSync(resolve(__dirname, '../static/app.js'), 'utf8');

class Element {
  constructor() {
    this.style = {}; this.dataset = {}; this.value = ''; this.listeners = {};
    this.classList = {toggle() {}};
    const classes = new Set();
    this.classList = {toggle(name, on) {
      if (on === undefined) on = !classes.has(name);
      if (on) classes.add(name); else classes.delete(name);
    }, contains: name => classes.has(name)};
  }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  setAttribute(name, value) {this[name] = value;}
  append() {}
  replaceChildren(...children) {this.children = children;}
  prepend() {}
  remove() {}
}

async function harness() {
  const nodes = new Map();
  let captures = 0, stops = 0, uploads = 0;
  const requests = [];
  const track = {stop: () => {stops++;}};
  const stream = {getTracks: () => [track]};
  const ctx = vm.createContext({
    Node: Element,
    document: {
      querySelector(s) {if (!nodes.has(s)) nodes.set(s, new Element()); return nodes.get(s);},
      querySelectorAll() {return [];},
      createElement() {return new Element();},
      createTextNode(text) {return text;},
      body: new Element()
    },
    window: new Element(),
    setInterval() {}, setTimeout() {return 1;}, clearTimeout() {},
    fetch: async (url, opts) => {
      requests.push({url, opts});
      if (url.includes('/voice')) uploads++;
      return {ok: true, json: async () => ({on: false, mode: 'local', notices: [], voice: {}})};
    },
    navigator: {mediaDevices: {getUserMedia: async () => {captures++; return stream;}}},
    MediaRecorder: class {
      static isTypeSupported() {return true;}
      constructor() {this.mimeType = 'audio/webm'; this.state = 'inactive';}
      start() {this.state = 'recording';}
      stop() {this.state = 'inactive'; Promise.resolve().then(() => this.onstop?.());}
    },
    Blob: class {}, FormData: class {append() {}}
  });
  vm.runInContext(source, ctx);
  await new Promise(resolve => setImmediate(resolve));
  return {ctx, stream, nodes, requests, captures: () => captures, stops: () => stops, uploads: () => uploads};
}

test('OFF never asks for microphone access', async () => {
  const h = await harness();
  await vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  assert.equal(h.captures(), 0);
});

test('simulation never asks for a real microphone', async () => {
  const h = await harness();
  vm.runInContext('S.on = true; S.simulated = true', h.ctx);
  await vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  assert.equal(h.captures(), 0);
});

test('OFF releases active browser capture and discards its upload', async () => {
  const h = await harness();
  vm.runInContext('S.on = true', h.ctx);
  await vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  assert.equal(vm.runInContext('recorder.state', h.ctx), 'recording');
  vm.runInContext("renderPower({on: false, mode:'local', notices: []})", h.ctx);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.stops() >= 1);
  assert.equal(h.uploads(), 0);
  assert.equal(vm.runInContext('recorder', h.ctx), null);
});

test('late permission grant after OFF releases tracks without starting capture', async () => {
  const h = await harness();
  let grant;
  h.ctx.navigator.mediaDevices.getUserMedia = () => new Promise(resolve => {grant = resolve;});
  vm.runInContext('S.on = true', h.ctx);
  const pending = vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  vm.runInContext("renderPower({on: false, mode:'local', notices: []})", h.ctx);
  grant(h.stream);
  await pending;
  assert.equal(h.stops(), 1);
  assert.equal(vm.runInContext('recorder', h.ctx), null);
});

test('recorder construction failure releases the acquired microphone', async () => {
  const h = await harness();
  h.ctx.MediaRecorder = class {
    static isTypeSupported() {return true;}
    constructor() {throw new Error('Unsupported MIME');}
  };
  vm.runInContext('S.on = true', h.ctx);
  await vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  assert.equal(h.stops(), 1);
});

test('server OFF from another client stops this tab after status sync', async () => {
  const h = await harness();
  vm.runInContext('S.on = true', h.ctx);
  await vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  h.ctx.fetch = async (url) => ({ok: url === '/api/power', status: 503,
    json: async () => url === '/api/power' ? {on: false, mode: 'local', notices: []} : {error: 'OFF'}});
  await vm.runInContext('pollStatus()', h.ctx);
  assert.equal(vm.runInContext('S.on', h.ctx), false);
  assert.ok(h.stops() >= 1);
});

test('a delayed status response cannot re-enable UI after local OFF', async () => {
  const h = await harness();
  let reply;
  vm.runInContext('S.on = true', h.ctx);
  h.ctx.fetch = async () => new Promise(resolve => {reply = resolve;});
  const pending = vm.runInContext('pollStatus()', h.ctx);
  vm.runInContext("renderPower({on:false, mode:'local', notices:[]})", h.ctx);
  reply({ok: true, json: async () => ({studio: {on: true, mode: 'local'}, meter: {running: false}})});
  await pending;
  assert.equal(vm.runInContext('S.on', h.ctx), false);
});

test('status polling preserves an unconfirmed microphone choice', async () => {
  const h = await harness();
  vm.runInContext("renderPower({on:true, mode:'local', power_epoch:0, notices:[], microphone_plan:null})", h.ctx);
  h.nodes.get('#podcastMics').value = '1,3';
  for (let i = 0; i < 3; i++)
    vm.runInContext("renderPower({on:true, mode:'local', power_epoch:0, notices:[], microphone_plan:null})", h.ctx);
  assert.equal(h.nodes.get('#podcastMics').value, '1,3');
});

test('loading an existing confirmed plan populates the microphone selector', async () => {
  const h = await harness();
  vm.runInContext("renderPower({on:true, mode:'local', notices:[], microphone_plan:{id:'confirmed', inputs:[1,2]}})", h.ctx);
  assert.equal(h.nodes.get('#podcastMics').value, '1,2');
});

test('polling the same confirmed plan preserves a pending replacement choice', async () => {
  const h = await harness();
  const render = "renderPower({on:true, mode:'local', notices:[], microphone_plan:{id:'confirmed', inputs:[1,2]}})";
  vm.runInContext(render, h.ctx);
  h.nodes.get('#podcastMics').value = '1';
  vm.runInContext(render, h.ctx);
  assert.equal(h.nodes.get('#podcastMics').value, '1');
});

test('a new plan from another tab replaces a stale microphone draft', async () => {
  const h = await harness();
  vm.runInContext("renderPower({on:true, mode:'local', notices:[], microphone_plan:{id:'old', inputs:[1,2]}})", h.ctx);
  h.nodes.get('#podcastMics').value = '1';
  vm.runInContext("renderPower({on:true, mode:'local', notices:[], microphone_plan:{id:'new', inputs:[1,3]}})", h.ctx);
  assert.equal(h.nodes.get('#podcastMics').value, '1,3');
});

test('OFF, mode changes and a missed power cycle clear the microphone draft', async () => {
  for (const transition of [
    "{on:false, mode:'local', power_epoch:1, notices:[]}",
    "{on:true, mode:'zoom', power_epoch:0, notices:[]}",
    "{on:true, mode:'local', power_epoch:1, notices:[]}"
  ]) {
    const h = await harness();
    vm.runInContext("renderPower({on:true, mode:'local', power_epoch:0, notices:[]})", h.ctx);
    h.nodes.get('#podcastMics').value = '1,2,3';
    vm.runInContext(`renderPower(${transition})`, h.ctx);
    assert.equal(h.nodes.get('#podcastMics').value, '');
  }
});

test('confirmation sends the chosen inputs and ignores an older pending status response', async () => {
  const h = await harness();
  vm.runInContext("renderPower({on:true, mode:'local', power_epoch:0, notices:[]})", h.ctx);
  h.nodes.get('#podcastMics').value = '1,3';
  let replyStatus;
  const posts = [];
  h.ctx.fetch = async (url, opts) => {
    if (url === '/api/status') return new Promise(resolve => {replyStatus = resolve;});
    if (url === '/api/podcast/microphones') {
      posts.push(JSON.parse(opts.body));
      return {ok: true, json: async () => ({plan: {id: 'accepted', inputs: [1,3]}, message: 'Confirmed'})};
    }
    return {ok: true, json: async () => ({findings: [], steps: [], active: false})};
  };
  const oldPoll = vm.runInContext('pollStatus()', h.ctx);
  const confirmation = h.nodes.get('#confirmPodcastMics').listeners.click();
  h.nodes.get('#confirmYes').onclick();
  await confirmation;
  replyStatus({ok:true, json:async () => ({studio:{on:true, mode:'local', power_epoch:0, notices:[]}, meter:{running:false}})});
  await oldPoll;
  assert.deepEqual(posts, [{inputs:[1,3], studio_idle:true}]);
  assert.equal(h.nodes.get('#podcastMics').value, '1,3');
  assert.equal(vm.runInContext('S.micPlanId', h.ctx), 'accepted');
});

test('OFF during the confirmation dialog prevents a microphone submission', async () => {
  const h = await harness();
  vm.runInContext("renderPower({on:true, mode:'local', power_epoch:0, notices:[]})", h.ctx);
  h.nodes.get('#podcastMics').value = '1';
  const posts = [];
  h.ctx.fetch = async url => {posts.push(url); return {ok:true, json:async () => ({})};};
  const confirmation = h.nodes.get('#confirmPodcastMics').listeners.click();
  vm.runInContext("renderPower({on:false, mode:'local', power_epoch:1, notices:[]})", h.ctx);
  h.nodes.get('#confirmYes').onclick();
  await confirmation;
  assert.deepEqual(posts, []);
});

test('startup has no private audio request or browser playback', async () => {
  const h = await harness();
  assert.equal(h.requests.filter(r => /presenter-speech\/(speak|test|enable)/.test(r.url)).length, 0);
  assert.equal(h.captures(), 0);
});

test('character mouth follows reported speaking state and stops on OFF', async () => {
  const h = await harness();
  vm.runInContext("renderPower({on:true, mode:'local', presenter_speech:{enabled:true, phase:'speaking', caption:'Hello'}})", h.ctx);
  assert.equal(h.nodes.get('#sawtiCharacter').classList.contains('speaking'), true);
  assert.equal(h.nodes.get('#sawtiCaption').textContent, 'Hello');
  vm.runInContext("renderPower({on:false, mode:'local'})", h.ctx);
  assert.equal(h.nodes.get('#sawtiCharacter').classList.contains('speaking'), false);
  assert.equal(vm.runInContext('S.presenterSpeech.enabled', h.ctx), false);
});

test('uncommissioned or simulated replies never request presenter playback', async () => {
  const h = await harness();
  vm.runInContext('S.on = true', h.ctx);
  await vm.runInContext("sayToPresenter('Hello')", h.ctx);
  vm.runInContext("S.simulated = true; S.presenterSpeech.enabled = true", h.ctx);
  await vm.runInContext("sayToPresenter('Hello')", h.ctx);
  assert.equal(h.requests.filter(r => r.url === '/api/presenter-speech/speak').length, 0);
});

test('browser microphone cannot listen while private speech is preparing or speaking', async () => {
  const h = await harness();
  vm.runInContext("S.on = true; S.presenterSpeech = {enabled:true, phase:'speaking'}", h.ctx);
  await vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  assert.equal(h.captures(), 0);
});

test('microphone cannot race a private speech request before its response arrives', async () => {
  const h = await harness();
  vm.runInContext("S.on = true; S.presenterSpeech = {enabled:true, phase:'ready'}", h.ctx);
  let reply;
  h.ctx.fetch = async () => new Promise(resolve => {reply = resolve;});
  const speaking = vm.runInContext("sayToPresenter('Hello presenter')", h.ctx);
  await vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  assert.equal(h.captures(), 0);
  reply({ok:true, json:async () => ({started:true, state:{enabled:true, phase:'preparing'}})});
  await speaking;
});

test('unknown private speech state blocks browser capture without pretending it is muted', async () => {
  const h = await harness();
  vm.runInContext("S.on = true; renderPresenterSpeech({enabled:false, phase:'unknown'})", h.ctx);
  await vm.runInContext("recordVoice('/api/voice', false)", h.ctx);
  assert.equal(h.captures(), 0);
  assert.match(h.nodes.get('#presenterSpeechState').textContent, /state unavailable/);
});

test('page close requests only Sawti speech mute with the local protection header', async () => {
  const h = await harness();
  vm.runInContext("S.on = true; S.presenterSpeech = {enabled:true, phase:'speaking'}", h.ctx);
  h.ctx.window.listeners.pagehide();
  const requests = h.requests.filter(r => r.url === '/api/presenter-speech/mute');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].opts.headers['X-Sawti'], '1');
  assert.equal(requests[0].opts.keepalive, true);
  assert.equal(vm.runInContext('S.presenterSpeech.enabled', h.ctx), false);
});

test('model status remains readable while OFF without starting services or microphones', async () => {
  const h = await harness();
  await vm.runInContext("api('/api/models')", h.ctx);
  assert.equal(h.requests.at(-1).url, '/api/models');
  assert.equal(h.requests.at(-1).opts.method, 'GET');
  assert.equal(h.captures(), 0);
  assert.equal(h.requests.filter(r => r.url === '/api/power/on').length, 0);
});

test('manual uploads preserve multipart encoding and carry the local write header', async () => {
  const h = await harness();
  vm.runInContext('S.on = true', h.ctx);
  await vm.runInContext("api('/api/knowledge/import', {form: new FormData()})", h.ctx);
  const request = h.requests.at(-1);
  assert.equal(request.opts.headers['X-Sawti'], '1');
  assert.equal(request.opts.headers['Content-Type'], undefined);
  assert.ok(request.opts.body);
});

test('template search lists saved files without adopting or launching them', async () => {
  const h = await harness();
  vm.runInContext("S.on=true; S.micContext='true:local:1'; S.micPlanId='two-mics'", h.ctx);
  const calls = [];
  h.ctx.fetch = async (url, opts) => {
    calls.push(url);
    return {ok:true, json:async () => ({files:[{id:'one',name:'Two people.sesx',folder:'/Documents/Templates'}], warnings:[],limited:false})};
  };
  await h.nodes.get('#findTemplates').listeners.click();
  assert.match(h.nodes.get('#templateChoice').children[1].textContent, /Two people.sesx.*Documents/);
  assert.deepEqual(calls, ['/api/audition/templates/search']);
  assert.equal(h.nodes.get('#useTemplateChoice').disabled, true);
});

test('template inspection requires a fresh empty-template acknowledgement before adoption', async () => {
  const h = await harness();
  vm.runInContext("S.on=true; S.micContext='true:local:1'; S.micPlanId='two-mics'", h.ctx);
  h.nodes.get('#templateChoice').value = 'one';
  h.ctx.fetch = async () => ({ok:true,json:async () => ({matches_plan:true,template:{tracks:[{name:'Presenter',armed:true},{name:'Guest',armed:true}],sample_rate:48000,contains_media:false,sha256:'a'.repeat(64)}})});
  await h.nodes.get('#templateChoice').listeners.change();
  assert.match(h.nodes.get('#templatePreview').textContent, /2 audio track/);
  assert.equal(h.nodes.get('#useTemplateChoice').disabled, true);
  h.nodes.get('#templateEmpty').checked = true;
  h.nodes.get('#templateEmpty').listeners.change();
  assert.equal(h.nodes.get('#useTemplateChoice').disabled, false);
  assert.equal(h.captures(), 0);
});

test('recorded-session preview cannot enable template adoption', async () => {
  const h = await harness();
  vm.runInContext("S.on=true; S.micContext='true:local:1'; S.micPlanId='two-mics'", h.ctx);
  h.nodes.get('#templateChoice').value = 'recorded';
  h.ctx.fetch = async () => ({ok:true,json:async () => ({matches_plan:true,template:{tracks:[{name:'Presenter',armed:true},{name:'Guest',armed:true}],sample_rate:48000,contains_media:true,sha256:'a'.repeat(64)}})});
  await h.nodes.get('#templateChoice').listeners.change();
  h.nodes.get('#templateEmpty').checked = true;
  h.nodes.get('#templateEmpty').listeners.change();
  assert.equal(h.nodes.get('#useTemplateChoice').disabled, true);
  assert.match(h.nodes.get('#templatePreview').textContent, /Contains clips/);
});

test('late template inspection is discarded after microphone context changes', async () => {
  const h = await harness();
  vm.runInContext("S.on=true; S.micContext='true:local:1'; S.micPlanId='old-plan'", h.ctx);
  h.nodes.get('#templateChoice').value = 'one';
  let finish;
  h.ctx.fetch = async () => new Promise(resolve => {finish=resolve;});
  const pending = h.nodes.get('#templateChoice').listeners.change();
  vm.runInContext("S.micPlanId='new-plan'; resetTemplateChoices()", h.ctx);
  finish({ok:true,json:async () => ({matches_plan:true,template:{tracks:[],sample_rate:48000,contains_media:false,sha256:'a'.repeat(64)}})});
  await pending;
  assert.equal(h.nodes.get('#templatePreview').hidden, true);
  assert.equal(h.nodes.get('#useTemplateChoice').disabled, true);
  assert.equal(vm.runInContext('templateSelection', h.ctx), null);
});

test('ordinary status polling preserves a pending saved-template choice', async () => {
  const h = await harness();
  const state="{on:true,mode:'local',power_epoch:1,microphone_plan:{id:'two-mics',inputs:[1,2]},notices:[]}";
  vm.runInContext(`renderPower(${state})`, h.ctx);
  h.nodes.get('#templateChoice').value = 'selected';
  vm.runInContext(`renderPower(${state})`, h.ctx);
  assert.equal(h.nodes.get('#templateChoice').value, 'selected');
});
