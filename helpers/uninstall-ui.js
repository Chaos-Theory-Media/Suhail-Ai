/* Native macOS review UI (JXA). No Flask or running Sawti server is required. */
function shellQuote(value) { return "'" + String(value).replace(/'/g, "'\\''") + "'"; }

function run(argv) {
  'use strict';
  ObjC.import('Foundation');
  const ui = Application.currentApplication();
  ui.includeStandardAdditions = true;
  const home = ObjC.unwrap($.NSHomeDirectory());
  const source = argv[0];
  const engine = argv[1] || source + '/helpers/uninstall.py';
  const support = home + '/Library/Application Support/Sawti';
  const choices = [support + '/venv/bin/python', '/usr/bin/python3', '/opt/homebrew/bin/python3', '/usr/local/bin/python3'];
  try {
    const extra = ui.doShellScript('/usr/bin/find ' + shellQuote(support + '/runtime/python') +
      " -type f -name 'python3*' -perm -111 2>/dev/null");
    choices.push.apply(choices, extra.split('\n').filter(Boolean));
  } catch (_) {}
  let python = null;
  for (const candidate of choices) {
    try {
      ui.doShellScript(shellQuote(candidate) + " -I -c 'import sys,json,sqlite3,ctypes,plistlib; assert sys.version_info >= (3,9)'");
      python = candidate; break;
    } catch (_) {}
  }
  if (!python) {
    ui.displayAlert('Uninstall could not start', {message: 'No working Python interpreter was found. Nothing was deleted. Keep the Sawti folder and request repair assistance; do not remove audio drivers to troubleshoot this.', as: 'critical'});
    return;
  }
  let temporary = null;
  function invoke(command, extra) {
    const args = [python, '-I', engine, command, '--gui', '--home', home, '--source', source].concat(extra || []);
    const raw = ui.doShellScript('exec ' + args.map(shellQuote).join(' '));
    const value = JSON.parse(raw);
    if (value.error) throw new Error(value.error);
    return value;
  }
  try {
    const stop = ui.displayDialog('Clean uninstall stops only verified Sawti processes, including their capture/output streams. Older inline builds may carry production audio. Adobe Audition, Zoom, Focusrite Control and external Ollama are never stopped.\n\nFirst stop ALL production recording and check that the studio is idle. Continue?',
      {withTitle: 'Uninstall Sawti', buttons: ['Cancel', 'Studio idle — continue'], defaultButton: 'Cancel', cancelButton: 'Cancel'});
    if (stop.buttonReturned !== 'Studio idle — continue') return;
    invoke('stop', ['--confirm-idle']);
    const labels = {
      'Sawti apps, Desktop shortcuts and launcher backups': 'app',
      'Private Python, Ollama, models, caches and logs': 'runtime',
      'Personal settings, presenters, templates and learning data': 'data',
      'Unchanged downloaded source files (optional)': 'source',
      'Unused Sawti virtual audio devices (advanced, optional)': 'devices'
    };
    const selected = ui.chooseFromList(Object.keys(labels), {withTitle: 'Choose uninstall components',
      withPrompt: 'Recordings and unknown/edited files are preserved. Shared BlackHole, FFmpeg, Homebrew, Apple tools and legacy shared model caches are retained.',
      defaultItems: Object.keys(labels).slice(0, 3), multipleSelectionsAllowed: true, emptySelectionAllowed: false});
    if (!selected) return;
    temporary = ui.doShellScript('/usr/bin/mktemp -d /tmp/sawti-uninstall.XXXXXX');
    const planFile = temporary + '/review.json';
    const preview = invoke('preview', ['--components', selected.map(x => labels[x]).join(','), '--plan', planFile]);
    const summary = 'Move to Trash: ' + preview.remove.length + ' file/folder entries.\n' +
      preview.remove.slice(0, 8).join('\n') + (preview.remove.length > 8 ? '\n…open the review list for all paths.' : '') +
      '\n\nPreserved items: ' + preview.preserved.length + '. No recordings are deleted.\n' +
      'Virtual devices eligible for removal: ' + preview.devices.map(d => d.name).join(', ') +
      '\nVirtual-device warnings: ' + preview.retained_devices.map(d => d.reason).join('; ') +
      '\n\nSelected personal data goes to Trash and remains recoverable until Trash is emptied. Shared tools remain installed.';
    while (true) {
      const decision = ui.displayDialog(summary, {withTitle: 'Review Sawti uninstall',
        buttons: ['Cancel', 'Review list', 'Move to Trash'], defaultButton: 'Review list', cancelButton: 'Cancel'});
      if (decision.buttonReturned === 'Review list') {
        ui.doShellScript('/usr/bin/open -t ' + shellQuote(planFile));
        continue;
      }
      if (decision.buttonReturned !== 'Move to Trash') return;
      break;
    }
    if (preview.devices.length) {
      ui.displayDialog('Also remove ONLY these Sawti virtual devices?\n\n' + preview.devices.map(d => d.name + '\n' + d.uid).join('\n\n') +
        '\n\nThe helper will refuse active/default/referenced devices. No sample rates or default routing will be changed.',
        {withTitle: 'Authorise virtual-device removal', buttons: ['Cancel', 'Remove reviewed devices'],
         defaultButton: 'Cancel', cancelButton: 'Cancel'});
    }
    const result = invoke('execute', ['--plan', planFile, '--confirm-idle']);
    const text = result.moved.length + ' entries moved to Trash.\nRecordings were preserved.\n' +
      'Devices removed: ' + result.removed_devices.length + '.\n' +
      'Retained items: ' + result.preserved.length + '.\n' +
      (result.errors.length ? 'Items needing review:\n' + result.errors.join('\n') + '\n' : '') +
      (result.retained_devices.length ? 'Some audio-device cleanup was blocked. The helper/inventory/uninstaller are retained where available for retry.\n' : '') +
      '\nReport: ' + result.report + '\n\nReview the report, then empty Trash to reclaim space. Shared drivers/tools and macOS permissions remain.';
    const done = ui.displayDialog(text, {withTitle: result.errors.length ? 'Sawti uninstall needs review' : 'Sawti cleanup finished',
      buttons: ['Close', 'Open report'], defaultButton: 'Open report'});
    if (done.buttonReturned === 'Open report') ui.doShellScript('/usr/bin/open -t ' + shellQuote(result.report));
  } catch (error) {
    if (error.errorNumber !== -128) ui.displayAlert('Uninstall stopped', {message: String(error.message || error) +
      '\nNo unverified process is stopped and no routing is restored automatically. See the last report and Trash for any completed moves.', as: 'critical'});
  } finally {
    if (temporary) {
      try { ui.doShellScript('/bin/rm -f ' + shellQuote(temporary + '/review.json') +
                            '; /bin/rmdir ' + shellQuote(temporary)); } catch (_) {}
    }
  }
}
