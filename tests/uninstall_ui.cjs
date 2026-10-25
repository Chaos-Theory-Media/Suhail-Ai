const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {spawnSync} = require('node:child_process');
const vm = require('node:vm');
const source = readFileSync(resolve(__dirname, '../helpers/uninstall-ui.js'), 'utf8');

function harness(options = {}) {
  const commands = [], alerts = [];
  const cancelled = () => {throw Object.assign(new Error('cancelled'), {errorNumber: -128});};
  const ui = {
    displayAlert(title, detail) {alerts.push({title, detail});},
    chooseFromList(items) {return options.cancelSelection ? false : items.slice(0, 3);},
    displayDialog(text, args) {
      if (args.withTitle === 'Uninstall Sawti') {
        if (options.cancel) return cancelled();
        return {buttonReturned: 'Studio idle — continue'};
      }
      if (args.withTitle === 'Review Sawti uninstall') return {buttonReturned: 'Move to Trash'};
      if (args.withTitle === 'Authorise virtual-device removal') return cancelled();
      return {buttonReturned: 'Close'};
    },
    doShellScript(command) {
      commands.push(command);
      if (command.includes('/usr/bin/find')) throw new Error('No private runtime');
      if (command.includes("'-I'")) {
        if (command.includes("'stop'")) return JSON.stringify(options.processError ? {error: 'Unverified process remains'} : {stopped: true});
        if (command.includes("'preview'")) return JSON.stringify({remove: ['/fake/private/model'], preserved: [], retained_devices: [], devices: options.devices ? [{name: 'Sawti device', uid: 'owned'}] : []});
        if (command.includes("'execute'")) return JSON.stringify({moved: [], preserved: [], retained_devices: [], removed_devices: [], errors: [], report: '/fake/report.json'});
      }
      if (command.includes(' -I -c ')) {
        if (options.noPython) throw new Error('Interpreter broken');
        return '';
      }
      if (command.includes('mktemp')) return '/tmp/sawti-uninstall.unit';
      return '';
    }
  };
  const context = vm.createContext({Application: {currentApplication: () => ui},
    ObjC: {import() {}, unwrap: x => x}, $: {NSHomeDirectory: () => '/fake'}});
  vm.runInContext(source, context);
  return {context, commands, alerts, invoke: () => vm.runInContext("run(['/fake/source'])", context)};
}

test('shell quoting preserves spaces, quotes and literal substitutions', () => {
  const h = harness();
  const input = "Studio's folder $(printf wrong) `printf wrong` \nArabic صوتي";
  h.context.value = input;
  const quoted = vm.runInContext('shellQuote(value)', h.context);
  const proc = spawnSync('/bin/sh', ['-c', "printf '%s' " + quoted], {encoding: 'utf8'});
  assert.equal(proc.status, 0);
  assert.equal(proc.stdout, input);
});

test('cancel before idle authorisation makes no stop or delete call', () => {
  const h = harness({cancel: true}); h.invoke();
  assert.equal(h.commands.some(s => s.includes("'stop'") || s.includes("'execute'")), false);
});

test('cancel component selection never removes files', () => {
  const h = harness({cancelSelection: true}); h.invoke();
  assert.equal(h.commands.some(s => s.includes("'execute'")), false);
});

test('unverified process stops native uninstall before file removal', () => {
  const h = harness({processError: true}); h.invoke();
  assert.equal(h.commands.some(s => s.includes("'execute'")), false);
  assert.match(h.alerts[0].detail.message, /Unverified process/);
});

test('missing interpreters fail without cleanup', () => {
  const h = harness({noPython: true}); h.invoke();
  assert.equal(h.commands.some(s => s.includes("'execute'")), false);
  assert.match(h.alerts[0].title, /could not start/);
});

test('device removal requires its separate native confirmation', () => {
  const h = harness({devices: true}); h.invoke();
  assert.equal(h.commands.some(s => s.includes("'execute'")), false);
});

test('reviewed normal flow calls the constrained cleanup engine', () => {
  const h = harness(); h.invoke();
  assert.equal(h.commands.filter(s => s.includes("'execute'")).length, 1);
  assert.equal(h.alerts.length, 0);
});
