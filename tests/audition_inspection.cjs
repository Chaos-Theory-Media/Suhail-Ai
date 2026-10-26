// Exercise the actual JXA script with read-only Accessibility substitutes.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {readFileSync} = require('node:fs');
const source = readFileSync(require('node:path').resolve(__dirname, '../helpers/inspect-audition.js'), 'utf8');

function inspect(processes, bid = 'com.adobe.AdobeAudition') {
  let queries = 0;
  const context = vm.createContext({Application: name => {
    assert.equal(name, 'System Events');
    return {applicationProcesses: {whose: predicate => {
      queries++;
      assert.equal(predicate.bundleIdentifier, bid);
      return () => processes;
    }}};
  }});
  vm.runInContext(source, context);
  return {result: JSON.parse(vm.runInContext(`run(${JSON.stringify([bid])})`, context)), queries};
}
function node(children = []) {
  // Any unexpected action or attribute access (including text/value) fails.
  const fields = {role: () => 'AXButton', name: () => 'Record', description: () => 'Record', uiElements: () => children};
  return new Proxy(fields, {get(target, key) {
    assert.ok(key in target, `Unexpected Accessibility access: ${key}`);
    return target[key];
  }});
}

test('inspection reads controls without activating, typing, clicking or reading programme text', () => {
  const {result} = inspect([node([node()])]);
  assert.equal(result.status, 'observed');
  assert.equal(result.read_only, true);
  assert.equal(result.transport_state, 'unknown');
  assert.equal(result.nodes.length, 2);
  assert.equal(result.nodes[1].parent, 0);
});
test('absent Audition is reported without launching it', () => {
  assert.equal(inspect([]).result.status, 'not_running');
});
test('unexpected bundle ID is rejected before accessing System Events', () => {
  const {result, queries} = inspect([], 'com.other.Editor');
  assert.equal(result.status, 'unavailable');
  assert.equal(queries, 0);
});
test('permission failures remain unavailable rather than declaring success', () => {
  const process = node();
  process.uiElements = () => {throw new Error('Accessibility permission denied');};
  const {result} = inspect([process]);
  assert.equal(result.status, 'unavailable');
  assert.match(result.error, /permission denied/);
});
test('wide and deep trees remain bounded and explicitly truncated', () => {
  let branch = node();
  for (let i = 0; i < 9; i++) branch = node(Array(45).fill(branch));
  const {result} = inspect([branch]);
  assert.equal(result.status, 'observed');
  assert.equal(result.truncated, true);
  assert.ok(result.nodes.length <= 200);
});
