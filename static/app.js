'use strict';
// Sawti UI. No inline handlers, no innerHTML with data (QA: stored-XSS fix). Every write call sends X-Sawti.
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style') Object.assign(el.style, v); // CSSOM: allowed under the strict CSP
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false)
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body !== undefined || opts.form ? 'POST' : 'GET'), headers: {} };
  if (init.method !== 'GET') init.headers['X-Sawti'] = '1';
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  let r;
  try { r = await fetch(path, init); } catch (e) { throw new Error('Sawti is not running. Open it again from the Sawti app.'); }
  let d = {};
  try { d = await r.json(); } catch (e) { /* non-JSON */ }
  if (!r.ok) throw new Error(d.error || `Request failed (${r.status})`);
  return d;
}

const S = { on: false, mode: 'local', live: false, tab: 'prepare', simulated: false, voice: {}, seenNotices: 0,
  pretestActive: false, jobs: {}, settings: null, profiles: null };

function toast(message, level = 'info', ms = 6000) {
  const t = h('div', { class: `toast ${level}`, text: message });
  $('#toasts').append(t);
  setTimeout(() => t.remove(), ms);
}
function ask(text) {
  return new Promise((resolve) => {
    $('#confirmText').textContent = text; $('#confirm').hidden = false;
    const done = (v) => { $('#confirm').hidden = true; $('#confirmYes').onclick = $('#confirmNo').onclick = null; resolve(v); };
    $('#confirmYes').onclick = () => done(true); $('#confirmNo').onclick = () => done(false);
  });
}
async function guard(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(typeof okMsg === 'function' ? okMsg(r) : okMsg, 'ok'); return r; }
  catch (e) { toast(e.message, 'fail', 9000); return null; }
}

// ------------------------------------------------------------------ actions (shared by checks, chat, pre-test)
const NEEDS_CONFIRM = { record: 'Press RECORD in Audition now?', stop: 'Press STOP in Audition now?',
  fix_all: 'Let Sawti fix everything it can (devices, sample rates, session)?' };
async function runAction(action) {
  if (NEEDS_CONFIRM[action] && !(await ask(NEEDS_CONFIRM[action]))) return;
  if (action === 'pretest') { switchTab('pretest'); return startPretest(); }
  if (action === 'meter_start') { switchTab('live'); return startMeters(); }
  const r = await guard(() => api('/api/action', { body: { action } }), (x) => x.message);
  if (r) { if (r.findings) renderFindings(r.findings); refreshAudition(); }
}

// ------------------------------------------------------------------ power, mode, live
function renderPower(st) {
  S.on = st.on; S.live = st.live; S.mode = st.mode;
  $('#pill').textContent = st.live ? `LIVE ${Math.floor(st.live_minutes || 0)} min` : st.on ? 'ON' : 'OFF';
  $('#pill').className = 'pill ' + (st.live ? 'live' : st.on ? 'on' : 'off');
  $('#powerBtn').textContent = st.on ? 'Switch Sawti OFF' : 'Switch Sawti ON';
  $('#powerBtn').classList.toggle('on', st.on);
  $('#liveBtn').hidden = !st.on;
  $('#liveBtn').textContent = st.live ? 'End show' : 'Go live';
  $('#offNote').hidden = st.on;
  $$('.mode').forEach((b) => b.classList.toggle('active', b.dataset.mode === st.mode));
  $('#aiState').textContent = st.ollama_detail || '';
  for (const n of st.notices || []) if (n.id > S.seenNotices) { S.seenNotices = n.id; toast(n.message, n.level, 9000); }
}
$('#powerBtn').addEventListener('click', async () => {
  if (S.on) {
    if (S.live && !(await ask('A show is live. Switch Sawti off anyway? (Audition keeps recording.)'))) return;
    const st = await guard(() => api('/api/power/off', { body: {} }), 'Sawti is off. Nothing is listening.');
    if (st) { renderPower(st); clearLive(); }
  } else {
    const st = await guard(() => api('/api/power/on', { body: { mode: S.mode } }));
    if (st) { renderPower(st); refreshAll(); }
  }
});
$('#quitBtn').addEventListener('click', async () => {
  if (!(await ask('Close Sawti completely? Audition, Zoom and the Scarlett are not affected.'))) return;
  const r = await guard(() => api('/api/quit', { body: {} }));
  if (r) document.body.replaceChildren(h('div', { class: 'offnote', text: r.message }));
});
$('#liveBtn').addEventListener('click', async () => {
  const path = S.live ? '/api/live/end' : '/api/live/start';
  if (!S.live && !(await ask('Mark the show as LIVE? Sawti will keep the Mac awake, watch levels, and refuse any device changes until you end the show. (This does not press Record.)'))) return;
  const r = await guard(() => api(path, { body: {} }), (x) => x.message);
  if (r) { pollStatus(); if (!S.live) switchTab('live'); }
});
$$('.mode').forEach((b) => b.addEventListener('click', async () => {
  if (!S.on) { S.mode = b.dataset.mode; $$('.mode').forEach((x) => x.classList.toggle('active', x === b)); renderPrompts(); return; }
  const r = await guard(() => api('/api/mode', { body: { mode: b.dataset.mode } }), (x) => x.message);
  if (r) { renderPower(r.studio); renderPrompts(); refreshAll(); }
}));

// ------------------------------------------------------------------ tabs
function switchTab(name) {
  S.tab = name;
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.tabpanel').forEach((p) => { p.hidden = p.id !== `tab-${name}`; });
  if (!S.on) return;
  if (name === 'prepare') { refreshChecks(); refreshAudition(); }
  if (name === 'learning') refreshLearning();
  if (name === 'after') refreshPostFiles();
  if (name === 'settings') loadSettings();
  if (name === 'pretest') pollPretest();
}
$$('.tab').forEach((t) => t.addEventListener('click', () => switchTab(t.dataset.tab)));

// ------------------------------------------------------------------ checks
function renderFindings(list) {
  const box = $('#findings');
  box.replaceChildren(...list.map((f) => {
    let right = null;
    if (f.action) right = h('button', { class: 'btn small', text: f.action_label || 'Fix', onclick: () => runAction(f.action) });
    else if (f.severity === 'manual') right = h('button', { class: 'btn small', text: 'Confirmed',
      onclick: async () => { const r = await guard(() => api('/api/confirm', { body: { id: f.id } })); if (r) renderFindings(r.findings); } });
    return h('div', { class: `finding sev-${f.severity}` }, h('span', { class: 'dot' }),
      h('div', {}, h('div', { class: 't' }, h('span', { class: 'agent', text: f.agent }), f.title),
        f.detail ? h('div', { class: 'd', text: f.detail }) : null), right);
  }));
  const counts = {};
  for (const f of list) (counts[f.agent] = counts[f.agent] || []).push(f.severity);
  $('#agents').replaceChildren(...['Devices', 'Mac', 'Audition', 'Levels'].map((a) => {
    const sev = counts[a] || [];
    const worst = sev.includes('fail') ? 'needs fixing' : sev.includes('warn') ? 'attention' : 'all good';
    return h('div', { class: 'agentrow' }, h('span', { text: `${a} agent` }),
      h('span', { class: `chip ${worst === 'all good' ? 'good' : worst === 'attention' ? 'low' : 'clip'}`, text: worst }));
  }));
}
async function refreshChecks() {
  if (!S.on) return;
  try { const r = await api('/api/checks'); renderFindings(r.findings); } catch (e) { /* shown elsewhere */ }
}
$('#recheck').addEventListener('click', () => guard(async () => { await refreshChecks(); }, 'Checked again.'));
$('#fixAll').addEventListener('click', () => runAction('fix_all'));

// ------------------------------------------------------------------ Audition
async function refreshAudition() {
  if (!S.on) return;
  const r = await guard(() => api('/api/audition'));
  if (!r) return;
  const t = r.template;
  const lines = [];
  lines.push(h('div', {}, h('b', { text: 'Audition: ' }), r.app ? r.app.name : 'not found on this Mac'));
  if (t && !t.error) lines.push(h('div', {}, h('b', { text: 'Show template: ' }),
    `${t.tracks.length} tracks (${t.tracks.map((x) => x.name || '?').join(', ')})` + (t.sample_rate ? ` · ${t.sample_rate / 1000} kHz` : '')));
  else lines.push(h('div', { class: 'hint', text: t && t.error ? t.error : 'No show template saved yet — see below.' }));
  lines.push(h('div', {}, h('b', { text: "Today's session: " }), r.session ? `${r.session.name}  (${r.session.folder})` : 'not prepared'));
  if (r.accessibility === false) lines.push(h('div', { class: 'error', text: 'Allow Accessibility for Terminal/Sawti so Sawti can press Record.' }));
  $('#auditionBox').replaceChildren(...lines);
  if (!$('#sessionName').value) $('#sessionName').value = (r.session && r.session.name) || r.suggested_name || '';
  if (r.session) $('#postFolder').value = $('#postFolder').value || r.session.folder;
}
$('#prepareBtn').addEventListener('click', async () => {
  const r = await guard(() => api('/api/session/prepare', { body: { title: $('#sessionName').value } }), (x) => x.message);
  if (r) { refreshAudition(); refreshChecks(); }
});
$('#openBtn').addEventListener('click', () => runAction('open_session'));
$('#templateBtn').addEventListener('click', async () => {
  const r = await guard(() => api('/api/audition/template', { body: { path: $('#templatePath').value.trim().replace(/^'|'$/g, '') } }),
    (x) => `Template saved: ${x.template.tracks.length} tracks.`);
  if (r) { refreshAudition(); refreshChecks(); }
});

// ------------------------------------------------------------------ meters
const SCALE_MIN = -50, SCALE_MAX = -6;
const pct = (v) => Math.max(0, Math.min(100, ((v - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)) * 100));
const LABEL = { good: 'Good', low: 'A bit quiet', very_low: 'Too quiet', high: 'Loud', hot: 'Hot', clip: 'CLIPPING',
  dead: 'No signal', waiting: 'Waiting for speech', ok: 'Talkback' };
function renderMeters(meter, coach) {
  const byId = Object.fromEntries((coach || []).map((c) => [c.id, c]));
  $('#meterState').textContent = meter.running ? `${meter.device} · ${meter.rate / 1000} kHz${meter.leveler ? ' · leveler ON' : ''}` : 'Meters stopped';
  $('#meterError').hidden = !meter.error; $('#meterError').textContent = meter.error || '';
  if (meter.digital_silence) { $('#meterError').hidden = false; $('#meterError').textContent = 'Every input is digital silence: macOS is blocking microphone access. See the Prepare tab for the fix.'; }
  const target = S.settings ? S.settings.speech_target : -20;
  const box = $('#meters');
  box.replaceChildren(...(meter.sources || []).map((s) => {
    const c = byId[s.id] || { status: 'waiting', message: '' };
    const st = s.speaking ? s.short_term : -120;
    return h('div', { class: 'meter' },
      h('div', { class: 'name', text: s.name }),
      h('div', { class: 'barwrap', title: 'Short-term loudness; green band = target window' },
        h('div', { class: 'band', style: { bottom: `${pct(target - 6)}%`, height: `${pct(target + 6) - pct(target - 6)}%` } }),
        h('div', { class: 'fill', style: { height: `${pct(st)}%` } }),
        h('div', { class: 'peak', style: { bottom: `${pct(s.hold)}%` } })),
      h('div', {}, h('span', { class: `chip ${c.status}`, text: LABEL[c.status] || c.status })),
      h('div', { class: 'val', text: `${s.speaking ? s.short_term.toFixed(1) + ' LUFS' : '—'} · peak ${s.hold <= -100 ? '—' : s.hold.toFixed(1) + ' dBFS'}` +
        (s.leveler_gain !== null && s.leveler_gain !== undefined ? ` · rider ${s.leveler_gain > 0 ? '+' : ''}${s.leveler_gain} dB` : '') }),
      c.status !== 'good' && c.status !== 'waiting' && c.status !== 'ok' ? h('div', { class: 'coach', text: c.message }) : null);
  }));
  $('#mixLine').textContent = meter.mix_st && meter.mix_st > -70 ? `Programme mix right now: ${meter.mix_st} LUFS short-term` : '';
}
function clearLive() { $('#meters').replaceChildren(); $('#meterState').textContent = 'Meters stopped'; }
async function startMeters() {
  const r = await guard(() => api('/api/meter/start', { body: {} }), 'Meters started.');
  if (r) renderMeters(r.meter, []);
}
$('#meterStart').addEventListener('click', startMeters);
$('#meterStop').addEventListener('click', () => guard(() => api('/api/meter/stop', { body: {} }), 'Meters stopped.'));
$('#recBtn').addEventListener('click', () => runAction('record'));
$('#stopBtn').addEventListener('click', () => runAction('stop'));

let statusBusy = false;
async function pollStatus() {
  if (statusBusy) return; statusBusy = true;
  try {
    const r = await api('/api/status');
    renderPower(r.studio);
    if (r.meter.running || r.meter.error) renderMeters(r.meter, r.coach); else clearLive();
  } catch (e) { /* server may be restarting */ } finally { statusBusy = false; }
}

// ------------------------------------------------------------------ pre-test
async function startPretest() {
  const r = await guard(() => api('/api/pretest/start', { body: {} }));
  if (r) renderPretest(r);
}
function renderPretest(p) {
  S.pretestActive = p.active && !p.done;
  $('#steps').replaceChildren(...p.steps.map((s, i) => h('li', { class: s.status, text: `${i + 1}. ${s.title}` })));
  const cur = p.steps[p.index];
  $('#stepNow').hidden = !(p.active && cur);
  $('#pretestDone').hidden = !p.done;
  if (p.done) {
    $('#pretestDone').replaceChildren(h('h3', { text: p.ready ? '✅ Studio ready to record' : '⚠️ Pre-test finished with issues' }),
      ...p.steps.filter((s) => s.status !== 'pass').map((s) => h('div', { class: 'hint', text: `${s.title}: ${s.status}${s.detail ? ' — ' + s.detail : ''}` })));
  }
  if (!cur) return;
  $('#stepTitle').textContent = cur.title;
  $('#stepInstr').textContent = cur.instruction;
  $('#stepDetail').textContent = cur.detail || '';
  $('#stepDetail').className = `detail ${cur.status}`;
  $('#stepRecord').hidden = cur.kind !== 'record';
  $('#stepRetest').hidden = cur.kind === 'record';
  $('#stepFindings').replaceChildren(...(cur.findings || []).map((f) => h('div', { class: `finding sev-${f.severity}` },
    h('span', { class: 'dot' }), h('div', {}, h('div', { class: 't', text: f.title }), f.detail ? h('div', { class: 'd', text: f.detail }) : null),
    f.action ? h('button', { class: 'btn small', text: f.action_label || 'Fix', onclick: () => runAction(f.action) }) : null)));
}
async function pollPretest() {
  try { renderPretest(await api('/api/pretest')); } catch (e) { /* off */ }
}
$('#pretestStart').addEventListener('click', startPretest);
for (const [id, step] of [['#stepNext', 'next'], ['#stepSkip', 'skip'], ['#stepRetest', 'retest'], ['#stepRecord', 'recording']])
  $(id).addEventListener('click', async () => { const r = await guard(() => api(`/api/pretest/${step}`, { body: {} })); if (r) renderPretest(r); });

// ------------------------------------------------------------------ post-production
async function refreshPostFiles() {
  const folder = $('#postFolder').value.trim();
  const r = await guard(() => api('/api/post/files' + (folder ? `?folder=${encodeURIComponent(folder)}` : '')));
  if (!r) return;
  if (r.folder && !folder) $('#postFolder').value = r.folder;
  $('#postFiles').replaceChildren(...(r.files.length ? r.files.map((f) => h('label', {},
    h('input', { type: 'checkbox', checked: true, value: f }), f.split('/').slice(-2).join('/'))) :
    [h('div', { class: 'hint', text: 'No recorded tracks found in this folder yet.' })]));
}
$('#postLoad').addEventListener('click', refreshPostFiles);
const selectedFiles = () => $$('#postFiles input:checked').map((i) => i.value);
function watchJob(job, title) {
  S.jobs[job.id] = title;
  const el = h('div', { class: 'job', id: `job-${job.id}` }, h('b', { text: title }), h('div', { class: 'progress' }, h('div')), h('div', { class: 'hint', text: 'Working…' }));
  $('#jobs').prepend(el);
  const tick = async () => {
    let j; try { j = await api(`/api/jobs/${job.id}`); } catch (e) { return; }
    el.querySelector('.progress > div').style.width = `${Math.round(j.progress * 100)}%`;
    if (j.state === 'running') return setTimeout(tick, 1000);
    const info = el.querySelector('.hint');
    if (j.state === 'failed') { info.textContent = `Failed: ${j.error}`; info.className = 'error'; return; }
    if (Array.isArray(j.result)) {
      info.replaceWith(h('table', { class: 'qc' }, h('tr', {}, ...['File', 'LUFS', 'True peak', 'Issues'].map((x) => h('th', { text: x }))),
        ...j.result.map((q) => h('tr', {}, h('td', { text: q.path.split('/').pop() }), h('td', { text: q.integrated_lufs }),
          h('td', { text: q.true_peak_dbtp }), h('td', { text: q.issues.join(', ') || 'OK' })))));
    } else {
      const a = j.result.after;
      info.textContent = `${j.result.within_spec ? '✅' : '⚠️'} ${a.integrated_lufs} LUFS, ${a.true_peak_dbtp} dBTP, ${Math.round(a.duration / 60)} min → ${j.result.output}`;
    }
  };
  tick();
}
$('#qcBtn').addEventListener('click', async () => {
  const r = await guard(() => api('/api/post/qc', { body: { files: selectedFiles() } }));
  if (r) watchJob(r.job, 'Track QC');
});
$('#mixBtn').addEventListener('click', async () => {
  const files = selectedFiles();
  if (!files.length) return toast('Select at least one track.', 'warn');
  const r = await guard(() => api('/api/post/automix', { body: { files } }));
  if (r) watchJob(r.job, `Mix & master (${files.length} tracks)`);
});
$('#masterBtn').addEventListener('click', async () => {
  const r = await guard(() => api('/api/post/master', { body: { path: $('#masterPath').value.trim().replace(/^'|'$/g, '') } }));
  if (r) watchJob(r.job, 'Master to standard');
});

// ------------------------------------------------------------------ learning
async function refreshLearning() {
  const r = await guard(() => api('/api/learning'));
  if (!r) return;
  const card = (k, v) => h('div', { class: 'card' }, h('div', { class: 'k', text: k }), h('div', { class: 'v', text: v }));
  const kids = [
    card('Next show', r.next_show ? `${r.next_show.label} · ${r.next_show.mode === 'zoom' ? 'Zoom Show' : 'Podcast'} (seen ${r.next_show.seen}×)` : 'Not enough shows yet (needs the same slot twice)'),
    card('Next session name', r.suggested_name),
    card('Shows logged', String(r.shows_logged)),
    card('Usual folder', r.top_folder || 'Learning…'),
  ];
  for (const t of r.tips) kids.push(card('Tip from past shows', t));
  for (const s of r.autofix_suggestions) kids.push(h('div', { class: 'card' }, h('div', { class: 'k', text: 'Do this automatically?' }),
    h('div', { class: 'v', text: `${s.label} — you did it ${s.times}×` }),
    h('button', { class: 'btn small primary', text: 'Yes, from now on', onclick: async () => {
      const x = await guard(() => api('/api/learning/autofix', { body: { action: s.action, enabled: true } }), 'Sawti will do this automatically.');
      if (x) refreshLearning(); } })));
  for (const [action, on] of Object.entries(r.autofix)) if (on) kids.push(h('div', { class: 'card' },
    h('div', { class: 'k', text: 'Done automatically' }), h('div', { class: 'v', text: action.replace(/_/g, ' ') }),
    h('button', { class: 'btn small', text: 'Stop doing this', onclick: async () => {
      const x = await guard(() => api('/api/learning/autofix', { body: { action, enabled: false } })); if (x) refreshLearning(); } })));
  $('#learnBox').replaceChildren(...kids);
  $('#autoPrep').checked = !!r.auto_prepare;
}
$('#learnScan').addEventListener('click', async () => {
  const r = await guard(() => api('/api/learning/scan', { body: { folder: $('#learnFolder').value.trim() } }),
    (x) => `Learned from ${x.files} files${x.stopped_early ? ' (stopped early — choose a narrower folder)' : ''}.`);
  if (r) refreshLearning();
});
$('#autoPrep').addEventListener('change', (e) => guard(() => api('/api/settings', { body: { auto_prepare: e.target.checked } }), 'Saved.'));
$('#learnReset').addEventListener('click', async () => {
  if (!(await ask('Forget all learned habits and history? Settings and templates are kept.'))) return;
  const r = await guard(() => api('/api/learning/reset', { body: {} }), 'Learning history cleared.');
  if (r) refreshLearning();
});

// ------------------------------------------------------------------ settings
async function loadSettings() {
  const r = await guard(() => api('/api/settings'));
  if (!r) return;
  S.settings = r.settings; S.profiles = r.profiles;
  const s = r.settings;
  $('#setRoot').value = s.recording_root; $('#setLufs').value = s.loudness_target; $('#setTp').value = s.true_peak;
  $('#setSpeech').value = s.speech_target; $('#setLeveler').checked = !!s.leveler_enabled; $('#setLevOut').value = s.leveler_output;
  $('#setShowLocal').value = (s.show_name || {}).local || ''; $('#setShowZoom').value = (s.show_name || {}).zoom || '';
  const fields = [];
  for (const mode of ['local', 'zoom']) for (const src of r.profiles[mode].sources) if (src.role !== 'talkback')
    fields.push(h('label', {}, `${mode === 'zoom' ? 'Zoom show' : 'Podcast'} · input ${src.channels.join('+')}`,
      h('input', { value: src.name, 'data-mode': mode, 'data-src': src.id, autocomplete: 'off' })));
  $('#nameFields').replaceChildren(...fields);
}
$('#saveSettings').addEventListener('click', async () => {
  const names = { local: {}, zoom: {} };
  $$('#nameFields input').forEach((i) => { names[i.dataset.mode][i.dataset.src] = i.value.trim(); });
  const body = { recording_root: $('#setRoot').value.trim(), loudness_target: parseFloat($('#setLufs').value),
    true_peak: parseFloat($('#setTp').value), speech_target: parseFloat($('#setSpeech').value),
    leveler_enabled: $('#setLeveler').checked, leveler_output: $('#setLevOut').value.trim(), source_names: names,
    show_name: { local: $('#setShowLocal').value.trim(), zoom: $('#setShowZoom').value.trim() } };
  const r = await guard(() => api('/api/settings', { body }), 'Settings saved.');
  if (r) { S.settings = r.settings; }
});

// presenters (only when voice features are installed)
async function loadPeople() {
  const r = await guard(() => api('/api/presenters'));
  if (!r) return;
  $('#people').replaceChildren(...r.people.map((p) => h('div', { class: 'agentrow' },
    h('span', { text: `${p.name} · ${p.enrolled ? 'voice saved' : 'no voice yet'}` }),
    h('span', {}, h('button', { class: 'btn small', text: 'Record voice', onclick: () => recordVoice(`/api/presenters/${p.id}/voice`, true) }), ' ',
      h('button', { class: 'btn small', text: 'Delete', onclick: async () => {
        if (!(await ask(`Delete ${p.name} and their voice signature?`))) return;
        await guard(() => api(`/api/presenters/${p.id}`, { method: 'DELETE' })); loadPeople(); } })))));
}
$('#personAdd').addEventListener('click', async () => {
  const r = await guard(() => api('/api/presenters', { body: { name: $('#personName').value, consent: $('#personConsent').checked } }), 'Presenter added.');
  if (r) { $('#personName').value = ''; $('#personConsent').checked = false; loadPeople(); }
});

// ------------------------------------------------------------------ chat & voice
const PROMPTS = {
  local: ['Check the studio before recording', 'Run the pre-test', 'How are the mic levels?', 'Is Audition running?',
    'Prepare and open today\'s session', 'Suggest a filename', 'What if a microphone clips?', 'صوتي، افحص الميكروفونات'],
  zoom: ['Check the Zoom setup', 'Is BlackHole available?', 'How do I test mix-minus?', 'Check the guest return level',
    'Can the guest hear the talkback?', 'Is Audition running?', 'Run the pre-test', 'صوتي، افحص إعدادات زوم'],
};
function renderPrompts() {
  $('#prompts').replaceChildren(...PROMPTS[S.mode].map((p) => h('button', { class: 'prompt', text: p, onclick: () => send(p) })));
}
function addMsg(who, text, actions) {
  const rtl = /[؀-ۿ]/.test(text);
  const m = h('div', { class: `msg ${who === 'You' ? 'me' : 'bot'}`, dir: rtl ? 'rtl' : null }, h('span', { class: 'who', text: who }), text);
  if (actions && actions.length) m.append(h('div', { class: 'acts' }, ...actions.map((a) =>
    h('button', { class: 'btn small primary', text: a.label, onclick: () => runAction(a.action) }))));
  $('#chat').append(m); $('#chat').scrollTop = $('#chat').scrollHeight;
}
async function send(text) {
  addMsg('You', text);
  try { const r = await api('/api/chat', { body: { message: text } }); addMsg(r.source === 'ai' ? 'Sawti (AI)' : 'Sawti', r.reply, r.actions); }
  catch (e) { addMsg('Sawti', e.message); }
}
$('#chatForm').addEventListener('submit', (e) => { e.preventDefault(); const t = $('#chatInput').value.trim(); if (!t) return; $('#chatInput').value = ''; send(t); });

let recorder = null;
async function recordVoice(url, enrol) {
  if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { toast('The browser could not use the microphone: ' + e.message, 'fail'); return; }
  const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
  const chunks = [];
  recorder = new MediaRecorder(stream, { mimeType: mime });
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    $('#voiceState').textContent = 'Processing…'; $('#voiceBtn').textContent = '🎙 Tap to speak';
    const form = new FormData(); form.append('audio', new Blob(chunks, { type: mime }), mime.includes('webm') ? 'a.webm' : 'a.m4a');
    try {
      const r = await api(url, { form });
      if (enrol) { toast('Voice saved.', 'ok'); loadPeople(); }
      else { addMsg('You' + (r.speaker && r.speaker.name ? ` (${r.speaker.name}?)` : ''), r.text || '(nothing heard)'); addMsg('Sawti', r.reply, r.actions); }
    } catch (e) { toast(e.message, 'fail'); }
    $('#voiceState').textContent = '';
  };
  recorder.start();
  $('#voiceState').textContent = enrol ? 'Recording voice sample — speak for 6+ seconds, tap again to stop' : 'Listening — tap again to stop';
  if (!enrol) $('#voiceBtn').textContent = '■ Tap to stop';
}
$('#voiceBtn').addEventListener('click', () => recordVoice('/api/voice', false));

// ------------------------------------------------------------------ boot
async function refreshAll() {
  if (!S.on) return;
  refreshChecks(); refreshAudition(); loadSettings();
  if (S.tab === 'learning') refreshLearning();
}
async function boot() {
  try {
    const a = await api('/api/app');
    $('#version').textContent = `Sawti ${a.version}`;
    $('#simBanner').hidden = !a.simulated; S.simulated = a.simulated; S.voice = a.voice || {};
    $('#voiceBtn').hidden = !S.voice.transcribe;
    $('#presenterSection').hidden = !S.voice.identify;
    renderPower(a); renderPrompts();
    if (S.voice.identify) loadPeople();
    if (a.on) refreshAll();
  } catch (e) { toast(e.message, 'fail', 15000); }
  addMsg('Sawti', 'Hello! Switch me ON, then I can check the studio, fix what I can, run the pre-test, open the Audition session and watch levels during the show.');
  setInterval(() => { if (S.on) pollStatus(); }, 1000);
  setInterval(() => { if (S.on) refreshChecks(); }, 6000);
  setInterval(() => { if (S.on && S.tab === 'pretest' && S.pretestActive) pollPretest(); }, 1000);
}
boot();
