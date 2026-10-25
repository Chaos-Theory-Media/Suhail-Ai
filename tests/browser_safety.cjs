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
  }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  setAttribute(name, value) {this[name] = value;}
  append() {}
  replaceChildren() {}
  prepend() {}
  remove() {}
}

async function harness() {
  const nodes = new Map();
  let captures = 0, stops = 0, uploads = 0;
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
  return {ctx, stream, nodes, captures: () => captures, stops: () => stops, uploads: () => uploads};
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
