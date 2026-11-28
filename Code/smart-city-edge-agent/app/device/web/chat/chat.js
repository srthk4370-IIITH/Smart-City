/* Campus Assistant: a second frontend on the same edge-agent backend (backend/chat.go).
   Sessions live on the board (state/chats.json); this page lists them, shows one, and asks questions. */
'use strict';
const $ = (s) => document.querySelector(s);
const S = { id: null, sessions: [], session: null, busy: false };
window.S = S;
const SUGG = [
  ['Counts', 'How many incidents were there today?'],
  ['Search', 'Which CO2 incidents happened this week?'],
  ['Health', 'Which domains have open incidents right now?'],
  ['Faults', 'Which sensors were faulty this month?'],
];
const STAGES = [[0, 'Thinking on the NPU…'], [4, 'Loading the reasoner on the NPU…'], [9, 'Looking through the incident store…'], [16, 'Writing the answer…'], [40, 'Still working, the NPU is busy…']];

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (k === 'text') e.textContent = v; else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k);
  return e;
}
async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'sce' } }, opts));
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
const when = (t) => {
  const d = new Date(t * 1000), now = new Date();
  return d.toDateString() === now.toDateString() ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
};

/* answer text -> nodes: [INC-0123] and bare INC-0123 become chips linking to the dashboard */
function richText(s) {
  s = String(s || '').replace(/approve(?:d)? or dismiss(?:ed)?/gi, "I'm on it or Dismiss").replace(/approve(?:d)?/gi, "taken (I'm on it)");
  const out = []; const re = /\[?(INC-\d{3,})\]?/g; let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    out.push(h('a', { class: 'inc', href: '/#incident/' + m[1], title: 'Open the dashboard', text: m[1] }));
    last = re.lastIndex;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

/* ------------------------------------------------------------ history sidebar */
async function loadSessions() {
  try { S.sessions = await api('/api/chat/sessions'); } catch { S.sessions = []; }
  renderSide();
}
function renderSide() {
  const box = $('#hist'); box.replaceChildren();
  if (!S.sessions.length) { box.append(h('div', { class: 'empty', text: 'No chats yet. Your conversations are kept on this board.' })); return; }
  const today = new Date().toDateString(); let group = '';
  for (const x of S.sessions) {
    const g = new Date(x.updated * 1000).toDateString() === today ? 'Today' : 'Earlier';
    if (g !== group) { box.append(h('h4', { text: g })); group = g; }
    box.append(h('button', { type: 'button', class: 'hi' + (x.id === S.id ? ' on' : ''), onclick: () => { openSession(x.id); closeSide(); } },
      h('span', { class: 't', text: x.title }), h('span', { class: 'm', text: when(x.updated) + ' · ' + Math.ceil(x.messages / 2) + ' question' + (x.messages > 2 ? 's' : '') })));
  }
}
async function openSession(id) {
  S.id = id;
  try { S.session = await api('/api/chat/sessions/' + encodeURIComponent(id)); } catch { S.session = null; S.id = null; }
  renderSide(); renderChat();
}
function newChat() { S.id = null; S.session = null; renderSide(); renderChat(); $('#q').focus(); }

/* ------------------------------------------------------------ conversation */
// where the answer was computed: the backend names the model when chat runs on its own server (chat_url, e.g.
// "qwen3.5-2b rsn_v3 (cpu)" or the htpd fallback); a fast answer without a model is the rule-based router (CPU);
// a slower one is the model on the NPU (no chat_url)
function engineOf(m) {
  if (m.model) return ' · ' + m.model;
  return (m.ms - (m.queued_ms || 0)) >= 1500 ? ' on the NPU' : '';
}

function msgNode(m) {
  if (m.role === 'user') return h('div', { class: 'row user' }, h('div', { class: 'bub', text: m.text }));
  const toolsBox = h('div', { class: 'tools' }, (m.tools || []).map((t) => h('div', { class: 'tool' },
    h('div', {}, 'Checked ', h('b', { text: t.name }), ' ', h('span', { text: t.args && t.args !== '{}' ? t.args : '' })),
    h('code', { text: t.result }))));
  const meta = h('div', { class: 'meta' },
    m.tools && m.tools.length ? h('button', { type: 'button', class: 'how', onclick: () => toolsBox.classList.toggle('open') }, 'How I found this · ' + m.tools.length + ' lookup' + (m.tools.length > 1 ? 's' : '')) : null,
    m.queued_ms > 1500 ? h('span', { text: 'waited ' + (m.queued_ms / 1000).toFixed(0) + ' s for an alert analysis' }) : null,
    m.ms ? h('span', { text: ((m.ms - (m.queued_ms || 0)) / 1000).toFixed(1) + ' s' + engineOf(m) }) : null);
  return h('div', { class: 'row bot' + (m.busy ? ' busy' : '') + (m.error ? ' err' : '') }, h('div', { class: 'av', 'aria-hidden': 'true', text: '✦' }),
    h('div', { class: 'bub' }, h('div', {}, richText(m.text)), meta, toolsBox));
}
function renderChat() {
  const box = $('#msgs'); box.replaceChildren();
  const s = S.session;
  $('#title').textContent = s ? s.title : 'New chat';
  $('#del').hidden = !s;
  if (!s || !s.messages.length) {
    box.append(h('div', { class: 'welcome' }, h('div', { class: 'big', 'aria-hidden': 'true', text: '✦' }),
      h('h2', { text: 'Ask the campus monitor' }),
      h('p', { text: 'The on-device AI looks up incidents, sensors and past actions on this board and answers with exact numbers. It can explain, but it never switches anything.' }),
      h('div', { class: 'sugg' }, suggestions().map(([k, q]) => h('button', { type: 'button', onclick: () => ask(q) }, h('small', { text: k }), q)))));
    return;
  }
  for (const m of s.messages) box.append(msgNode(m));
  box.scrollTop = box.scrollHeight;
}
// night sweep 2026-11-27 #35: suggestions from what is open right now (worst open incidents first), then the general ones
let CTX = [];
function suggestions() {
  const out = [], rank = { critical: 3, sensor_fault: 2, warning: 1 };
  const open = CTX.filter((i) => i && i.workflow !== 'closed' && i.workflow !== 'resolved' && i.state !== 'running')
    .sort((a, b) => (rank[b.severity] || 0) - (rank[a.severity] || 0) || String(b.id).localeCompare(String(a.id), undefined, { numeric: true }));
  if (open[0]) {
    out.push(['Open now', 'What is happening in ' + open[0].id + ' and what should I do first?']);
    out.push(['Real or fault?', 'Is ' + open[0].id + ' a sensor fault or a real problem?']);
  }
  if (open[1]) out.push(['Open now', 'Explain ' + open[1].id + ' in simple words.']);
  if (open.length) out.push(['Right now', 'Which readings are critical or warning right now?']);
  for (const x of SUGG) if (out.length < 4) out.push(x);
  return out.slice(0, 4);
}
function loadContext() {
  api('/api/incidents?limit=40').then((l) => { CTX = Array.isArray(l) ? l : []; if (!S.session || !S.session.messages.length) renderChat(); }).catch(() => {});
}
let timer = null, poll = null;
function typing() {
  const t0 = Date.now(); let ta = Date.now(), waiting = '';
  const label = h('span', { text: STAGES[0][1] }); const secs = h('span', { text: '' });
  const node = h('div', { class: 'row bot', id: 'typing' }, h('div', { class: 'av', 'aria-hidden': 'true', text: '✦' }),
    h('div', { class: 'bub' }, h('div', { class: 'typing' }, h('span', { class: 'dots' }, h('i'), h('i'), h('i')), label, secs)));
  // queued behind an incident analysis or another question: the backend waits and answers by itself
  poll = setInterval(() => api('/api/chat/status').then((st) => {
    const w = (st && st.waiting_for) || '';
    if (waiting && !w) ta = Date.now();
    waiting = w;
  }).catch(() => {}), 1500);
  timer = setInterval(() => {
    const s = (Date.now() - ta) / 1000;
    label.textContent = waiting.startsWith('INC-') ? 'Queued: the AI is analysing ' + waiting + ' (alerts first). Your question goes next…'
      : waiting ? 'Queued behind another question…' : STAGES.filter(([at]) => s >= at).pop()[1];
    secs.textContent = ((Date.now() - t0) / 1000).toFixed(0) + ' s';
  }, 500);
  return node;
}
// streamDraft (chatstream.go): the answer appears word by word as a draft, tool look-ups as steps; the checked final
// answer from the reply replaces it. No EventSource (old WebView): the typing dots stay as before.
function streamDraft(sid, ty, box) {
  if (!window.EventSource) return null;
  let es; try { es = new EventSource('/api/events'); } catch (e) { return null; }
  const bub = ty.querySelector('.bub'); let draft = null, step = null;
  es.addEventListener('chat_piece', (e) => {
    let d; try { d = JSON.parse(e.data); } catch (x) { return; }
    if (!d || d.stream !== sid) return;
    if (d.step) {
      if (!step) { step = h('div', { class: 'cstep' }); bub.append(step); }
      step.textContent = d.step;
    }
    if (d.text) {
      if (!draft) { draft = h('div', { class: 'cdraft', 'aria-live': 'polite' }); bub.append(draft); const t = bub.querySelector('.typing'); if (t) t.classList.add('small'); }
      draft.textContent = d.text;
      box.scrollTop = box.scrollHeight;
    }
  });
  return es;
}
async function ask(q) {
  q = (q || '').trim(); if (!q || S.busy) return;
  const spoken = window.SPOKEN === true; window.SPOKEN = false; // set by voice.js only for a spoken question
  S.busy = true; $('#send').disabled = true; $('#q').value = ''; grow();
  // night sweep 2026-11-27 #119: an old status note (e.g. a voice error) goes once a new question is sent
  const vn = $('#voicenote'); if (vn) { vn.replaceChildren(); vn.hidden = true; }
  const box = $('#msgs');
  if (!S.session) box.replaceChildren();
  box.append(msgNode({ role: 'user', text: q })); const ty = typing(); box.append(ty); box.scrollTop = box.scrollHeight;
  const sid = 'cs' + Math.random().toString(36).slice(2, 10);
  const es = streamDraft(sid, ty, box);
  try {
    const s = await api('/api/chat', { method: 'POST', body: JSON.stringify({ session: S.id || '', message: q, spoken, stream: sid }) });
    S.session = s; S.id = s.id;
    if (spoken && window.speakAnswer) { const m = (s.messages || []).filter((x) => x.role === 'assistant' && !x.error).pop(); if (m) window.speakAnswer(m.text); }
  } catch (e) {
    ty.remove(); box.append(msgNode({ role: 'assistant', text: 'Could not reach the board: ' + e.message, error: true }));
  } finally {
    clearInterval(timer); clearInterval(poll); if (es) es.close(); S.busy = false; $('#send').disabled = false;
  }
  if (S.session) renderChat();
  loadSessions();
}

/* ------------------------------------------------------------ composer + chrome */
function grow() { const t = $('#q'); t.style.height = 'auto'; t.style.height = Math.min(140, t.scrollHeight) + 'px'; }
function openSide() { $('#side').classList.add('open'); $('#scrim').hidden = false; }
function closeSide() { $('#side').classList.remove('open'); $('#scrim').hidden = true; }
$('#form').addEventListener('submit', (e) => { e.preventDefault(); ask($('#q').value); });
$('#q').addEventListener('input', grow);
$('#q').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask($('#q').value); } });
$('#new').addEventListener('click', () => { newChat(); closeSide(); });
$('#menu').addEventListener('click', openSide);
$('#scrim').addEventListener('click', closeSide);
$('#clear').addEventListener('click', async () => {
  const b = $('#clear');
  if (b.dataset.arm !== '1') { b.dataset.arm = '1'; b.textContent = 'Tap again to delete all chats'; setTimeout(() => { b.dataset.arm = ''; b.textContent = 'Clear history'; }, 4000); return; }
  b.dataset.arm = ''; b.textContent = 'Clear history';
  try { await api('/api/chat/sessions/clear', { method: 'POST', body: '{}' }); } catch (e) { b.textContent = 'Could not clear: ' + e.message.slice(0, 40); setTimeout(() => { b.textContent = 'Clear history'; }, 3000); return; }
  newChat(); loadSessions();
});
$('#del').addEventListener('click', async () => {
  if (!S.id) return;
  try { await api('/api/chat/sessions/' + encodeURIComponent(S.id), { method: 'DELETE' }); } catch { /* already gone */ }
  newChat(); loadSessions();
});
api('/api/status').then((st) => { if (st && st.running_on) $('#sub').textContent = 'On-device AI · ' + st.running_on.split(',')[0]; }).catch(() => {});
renderChat(); loadSessions(); loadContext(); setTimeout(() => $("#q").focus(), 300);
/* keep the reasoner warm on the NPU while this page is in use (backend Warm: ~60 s after the last activity) */
let lastWarm = 0;
function warm() { if (Date.now() - lastWarm < 15000) return; lastWarm = Date.now(); fetch('/api/chat/warm', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'sce' }, body: '{}' }).catch(() => {}); }
warm();
addEventListener('focus', warm);
document.addEventListener('visibilitychange', () => { if (!document.hidden) warm(); });
$('#q').addEventListener('input', warm);
