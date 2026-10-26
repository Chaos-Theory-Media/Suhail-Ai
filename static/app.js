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
  const open = ['/api/app', '/api/power', '/api/power/on', '/api/power/off', '/api/quit', '/api/settings'];
  if (!S.on && !open.includes(path)) throw new Error('Sawti is OFF. Switch it ON first.');
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
  pretestActive: false, jobs: {}, settings: null, profiles: null, generation: 0,
  micContext: null, micPlanId: null, presenterSpeech: {enabled: false, phase: 'muted'},
  speechDevices: [], speechContext: null, speechRequestPending: false, speechRequestEpoch: 0 };

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
  fix_all: 'Run non-audio fixes? Sample rates, devices and Audition changes need individual approval.' };
async function runAction(action) {
  let approval = {};
  const impactful = new Set(['record', 'stop', 'open_session', 'open_zoom', 'set_scarlett_48k',
    'set_blackhole_48k', 'set_show_input_48k', 'create_show_input', 'repair_show_input', 'create_zoom_speaker',
    'open_focusrite', 'open_audition', 'open_studio_apps']);
  if (impactful.has(action)) {
    const review = await guard(() => api('/api/action/review', {body: {action}}));
    if (!review) return;
    const text = `${review.label}: ${review.impact}\n\n${review.warning}\n\n` +
      (review.requires_idle ? 'Authorise this action and confirm you checked that ALL recording is idle?' :
        'Authorise sending Stop even if it interrupts the current recording?');
    if (!(await ask(text))) return;
    approval = {approval: review.token, operator_confirmed: true, studio_idle: review.requires_idle};
  } else if (NEEDS_CONFIRM[action] && !(await ask(NEEDS_CONFIRM[action]))) return;
  if (action === 'pretest') { switchTab('pretest'); return startPretest(); }
  if (action === 'meter_start') { switchTab('live'); return startMeters(); }
  const r = await guard(() => api('/api/action', { body: { action, ...approval } }), (x) => x.message);
  if (r) { if (r.findings) renderFindings(r.findings); refreshAudition(); }
}

// ------------------------------------------------------------------ power, mode, live
function renderMicrophones(plan, context) {
  const planId = plan ? plan.id : null;
  // Polling must not erase an edit awaiting explicit confirmation. Hydrate only
  // when loading a session or observing a genuinely different confirmed plan.
  if (S.micContext !== context || S.micPlanId !== planId)
    $('#podcastMics').value = plan ? plan.inputs.join(',') : '';
  S.micContext = context; S.micPlanId = planId;
  $('#podcastMicStatus').textContent = plan ?
    `Confirmed programme inputs: ${plan.inputs.join(', ')}. Mic 1: presenter. Input 4: talkback only.` :
    'Confirm microphones before preparing the session or starting pre-test.';
}
function renderPower(st) {
  if (S.on !== st.on) S.generation++;
  if (!st.on) stopVoice();
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
  $('#recordingState').textContent = 'Audition recording state: unknown. LIVE is an operator marker.';
  $('#podcastMicSetup').hidden = st.mode !== 'local';
  renderMicrophones(st.on && st.mode === 'local' ? st.microphone_plan : null,
    `${st.on}:${st.mode}:${st.power_epoch || 0}`);
  if (S.speechContext !== S.micContext) {
    S.speechContext = S.micContext;
    S.speechRequestPending = false; S.speechRequestEpoch++;
    clearSpeechAttestations();
    $('#speechMapping').checked = false;
  }
  renderPresenterSpeech(st.on ? st.presenter_speech : null);
  for (const n of st.notices || []) if (n.id > S.seenNotices) { S.seenNotices = n.id; toast(n.message, n.level, 9000); }
}
$('#powerBtn').addEventListener('click', async () => {
  if (S.on) {
    if (S.live && !(await ask('A show is live. Switch Sawti off anyway? (Audition keeps recording.)'))) return;
    S.generation++; stopVoice(); S.on = false;
    const st = await guard(() => api('/api/power/off', { body: {} }), 'Sawti capture and managed services are off.');
    if (st) { renderPower(st); clearLive(); }
  } else {
    const st = await guard(() => api('/api/power/on', { body: { mode: S.mode } }));
    if (st) { renderPower(st); refreshAll(); }
  }
});
$('#quitBtn').addEventListener('click', async () => {
  if (!(await ask('Close Sawti completely? Audition, Zoom and the Scarlett are not affected.'))) return;
  S.generation++; stopVoice(); S.on = false;
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
$('#openStudioApps').addEventListener('click', () => runAction('open_studio_apps'));
$('#openFocusrite').addEventListener('click', () => runAction('open_focusrite'));
$('#openAuditionApp').addEventListener('click', () => runAction('open_audition'));
$('#confirmPodcastMics').addEventListener('click', async () => {
  const value = $('#podcastMics').value;
  const generation = S.generation, context = S.micContext;
  if (!value) { toast('Choose one, two or three programme microphones first.', 'warn'); return; }
  if (!(await ask('Confirm these programme microphones and that all recording is idle? This clears previous Sawti tests and stops its meters. Audition tracks and Focusrite routing still need verification.'))) return;
  if (!S.on || generation !== S.generation || context !== S.micContext) return;
  const r = await guard(() => api('/api/podcast/microphones', {body: {
    inputs: value.split(',').map(Number), studio_idle: true}}), x => x.message);
  if (r && S.on && generation === S.generation && context === S.micContext) {
    S.generation++; // discard status responses admitted before this confirmation
    renderMicrophones(r.plan, context);
    pollStatus(); refreshAudition(); refreshChecks(); pollPretest();
  }
});
for (const [id, path, body] of [
  ['autonomyReadiness', '/api/readiness', undefined],
  ['inspectAudition', '/api/audition/inspect', {}]
]) $( '#' + id).addEventListener('click', async () => {
  const generation = S.generation;
  const r = await guard(() => api(path, {body}));
  if (!r || !S.on || generation !== S.generation) return;
  $('#autonomyReport').hidden = false;
  $('#autonomyReport').textContent = JSON.stringify(r, null, 2);
});
$('#deviceDiagnostics').addEventListener('click', async () => {
  const result = await guard(() => api('/api/devices'));
  if (!result) return;
  const summary = {audio_queries: result.diagnostics, helper_installed: result.helper,
    devices: result.devices.map(d => ({name: d.name, inputs: d.inputs, outputs: d.outputs,
      observed_rate_hz: d.rate_verified ? d.rate : null, rate_verified: !!d.rate_verified,
      rate_source: d.rate_source || 'simulation', capture_engine_index: d.index}))};
  $('#deviceDiagnosticText').hidden = false;
  $('#deviceDiagnosticText').textContent = JSON.stringify(summary, null, 2);
});

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
  if (meter.digital_silence) { $('#meterError').hidden = false; $('#meterError').textContent = 'All inputs are digital silence. Check source, routing and microphone permission; the cause is unverified.'; }
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
  const generation = S.generation;
  try {
    const r = await api('/api/status');
    if (generation !== S.generation) return;
    renderPower(r.studio);
    if (r.meter.running || r.meter.error) renderMeters(r.meter, r.coach); else clearLive();
  } catch (e) {
    try { renderPower(await api('/api/power')); }
    catch { S.generation++; stopVoice(); S.on = false; clearLive(); $('#pill').textContent = 'CONNECTION LOST'; }
  } finally { statusBusy = false; }
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
  if (r.report) $('#learningReportStatus').textContent =
    `${r.report.folder}/${r.report.filename} · automatic updates · ${r.report.retention_days}-day working history` +
    (r.report.error ? ` · Report update failed (${r.report.error}); download will retry.` : '');
}
$('#openLearningFolder').addEventListener('click', () => guard(async () => {
  const r = await api('/api/learning/report/folder', {body: {}});
  if (!r.opened) toast('Simulation folder: ' + r.folder);
}));
$('#downloadLearningReport').addEventListener('click', async () => {
  const generation = S.generation;
  const r = await guard(() => api('/api/learning/report/refresh', {body: {}}));
  if (!r || !S.on || generation !== S.generation) return;
  const link = h('a', {href: '/api/learning/report/download', download: 'Sawti-Learnings.json'});
  document.body.append(link); link.click(); link.remove();
  refreshLearning();
});
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
const SAWTI_WELCOME = 'Hello, I’m Sawti, your studio assistant. I can help you prepare and check your studio.';
let speechPollTimer = null;
function clearSpeechAttestations() {
  for (const id of ['speechHeadphonesOnly', 'speechNotRecorded', 'speechNoLoopback', 'speechAcoustic'])
    $('#' + id).checked = false;
}
function renderPresenterSpeech(state) {
  S.presenterSpeech = state || {enabled: false, phase: 'muted'};
  const voice = S.presenterSpeech;
  $('#sawtiCharacter').classList.toggle('speaking', voice.phase === 'speaking' && S.on);
  $('#mutePresenterSpeech').disabled = !S.on;
  $('#presenterSpeechState').textContent = voice.phase === 'unknown' ? 'Voice state unavailable · wait for reconnection or switch Sawti OFF' :
    voice.error ? `Voice muted: ${voice.error}` :
    voice.phase === 'speaking' ? 'Speaking to the configured private headset pair' :
    voice.phase === 'preparing' ? 'Preparing local speech…' :
    voice.phase === 'test_complete' ? 'Test played · listen back before enabling' :
    voice.enabled ? 'Private voice enabled · isolation checked by operator' : 'Text welcome · private voice is off';
  if (voice.caption) $('#sawtiCaption').textContent = voice.caption;
  clearTimeout(speechPollTimer); speechPollTimer = null;
  if (S.on && ['preparing', 'speaking', 'unknown'].includes(voice.phase)) {
    const generation = S.generation;
    speechPollTimer = setTimeout(async () => {
      try {
        const r = await api('/api/presenter-speech/state');
        if (S.on && generation === S.generation) renderPresenterSpeech(r);
      } catch (_) { if (generation === S.generation && S.on) renderPresenterSpeech({enabled: false, phase: 'unknown'}); }
    }, 150);
  }
}
async function sayToPresenter(text) {
  if (!S.on || S.simulated || !S.presenterSpeech.enabled || recorder || voicePending || S.speechRequestPending) return;
  if (text.length > 700) text = (text.match(/[؀-ۿ]/g) || []).length > (text.match(/[a-zA-Z]/g) || []).length ?
    'وضعت التعليمات الكاملة على الشاشة لتراجعها.' : 'I’ve put the full instructions on screen for you.';
  const generation = S.generation;
  const requestEpoch = ++S.speechRequestEpoch;
  S.speechRequestPending = true;
  try {
    const r = await guard(() => api('/api/presenter-speech/speak', {body: {text}}));
    if (S.on && generation === S.generation && requestEpoch === S.speechRequestEpoch)
      renderPresenterSpeech(r ? r.state : {enabled: false, phase: 'unknown'});
  } finally {
    if (requestEpoch === S.speechRequestEpoch) S.speechRequestPending = false;
  }
}
function populateSpeechPairs() {
  const device = S.speechDevices.find(d => d.uid === $('#speechDevice').value);
  const options = [h('option', {value: '', text: 'Choose verified headphone-only USB pair'})];
  if (device && device.outputs >= 4)
    options.push(h('option', {value: '3,4', text: 'USB Playback 3–4 → presenter outputs 3–4'}));
  $('#speechPair').replaceChildren(...options);
}
async function refreshSpeechSetup() {
  const r = await guard(() => api('/api/presenter-speech'));
  if (!r) return;
  S.speechDevices = r.devices;
  if (!r.devices.some(d => d.uid))
    toast('No stable Scarlett device identity is available. Use Show device diagnostics in Prepare; private voice stays off.', 'warn');
  $('#speechDevice').replaceChildren(h('option', {value: '', text: 'Choose exact Scarlett device'}),
    ...r.devices.filter(d => d.uid).map(d => h('option', {value: d.uid, text: d.name})));
  populateSpeechPairs();
  for (const [id, language, label] of [['speechEnglish', 'en_', 'Choose installed English voice'],
    ['speechArabic', 'ar_', 'Text only in Arabic']])
    $('#' + id).replaceChildren(h('option', {value: '', text: label}),
      ...r.voices.filter(v => v.language.startsWith(language)).map(v => h('option', {value: v.name, text: `${v.name} · ${v.language}`})));
  renderPresenterSpeech(r.state);
}
$('#refreshSpeechSetup').addEventListener('click', refreshSpeechSetup);
$('#speechDevice').addEventListener('change', populateSpeechPairs);
$('#configureSpeech').addEventListener('click', async () => {
  if (!(await ask('All production recording must be stopped. Save this private voice plan without changing Focusrite routing?'))) return;
  const voices = {en: $('#speechEnglish').value};
  if ($('#speechArabic').value) voices.ar = $('#speechArabic').value;
  const r = await guard(() => api('/api/presenter-speech/configure', {body: {
    uid: $('#speechDevice').value, pair: $('#speechPair').value.split(',').map(Number), voice: voices,
    studio_idle: true, headphone_mapping_confirmed: $('#speechMapping').checked}}));
  if (r) { clearSpeechAttestations(); renderPresenterSpeech(r); }
});
$('#testPresenterSpeech').addEventListener('click', async () => {
  if (!(await ask('Play the low-level Sawti test phrase on the configured pair? Confirm production recording is idle, headphones are mapped, and you have prepared isolated test recordings to check leakage.'))) return;
  clearSpeechAttestations();
  const r = await guard(() => api('/api/presenter-speech/test', {body: {studio_idle: true, operator_confirmed: true}}));
  if (r) renderPresenterSpeech(r.state);
});
$('#enablePresenterSpeech').addEventListener('click', async () => {
  if (!(await ask('Enable spoken chat replies on the tested pair for this session? Confirm all production recording is idle and you have listened back to the isolation tests.'))) return;
  const r = await guard(() => api('/api/presenter-speech/enable', {body: {studio_idle: true, attestations: {
    headphones_only: $('#speechHeadphonesOnly').checked, no_recorded_speech: $('#speechNotRecorded').checked,
    no_loopback: $('#speechNoLoopback').checked, acoustic_checked: $('#speechAcoustic').checked}}}));
  if (r) { renderPresenterSpeech(r); sayToPresenter(SAWTI_WELCOME); }
});
$('#mutePresenterSpeech').addEventListener('click', async () => {
  const r = await guard(() => api('/api/presenter-speech/mute', {body: {}}));
  if (r) { clearSpeechAttestations(); renderPresenterSpeech(r); }
});
const PROMPTS = {
  local: ['How do I use Sawti?', 'Check the studio before recording', 'Run the pre-test', 'How are the mic levels?', 'Is Audition running?',
    'Prepare and open today\'s session', 'Suggest a filename', 'What if a microphone clips?', 'صوتي، افحص الميكروفونات'],
  zoom: ['How do I record a Zoom interview?', 'Check the Zoom setup', 'Is BlackHole available?', 'How do I test mix-minus?', 'Check the guest return level',
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
  try { const r = await api('/api/chat', { body: { message: text } }); addMsg(r.source === 'ai' ? 'Sawti (AI)' : 'Sawti', r.reply, r.actions); sayToPresenter(r.reply); }
  catch (e) { addMsg('Sawti', e.message); }
}
$('#chatForm').addEventListener('submit', (e) => { e.preventDefault(); const t = $('#chatInput').value.trim(); if (!t) return; $('#chatInput').value = ''; send(t); });

let recorder = null, voiceStream = null, voiceGeneration = 0, voicePending = false, voiceTimer = null;
function stopVoice() {
  voiceGeneration++;
  voicePending = false;
  clearTimeout(voiceTimer); voiceTimer = null;
  if (recorder && recorder.state === 'recording') recorder.stop();
  if (voiceStream) voiceStream.getTracks().forEach((t) => t.stop());
  voiceStream = null; recorder = null;
  $('#voiceState').textContent = ''; $('#voiceBtn').textContent = '🎙 Tap to speak';
}
window.addEventListener('pagehide', () => {
  stopVoice();
  if (S.on && (S.presenterSpeech.enabled || ['preparing', 'speaking'].includes(S.presenterSpeech.phase))) {
    // Best effort only. OFF/Quit is the authoritative server-side stop.
    fetch('/api/presenter-speech/mute', {method: 'POST', headers: {'X-Sawti': '1'}, keepalive: true}).catch(() => {});
  }
  renderPresenterSpeech(null);
});
async function recordVoice(url, enrol) {
  if (S.simulated) return toast('Simulation does not use real microphones.', 'warn');
  if (!S.on) return toast('Switch Sawti ON before using the microphone.', 'warn');
  if (S.speechRequestPending || ['preparing', 'speaking', 'unknown'].includes(S.presenterSpeech.phase))
    return toast('Wait until Sawti finishes speaking, or mute her voice before using the microphone.', 'warn');
  if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
  if (voicePending) return;
  const generation = ++voiceGeneration;
  voicePending = true;
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { if (generation === voiceGeneration) voicePending = false; toast('The browser could not use the microphone: ' + e.message, 'fail'); return; }
  if (!S.on || generation !== voiceGeneration) { stream.getTracks().forEach((t) => t.stop()); return; }
  voicePending = false; voiceStream = stream;
  let media;
  try {
    const mime = ['audio/webm', 'audio/mp4'].find((m) => MediaRecorder.isTypeSupported(m));
    media = mime ? new MediaRecorder(stream, {mimeType: mime}) : new MediaRecorder(stream);
  } catch (e) { stopVoice(); toast(e.message, 'fail'); return; }
  recorder = media;
  const mime = media.mimeType || 'audio/webm';
  const chunks = [];
  let bytes = 0, tooLarge = false;
  media.ondataavailable = (e) => {
    bytes += e.data.size;
    if (bytes > 7 * 1024 * 1024) { tooLarge = true; if (media.state === 'recording') media.stop(); }
    else chunks.push(e.data);
  };
  media.onerror = () => { stopVoice(); toast('Microphone recording failed.', 'fail'); };
  media.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    if (!S.on || generation !== voiceGeneration) return;
    clearTimeout(voiceTimer); voiceTimer = null; voiceStream = null; recorder = null;
    if (tooLarge) { toast('Voice sample exceeded the size limit.', 'fail'); return; }
    $('#voiceState').textContent = 'Processing…'; $('#voiceBtn').textContent = '🎙 Tap to speak';
    const form = new FormData(); form.append('audio', new Blob(chunks, { type: mime }), mime.includes('webm') ? 'a.webm' : 'a.m4a');
    try {
      const r = await api(url, { form });
      if (!S.on || generation !== voiceGeneration) return;
      if (enrol) { toast('Voice saved.', 'ok'); loadPeople(); }
      else { addMsg('You' + (r.speaker && r.speaker.name ? ` (${r.speaker.name}?)` : ''), r.text || '(nothing heard)'); addMsg('Sawti', r.reply, r.actions); sayToPresenter(r.reply); }
    } catch (e) { toast(e.message, 'fail'); }
    $('#voiceState').textContent = '';
  };
  try { media.start(1000); }
  catch (e) { stopVoice(); toast(e.message, 'fail'); return; }
  voiceTimer = setTimeout(() => { if (media.state === 'recording') media.stop(); }, 60000);
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
  addMsg('Sawti', 'I’m Sawti, your studio assistant. Switch ON to check the studio or ask how to use it.');
  setInterval(() => { if (S.on) pollStatus(); }, 1000);
  setInterval(() => { if (S.on) refreshChecks(); }, 6000);
  setInterval(() => { if (S.on && S.tab === 'pretest' && S.pretestActive) pollPretest(); }, 1000);
}
boot();
