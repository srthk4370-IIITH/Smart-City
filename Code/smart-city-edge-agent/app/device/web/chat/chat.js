/* Campus Assistant: a second frontend on the same edge-agent backend (backend/chat.go).
   Sessions live on the board (state/chats.json); this page lists them, shows one, and asks questions. */
'use strict';
const $ = (s) => document.querySelector(s);
const S = { id: null, sessions: [], session: null, busy: false };
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
  const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
const when = (t) => {
  const d = new Date(t * 1000), now = new Date();
  return d.toDateString() === now.toDateString() ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
};

/* answer text -> nodes: [INC-0123] and bare INC-0123 become chips linking to the dashboard */
function richText(s) {
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
function msgNode(m) {
  if (m.role === 'user') return h('div', { class: 'row user' }, h('div', { class: 'bub', text: m.text }));
  const toolsBox = h('div', { class: 'tools' }, (m.tools || []).map((t) => h('div', { class: 'tool' },
    h('div', {}, 'Checked ', h('b', { text: t.name }), ' ', h('span', { text: t.args && t.args !== '{}' ? t.args : '' })),
    h('code', { text: t.result }))));
  const meta = h('div', { class: 'meta' },
    m.tools && m.tools.length ? h('button', { type: 'button', class: 'how', onclick: () => toolsBox.classList.toggle('open') }, 'How I found this · ' + m.tools.length + ' lookup' + (m.tools.length > 1 ? 's' : '')) : null,
    m.queued_ms > 1500 ? h('span', { text: 'waited ' + (m.queued_ms / 1000).toFixed(0) + ' s for an alert analysis' }) : null,
    m.ms ? h('span', { text: ((m.ms - (m.queued_ms || 0)) / 1000).toFixed(1) + ' s on the NPU' }) : null);
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
      h('div', { class: 'sugg' }, SUGG.map(([k, q]) => h('button', { type: 'button', onclick: () => ask(q) }, h('small', { text: k }), q)))));
    return;
  }
  for (const m of s.messages) box.append(msgNode(m));
  box.scrollTop = box.scrollHeight;
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
async function ask(q) {
  q = (q || '').trim(); if (!q || S.busy) return;
  S.busy = true; $('#send').disabled = true; $('#q').value = ''; grow();
  const box = $('#msgs');
  if (!S.session) box.replaceChildren();
  box.append(msgNode({ role: 'user', text: q })); const ty = typing(); box.append(ty); box.scrollTop = box.scrollHeight;
  try {
    const s = await api('/api/chat', { method: 'POST', body: JSON.stringify({ session: S.id || '', message: q }) });
    S.session = s; S.id = s.id;
  } catch (e) {
    ty.remove(); box.append(msgNode({ role: 'assistant', text: 'Could not reach the board: ' + e.message, error: true }));
  } finally {
    clearInterval(timer); clearInterval(poll); S.busy = false; $('#send').disabled = false;
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
$('#del').addEventListener('click', async () => {
  if (!S.id) return;
  try { await api('/api/chat/sessions/' + encodeURIComponent(S.id), { method: 'DELETE' }); } catch { /* already gone */ }
  newChat(); loadSessions();
});
api('/api/status').then((st) => { if (st && st.running_on) $('#sub').textContent = 'On-device AI · ' + st.running_on.split(',')[0]; }).catch(() => {});
renderChat(); loadSessions(); setTimeout(() => $("#q").focus(), 300);
/* keep the reasoner warm on the NPU while this page is in use (backend Warm: ~60 s after the last activity) */
let lastWarm = 0;
function warm() { if (Date.now() - lastWarm < 15000) return; lastWarm = Date.now(); fetch('/api/chat/warm', { method: 'POST' }).catch(() => {}); }
warm();
addEventListener('focus', warm);
document.addEventListener('visibilitychange', () => { if (!document.hidden) warm(); });
$('#q').addEventListener('input', warm);
