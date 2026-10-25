// Executes the original inline UI script with test doubles. No real microphone,
// browser permissions, network or audio hardware is used.
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const html = readFileSync(resolve(__dirname, '../../static/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

async function harness() {
  const elements = new Map();
  let captures = 0, stopped = 0;
  const stream = {getTracks: () => [{stop: () => { stopped++; }}]};
  const context = vm.createContext({
    document: {querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, {
        classList: {toggle() {}}, style: {}, textContent: '', innerHTML: '', value: ''
      });
      return elements.get(selector);
    }},
    setInterval() {},
    fetch: async () => ({ok: true, json: async () => ({on: false})}),
    navigator: {mediaDevices: {getUserMedia: async () => {captures++; return stream;}}},
    MediaRecorder: class {
      static isTypeSupported() {return true;}
      start() {this.state = 'recording';}
      stop() {this.state = 'inactive';}
    }
  });
  vm.runInContext(script, context);
  await vm.runInContext('syncPower()', context);
  return {context, stream, captures: () => captures, stopped: () => stopped};
}

test('OFF prevents browser microphone acquisition', async () => {
  const h = await harness();
  await vm.runInContext("toggleVoice('command')", h.context);
  assert.equal(h.captures(), 0, 'OFF UI still invokes getUserMedia');
});

test('OFF cancels microphone permission requests already pending', async () => {
  const h = await harness();
  let grant;
  h.context.navigator.mediaDevices.getUserMedia = () => new Promise(resolve => {grant = resolve;});
  vm.runInContext('powerOn = true', h.context);
  const pending = vm.runInContext("beginAudio('command')", h.context);
  await vm.runInContext("$('#powerBtn').onclick()", h.context);
  grant(h.stream);
  await pending;
  assert.equal(vm.runInContext('recorder?.state', h.context), 'inactive',
    'Late permission grant starts recording after OFF');
  assert.equal(h.stopped(), 1, 'Microphone tracks must be released');
});
