/* Smart City Edge - dashboard. Plain JS, no external dependencies, works offline.
   Sections: helpers - icons - state - header/theme - data refresh - hero - live - sensor sheet + charts -
   incidents (cards, tracking, detail, streaming) - sensors - map - about - navigation - SSE - boot */
'use strict';
(() => {

/* ============================== helpers ============================== */
const NS = 'http://www.w3.org/2000/svg';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
function h(tag, a, ...kids) {
  const e = tag === 'svg' ? document.createElementNS(NS, 'svg') : document.createElement(tag);
  if (a) for (const k in a) {
    const v = a[k];
    if (v == null || v === false) continue;
    if (k === 'class') e.setAttribute('class', v);
    else if (k === 'text') e.textContent = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(3)) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}
const fill = (el, ...kids) => el.replaceChildren(...kids.flat(3).filter((k) => k != null && k !== false));
const setText = (e, s) => { s = String(s); if (e.textContent !== s) e.textContent = s; };
const setCls = (e, c) => { if (e.getAttribute('class') !== c) e.setAttribute('class', c); };
const setAttr = (e, k, v) => { if (e.getAttribute(k) !== v) e.setAttribute(k, v); };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad = (n) => String(n).padStart(2, '0');
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const istParts = (e) => new Date((e + 19800) * 1000);
const hm = (e) => { const d = istParts(e); return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); };
const dhm = (e) => { const d = istParts(e); return pad(d.getUTCDate()) + ' ' + MON[d.getUTCMonth()] + ' ' + hm(e); };
const nice = (s) => (s == null || s === '' ? '-' : String(s).replace(/_/g, ' '));
function fmt(v) {
  if (v == null || typeof v !== 'number' || !isFinite(v)) return '-';
  const a = Math.abs(v);
  return a >= 1000 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : a >= 1 ? v.toFixed(2) : v.toFixed(3);
}
const pct = (c) => (c == null ? '-' : Math.round(c * 100) + '%');
const key = (n, m) => n + ':' + m;
const roleTitle = { air_quality: 'Air Quality', water: 'Water', power: 'Power', occupancy: 'Occupancy', weather: 'Weather', hvac: 'HVAC' };
const roleShort = { air_quality: 'Air', water: 'Water', power: 'Power', occupancy: 'Occupancy', weather: 'Weather', hvac: 'HVAC' };
const ROLE_ORDER = ['air_quality', 'water', 'power', 'occupancy', 'weather', 'hvac'];
const ROLE_COLOR = { air_quality: '#4f8cf0', water: '#14a3c7', power: '#f29b00', occupancy: '#9b5de5', weather: '#2fb26a', hvac: '#6b7bd6', multi: '#ef4f45' };
const STATUS_LABEL = { normal: 'Normal', warning: 'Warning', critical: 'Critical', sensor_fault: 'Sensor fault', insufficient_data: 'Not enough data', no_data: 'No data', none: 'No data', info: 'Info' };
const STATUS_GLYPH = { normal: '●', warning: '▲', critical: '■', sensor_fault: '◆', insufficient_data: '○', no_data: '○', none: '○', info: '●' };
const stClass = (s) => 'st-' + (s || 'none');
const isGrey = (st) => st === 'insufficient_data' || st === 'no_data' || !st;
const sevRank = (s) => ({ critical: 3, sensor_fault: 2, warning: 1 }[s] || 0);
function pill(status, extra) {
  return h('span', { class: 'pill ' + stClass(status) + (extra ? ' ' + extra : '') }, STATUS_GLYPH[status] || '○', ' ', STATUS_LABEL[status] || nice(status));
}
function toast(msg, err) {
  const t = h('div', { class: 'toast' + (err ? ' err' : ''), text: msg });
  const box = $('#toasts');
  while (box.children.length >= 2) box.firstElementChild.remove(); // at most 2 toasts on screen
  box.append(t);
  setTimeout(() => t.remove(), err ? 6000 : 3000);
}
async function api(path, opt) {
  const r = await fetch(path, opt);
  if (!r.ok) { const t = await r.text().catch(() => ''); throw new Error((t || r.statusText || 'HTTP ' + r.status).trim()); }
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r.text();
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

/* ============================== icons ============================== */
const IC = {
  live: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  incidents: '<path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  sensors: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  map: '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
  about: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  restart: '<path d="M4 4v6h6"/><path d="M5.5 15a8 8 0 1 0 1.5-8.5L4 10"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  check: '<path d="M5 13l4 4 10-10"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
  bell: '<path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  air_quality: '<path d="M3 8h11a3 3 0 1 0-3-3"/><path d="M3 12h15a3 3 0 1 1-3 3"/><path d="M3 16h8"/>',
  water: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
  power: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  occupancy: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  weather: '<path d="M7 18a4 4 0 0 1 0-8 5 5 0 0 1 9.6-1A4.5 4.5 0 0 1 17 18z"/>',
  hvac: '<path d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5L4.2 16.5"/>',
  multi: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  eng: '<path d="M8 9l-4 3 4 3M16 9l4 3-4 3M13.5 6l-3 12"/>',
};
function icon(name, size) {
  const s = document.createElementNS(NS, 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
  s.setAttribute('stroke-width', '2'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
  s.setAttribute('aria-hidden', 'true');
  if (size) { s.setAttribute('width', size); s.setAttribute('height', size); }
  s.innerHTML = IC[name] || IC.info;
  return s;
}
const PI = { // 16px pattern glyphs
  spike: '<path d="M1 13h4l3-10 3 10h4"/>', dip: '<path d="M1 3h4l3 10 3-10h4"/>',
  gradual_increase: '<path d="M2 13L14 3M9 3h5v5"/>', gradual_decrease: '<path d="M2 3l12 10M9 13h5V8"/>',
  step_increase: '<path d="M1 13h5V8h5V3h4"/>', step_decrease: '<path d="M1 3h5v5h5v5h4"/>',
  exponential_increase: '<path d="M1 14C8 14 11 10 14 2M10 2h4v4"/>', oscillation: '<path d="M1 8c2-8 4-8 6 0s4 8 8 0"/>',
  throttling: '<path d="M1 14L7 4h8"/>', flatline: '<path d="M1 8h14"/>', erratic: '<path d="M1 9l2-6 2 9 2-7 2 8 2-9 2 6 2-3"/>',
  stable: '<path d="M1 6h14M1 10h14"/>', vacant: '<circle cx="8" cy="8" r="5"/>', occupied: '<circle cx="8" cy="8" r="5" style="fill:currentColor"/>',
  arrival: '<path d="M2 8h11M9 4l4 4-4 4"/>', departure: '<path d="M14 8H3M7 4L3 8l4 4"/>',
  intermittent: '<path d="M1 12V5h4v7h3V5h4v7h3"/>', off_hours_presence: '<path d="M12 10A6 6 0 1 1 7 2a5 5 0 0 0 5 8z"/>',
};
const patIcon = (p) => `<svg class="pi" viewBox="0 0 16 16" aria-hidden="true">${PI[p] || '<circle cx="8" cy="8" r="2"/>'}</svg>`;
function tabIcons() {
  const labels = { sensors: 'Sensors', live: 'Live', incidents: 'Incidents', map: 'Map', about: 'About' };
  $$('#rail a').forEach((a) => {
    const v = a.dataset.view;
    a.append(icon(v), h('span', { text: labels[v] }));
    if (v === 'incidents') a.append(h('span', { class: 'cnt', id: 'n-inc' }));
  });
}

/* ============================== state ============================== */
const S = {
  status: null, live: null, topo: null, incs: [], incId: null, incText: '', inc: null,
  view: 'sensors', sensorMap: new Map(), drawer: null, open: new Set(), draft: {}, sse: false,
  pendingNewest: null, lastLiveEv: 0, lastLive: 0, lastStatus: 0, lastDrawer: 0, lastIncList: 0,
  filter: 'all', incFilter: 'all', stream: {}, cardStream: {}, autoOpened: {}, trkPct: {}, modeTimer: 0, fold: {},
  health: null, simNow: 0, lastHealth: 0, eng: false,
  // UX v34: checklist "not needed" form, footer close/dismiss form, sensor history cache, list filters
  ckNN: null, footForm: null, hist: {}, histReq: {}, incQ: '', incDom: 'all', incDate: 'any', grpOpen: new Set(),
};

/* ============================== theme + segmented ============================== */
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  const b = $('#theme'); b.replaceChildren(icon(t === 'dark' ? 'sun' : 'moon'));
}
function bindTheme() {
  applyTheme(document.documentElement.getAttribute('data-theme') || 'light');
  $('#theme').onclick = () => {
    const t = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('sce-theme', t); } catch (e) { /* private mode */ }
    applyTheme(t);
  };
}
/* Engineering view: modes, NPU/model badges, evidence ids, prompts and pipeline steps for evaluators and
   engineers. Off by default so an operator sees plain language; one tap (header or About) shows it all. */
function applyEng(on) {
  S.eng = !!on;
  document.body.classList.toggle('eng', S.eng);
  const b = $('#eng'); if (b) { b.setAttribute('aria-pressed', S.eng ? 'true' : 'false'); b.classList.toggle('on', S.eng); }
  const sw = $('#eng-sw'); if (sw) sw.setAttribute('aria-checked', S.eng ? 'true' : 'false');
}
function setEng(on) {
  try { localStorage.setItem('sce-eng', on ? '1' : '0'); } catch (e) { /* private mode */ }
  applyEng(on);
  if (S.inc) renderIncDetail();
  if (FS.ref) renderSensorSheet(true);
  if (S.drawer && S.drawer.data) renderDrawer();
  toast(on ? 'Engineering view on: modes, models and evidence shown' : 'Engineering view off');
}
function bindEng() {
  let on = false; try { on = localStorage.getItem('sce-eng') === '1'; } catch (e) { /* private mode */ }
  $('#eng').replaceChildren(icon('eng'));
  $('#eng').onclick = () => setEng(!S.eng);
  const sw = $('#eng-sw'); if (sw) sw.onclick = () => setEng(!S.eng);
  applyEng(on);
}
function initSeg(seg) {
  if (!$('.thumb', seg)) seg.prepend(h('i', { class: 'thumb' }));
}
function setSeg(seg, value) {
  initSeg(seg);
  const btns = $$('button', seg);
  const i = btns.findIndex((b) => +b.dataset.v === value);
  seg.style.setProperty('--n', btns.length);
  seg.style.setProperty('--i', Math.max(i, 0));
  $('.thumb', seg).style.opacity = i < 0 ? 0 : 1;
  btns.forEach((b, k) => { b.classList.toggle('on', k === i); b.setAttribute('aria-pressed', k === i ? 'true' : 'false'); });
}
function makeSeg(items, onPick, label) {
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': label || '' },
    items.map((it) => h('button', { type: 'button', 'data-v': it.v, text: it.t, onclick: () => onPick(it.v) })));
  initSeg(seg); return seg;
}

/* ============================== header / mode ============================== */
const MODE_EXP = {
  1: 'Rules: statistics and a rule engine decide. No AI model is used.',
  2: 'Single: one on-device AI call reads all flagged sensors and writes the report.',
  3: 'Multi-Agent: one AI agent per sensor on the NPU, then a synthesizer writes the cross-domain report.',
};
function renderMode() {
  const m = S.status && S.status.mode;
  setSeg($('#m-seg'), m);
  setText($('#m-exp'), MODE_EXP[m] || '');
}
function showModeExp(auto) {
  const e = $('#m-exp'), b = $('#m-info');
  e.classList.add('show'); b.setAttribute('aria-expanded', 'true');
  clearTimeout(S.modeTimer);
  if (auto) S.modeTimer = setTimeout(() => { e.classList.remove('show'); b.setAttribute('aria-expanded', 'false'); }, 4500);
}
function bindHeader() {
  $$('#m-seg button').forEach((b) => b.onclick = async () => {
    try {
      await post('/api/mode', { mode: +b.dataset.v }); S.status.mode = +b.dataset.v; renderMode(); showModeExp(true);
    } catch (e) { toast('Mode: ' + e.message, true); }
  });
  $('#m-info').replaceChildren(icon('info'));
  $('#m-info').onclick = () => {
    const e = $('#m-exp');
    if (e.classList.contains('show')) { clearTimeout(S.modeTimer); e.classList.remove('show'); $('#m-info').setAttribute('aria-expanded', 'false'); } else showModeExp(false);
  };
  initSeg($('#m-seg'));
}

/* ============================== data refresh ============================== */
async function refreshStatus() {
  try { S.status = await api('/api/status'); S.lastStatus = Date.now(); renderStatus(); } catch (e) { /* offline */ }
}
let liveBusy = false;
async function refreshLive() {
  if (liveBusy) return; liveBusy = true;
  try { S.live = await api('/api/live'); S.lastLive = Date.now(); indexLive(); renderLive(); renderMapColors(); updateHero(); } catch (e) { /* ignore */ }
  liveBusy = false;
}
function indexLive() {
  S.sensorMap = new Map();
  for (const r in S.live.roles) for (const s of S.live.roles[r].sensors) S.sensorMap.set(key(s.node, s.metric), s);
}
async function refreshIncidents() {
  try {
    const l = await api('/api/incidents?limit=300');
    // numeric: 'INC-10000' must sort above 'INC-9999'. The newest 300 are plenty for a phone list;
    // older incidents stay in the store and the archive.
    S.incs = (Array.isArray(l) ? l : []).sort((a, b) => (+b.id.slice(4) || 0) - (+a.id.slice(4) || 0));
    S.lastIncList = Date.now();
    renderIncList();
    shiftSummary(); // "Since 14:05: 2 new · 1 got worse · 1 resolved" (once per opening)
    renderHealth(); // tiles count decisions still owed per domain
    if (S.pendingNewest) {
      const nw = S.incs.find((i) => !S.pendingNewest.has(i.id));
      if (nw) { S.pendingNewest = null; closeSheet('sheet'); location.hash = '#incidents'; selectIncident(nw.id); }
    }
  } catch (e) { /* ignore */ }
}
async function refreshIncDetail(force) {
  if (!S.incId) return;
  const id = S.incId;
  try {
    const t = await api('/api/incidents/' + encodeURIComponent(id));
    if (id !== S.incId) return;
    const txt = typeof t === 'string' ? t : JSON.stringify(t);
    if (!force && txt === S.incText) return;
    S.incText = txt; S.inc = typeof t === 'string' ? JSON.parse(t) : t;
    renderIncDetail();
  } catch (e) { $('#inc-detail').replaceChildren(h('div', { class: 'empty', text: 'Could not load ' + id + ': ' + e.message })); }
}

/* ============================== status -> header, hero ============================== */
function renderStatus() {
  const st = S.status; if (!st) return;
  const rp = st.replay || {};
  setText($('#c-time'), (st.sim_time_ist || '-').replace(/^\w+ \d+ \w+ \d+ /, '') + ' IST');
  setAttr($('#c-time'), 'title', 'Sensor time: ' + (st.sim_time_ist || '-'));
  setText($('#l-sub'), 'Sensor time ' + (st.sim_time_ist || '-') + ' IST');
  if (rp.poll_ms && SN.pollSeg && rp.poll_ms !== SN.pollMs) { SN.pollMs = rp.poll_ms; setSeg(SN.pollSeg, rp.poll_ms); }
  renderMode();
  updateHero();
  setBadge();
  renderAboutModel();
}
// the Incidents tab badge counts decisions waiting (what the operator owes), not every incident ever
function setBadge() {
  const n = (S.incs || []).filter((i) => wfOfI(i) === 'needs_decision').length;
  const b = $('#n-inc'); if (!b) return;
  setText(b, n ? n : '');
  setAttr(b, 'aria-label', n ? n + ' decision' + (n === 1 ? '' : 's') + ' waiting' : '');
}
const H = {};
function buildHero() {
  H.ico = h('div', { class: 'hero-ico' }); H.t = h('div', { class: 'hero-h', text: 'Checking campus ...' }); H.s = h('div', { class: 'hero-s' });
  const stat = (k, lbl) => { const b = h('b', { text: '-' }); H[k] = b; return h('div', { class: 'hstat' }, b, h('span', { text: lbl })); };
  H.npuDot = h('i', { class: 'dot' }); H.npuT = h('span');
  H.npu = h('span', { class: 'hbadge', title: 'Qualcomm Hexagon NPU' }, H.npuDot, H.npuT);
  H.modelDot = h('i', { class: 'dot' }); H.modelT = h('span');
  H.model = h('span', { class: 'hbadge' }, H.modelDot, H.modelT);
  H.thermDot = h('i', { class: 'dot' }); H.thermT = h('span'); H.therm = h('span', { class: 'hbadge' }, H.thermDot, H.thermT);
  H.runDot = h('i', { class: 'dot' }); H.runT = h('span'); H.run = h('span', { class: 'hbadge' }, H.runDot, H.runT);
  H.mem = h('span', { class: 'hbadge' });
  $('#hero').append(h('div', { class: 'hero' },
    h('div', { class: 'hero-top' }, H.ico, h('div', {}, H.t, H.s)),
    h('div', { class: 'hero-stats' }, stat('sCrit', 'Critical'), stat('sWarn', 'Warnings'), stat('sFault', 'Faults'), stat('sTot', 'Sensors')),
    h('div', { class: 'hero-sys eng-only' }, H.npu, H.model, H.therm, H.run, H.mem)));
}
function updateHero() {
  if (!H.ico) return;
  let crit = 0, warn = 0, fault = 0, tot = 0, worst = 'normal';
  if (S.health && Array.isArray(S.health.domains)) for (const d of S.health.domains) {
    if (d.context_only) continue;
    const c = d.counts || {}; crit += c.critical || 0; warn += c.warning || 0; fault += c.sensor_fault || 0; tot += d.sensors || 0;
  } else if (S.live) for (const r in S.live.roles) {
    if (r === 'hvac') continue;
    for (const s of S.live.roles[r].sensors) {
      tot++;
      if (s.status === 'critical') crit++; else if (s.status === 'warning') warn++; else if (s.status === 'sensor_fault') fault++;
    }
  }
  if (crit) worst = 'critical'; else if (warn) worst = 'warning'; else if (fault) worst = 'sensor_fault';
  const title = !S.live ? 'Checking campus ...' : crit ? 'Action needed' : warn ? 'A few things to watch' : fault ? 'Some sensors need a check' : 'All clear';
  const sub = !S.live ? '' : crit ? crit + ' critical reading' + (crit === 1 ? '' : 's') + ' right now' : warn ? warn + ' reading' + (warn === 1 ? '' : 's') + ' above normal' : fault ? fault + ' sensor' + (fault === 1 ? ' looks' : 's look') + ' faulty or stuck' : 'Everything is within normal range';
  setCls(H.ico, 'hero-ico ' + stClass(worst));
  const want = worst === 'normal' ? 'shield' : worst === 'critical' ? 'bell' : 'alert';
  if (H.ico.dataset.i !== want) { H.ico.dataset.i = want; H.ico.replaceChildren(icon(want)); }
  setText(H.t, title); setText(H.s, sub);
  setText(H.sCrit, crit); setText(H.sWarn, warn); setText(H.sFault, fault); setText(H.sTot, tot);
  const st = S.status; if (!st) return;
  const n = st.npu || {};
  setText(H.npuT, 'NPU ' + (n.errors > 0 ? 'errors ' + n.errors : n.busy ? 'busy' : 'idle') + (n.queue ? ' · q' + n.queue : '') + (n.last_latency_ms ? ' · ' + Math.round(n.last_latency_ms) + ' ms' : ''));
  setCls(H.npuDot, 'dot ' + (n.errors > 0 ? 'crit' : n.busy ? 'busy' : 'ok'));
  setCls(H.npu, 'hbadge' + (n.errors > 0 ? ' err' : ''));
  setAttr(H.npu, 'title', 'NPU calls: ' + n.calls + ', errors: ' + n.errors + (n.last_error ? ', last error: ' + n.last_error : ''));
  const am = (st.models || {}).agent || {}, ft = !!am.fine_tuned, tuned = (st.models || {}).tuned || {};
  setText(H.modelT, ft ? 'Fine-tuned agent model' : 'Base Llama 3.2 3B · fallback');
  setCls(H.modelDot, 'dot ' + (ft ? 'ok' : 'warn')); setCls(H.model, 'hbadge ' + (ft ? 'good' : 'fallback'));
  setAttr(H.model, 'title', [am.name, am.note, ft ? '' : 'Fine-tuned bundle available: ' + (tuned.available ? 'yes' : 'no') + (tuned.note ? ' (' + tuned.note + ')' : ''), am.available === false ? 'Model NOT available' : ''].filter(Boolean).join(' | '));
  const dv = st.device || {}, npuC = dv.npu_c || dv.thermal_max_c || 0, skinC = dv.skin_c || 0;
  const hot = !!dv.thermal_guard;
  setText(H.thermT, hot ? 'Cooling down · AI paused' : (npuC || skinC) ? 'NPU ' + Math.round(npuC) + '° · skin ' + Math.round(skinC) + '°C' : 'Thermals n/a');
  setCls(H.thermDot, 'dot ' + (hot ? 'warn' : (npuC || skinC) ? 'ok' : '')); setCls(H.therm, 'hbadge' + (hot ? ' fallback' : ''));
  setAttr(H.therm, 'title', hot ? 'Thermal guard active: AI analysis is deferred until the device cools down (rules stay active).' : 'NPU junction and skin temperature');
  const ro = st.running_on || '', onQidk = /qidk|qualcomm|android/i.test(ro);
  setText(H.runT, onQidk ? 'Running on QIDK — standalone, no laptop' : 'Running on: ' + (ro || 'unknown host'));
  setCls(H.runDot, 'dot ' + (onQidk ? 'ok' : 'warn')); setAttr(H.run, 'title', 'running_on: ' + ro);
  setText(H.mem, dv.mem_available_mb != null ? (dv.mem_available_mb >= 1024 ? (dv.mem_available_mb / 1024).toFixed(1) + ' GB' : dv.mem_available_mb + ' MB') + ' free' : '');
  H.mem.style.display = dv.mem_available_mb != null ? '' : 'none';
}

/* ----- plain language ----- */
/* Operator wording (proofs/2026-10-21_ux/UX_RESEARCH.md). Every screen leads with plain words; the
   engineering terms (patterns, evidence ids, modes, NPU, agents) stay available behind "Technical
   details" or the Engineering view. These maps only translate enums the backend already emits. */
const METRIC_NAME = { co2: 'CO2', pm25: 'PM2.5', pm10: 'PM10', temp: 'Temperature', rh: 'Humidity', level: 'Tank level', flow: 'Water flow',
  tds: 'Water TDS', ph: 'Water pH', power_kw: 'Power', pf: 'Power factor', wind: 'Wind speed', occ: 'Occupancy', ac_units_on: 'AC units on',
  room_temp: 'Room temperature', setpoint: 'AC setpoint', ac_on: 'AC running' };
const metricName = (m) => METRIC_NAME[m] || nice(m);
// "KH building, level 98, water tank level sensor 00" -> "KH-98 tank"; the full location stays in title / detail
function placeShort(loc) {
  const s = String(loc || '');
  let m = /^(\w+) substation/i.exec(s);
  if (m) return m[1] + ' substation';
  m = /^(\w+) building(?:, level (\w+))?(?:, (.*))?$/i.exec(s);
  if (!m) return s.length > 24 ? s.slice(0, 23) + '…' : s;
  const code = m[1] + (m[2] ? '-' + m[2] : ''), rest = (m[3] || '').replace(/\s*\(.*\)\s*$/, '');
  let q = '', k;
  if (/outdoor/i.test(rest)) q = 'outdoor';
  else if (/rooftop/i.test(rest)) q = 'rooftop';
  else if ((k = /AC indoor unit (\d+)/i.exec(rest))) q = 'AC unit ' + k[1];
  else if (/AC units/i.test(rest)) q = 'AC';
  else if ((k = /^room (?:occupancy sensor|energy meter) (\d+)/i.exec(rest))) q = 'room ' + k[1];
  else if (/water tank/i.test(rest)) q = 'tank';
  return q ? code + ' ' + q : code;
}
const sensorLabel = (metric, loc) => metricName(metric) + ' · ' + placeShort(loc);
const PATTERN_PLAIN = { spike: 'had a brief spike', dip: 'had a brief dip', gradual_increase: 'rising steadily', gradual_decrease: 'falling steadily',
  step_increase: 'jumped up and stayed', step_decrease: 'dropped and stayed down', exponential_increase: 'rising faster and faster',
  oscillation: 'swinging up and down', throttling: 'flattened at a cap', flatline: 'stuck at one value', erratic: 'jumping around irregularly',
  stable: 'steady', vacant: 'empty', occupied: 'occupied', arrival: 'people arriving', departure: 'people leaving', intermittent: 'occupied on and off',
  off_hours_presence: 'occupied out of hours', too_hot: 'too hot', too_cold: 'too cold', slow_recovery: 'slow to cool down', no_cooling_effect: 'not cooling',
  short_cycling: 'switching on and off too often', stuck_on: 'stuck on', stuck_off: 'stuck off', running_empty_room: 'running in an empty room',
  unit_alarm: 'reporting a unit alarm', normal_cycling: 'cycling normally', pull_down: 'cooling the room down', setback_drift: 'drifting after setback',
  bias_jump: 'reading jumped by an offset (sensor)', biased_reading: 'reading offset (sensor)', calibration_drift: 'drifting off calibration (sensor)',
  dropout: 'readings dropping out', saturation: 'maxed out (sensor)', quantised: 'reading in coarse steps (sensor)',
  stuck: 'stuck at one value', bias: 'reading offset (sensor)', drift: 'drifting off calibration (sensor)', noise: 'noisy readings (sensor)',
  slow_drift: 'drifting slowly', level_shift: 'shifted to a new level and stayed',
  warning: 'above normal', critical: 'at a critical level', sensor_fault: 'faulty', context: 'shown for context' };
const patternPlain = (p) => PATTERN_PLAIN[p] || nice(p);
const STEADY = { stable: 1, normal_cycling: 1, context: 1 }; // shapes that say nothing about level
const CAUSE_PLAIN = { normal_conditions: 'normal conditions', occupancy_load: 'many people in the room', ventilation_insufficient: 'not enough fresh air',
  outdoor_pollution_ingress: 'outdoor pollution getting in', indoor_emission_source: 'a source of fumes or dust indoors', hvac_cooling_issue: 'the AC not cooling properly',
  humidity_control_issue: 'humidity not being controlled', sensor_fault: 'a faulty sensor', normal_usage: 'normal use', high_demand: 'high water demand',
  possible_leak: 'a possible leak', tank_filling: 'the tank filling', tank_draining: 'the tank draining', supply_interruption: 'the water supply being interrupted',
  pump_cycling: 'the pump switching on and off', water_quality_issue: 'a water quality problem', tank_overflow_risk: 'the tank may overflow',
  fill_valve_stuck: 'the tank fill valve may be stuck', normal_load: 'normal load', load_surge: 'a sudden load surge', equipment_startup: 'equipment starting up',
  load_drop_or_outage: 'a load drop or outage', capacity_limit_throttling: 'the load hitting a capacity limit', gradual_load_growth: 'load slowly growing',
  cyclic_equipment: 'equipment cycling', power_quality_issue: 'poor power quality', normal_weather: 'normal weather', heat_buildup: 'heat building up',
  cooling_trend: 'it is cooling down', weather_front: 'a weather front', gusty_wind: 'gusty wind', diurnal_cycle: 'the normal day/night cycle',
  vacant: 'the room is empty', normal_occupancy: 'normal occupancy', arrival: 'people arriving', departure: 'people leaving',
  intermittent_presence: 'people coming and going', off_hours_presence: 'someone present out of hours', normal_operation: 'normal operation',
  scheduled_off: 'the unit is off as scheduled', high_heat_load: 'a high heat load', ac_not_cooling: 'the AC not cooling', overcooling: 'the room being overcooled',
  ac_off_heat_gain: 'the room heating up with the AC off', short_cycling_control: 'the AC control switching too often', schedule_or_control_fault: 'a schedule or control fault',
  unit_not_starting: 'the unit not starting', unoccupied_running: 'the AC running in an empty room', unit_alarm: 'a unit alarm' };
const causePlain = (c) => CAUSE_PLAIN[c] || nice(c);
// mirrors domainhealth.go actionStep: a recommendation for a person; the app switches nothing
const ACTION_TEXT = { none: 'No action needed', monitor: 'Keep watching the flagged readings; no on-site action yet',
  inspect_ventilation: 'Ask facilities to inspect ventilation (fresh-air dampers, AHU fan) in the affected area',
  inspect_hvac: 'Ask facilities to inspect the HVAC unit (setpoint, compressor, filters)',
  check_sensor: 'Check the flagged sensor on site (power, mounting, calibration) before trusting it',
  inspect_water_system: 'Inspect the water system: tank, pumps, valves and pipes for leaks',
  inspect_electrical: 'Ask an electrician to inspect the feeder and panel of the flagged meter',
  review_schedule: 'Review the occupancy and equipment schedule for the area',
  request_facility_review: 'Raise a facility review with the incident\'s evidence',
  switch_off_ac: 'Switch off the AC in the empty room (your decision; the app switches nothing)' };
const actionText = (a) => ACTION_TEXT[a] || nice(a);
// why it matters, by the report label (cause -> consequence, ISA-18.2 alarm rationale)
const LABEL_IMPACT = {
  ventilation_issue: 'Stale air (high CO2) makes people drowsy and is a sign ventilation is not keeping up.',
  hvac_or_thermal_issue: 'Rooms may become uncomfortable and the AC may waste energy.',
  occupancy_driven_load: 'More people than usual are driving up air and power use.',
  air_pollution_event: 'Dust can get into the buildings; people with breathing problems may be affected.',
  water_leak_or_overuse: 'Water is being lost or used faster than normal; the tank can run dry.',
  water_supply_issue: 'The building\'s water supply may be interrupted, or the tank may overflow.',
  water_quality_issue: 'The water may not be safe to drink until it is checked.',
  power_load_anomaly: 'Unusual electrical load can trip breakers or overheat equipment.',
  power_quality_issue: 'Poor power quality wastes energy and can damage equipment.',
  weather_driven: 'The weather is changing cooling load and indoor comfort.',
  sensor_fault: 'A faulty sensor can hide a real problem: its readings cannot be trusted until it is checked.',
  normal_operation: 'Nothing abnormal was confirmed. Dismiss it with a short note if you agree.',
  unknown: 'The cause is unclear, so a person should take a look.' };
const DOMAIN_IMPACT = { air_quality: 'Air quality affects the health and comfort of people in the room.', water: 'Water problems can cut supply or waste water.',
  power: 'Power problems can trip equipment or waste energy.', occupancy: 'Unexpected presence can be a security or energy issue.',
  weather: 'Weather changes the load on cooling and drainage.', hvac: 'AC problems affect comfort and energy use.' };
// confidence as a word; the number stays one tap away (People + AI Guidebook: categories over raw scores)
function confWord(c) {
  if (typeof c !== 'number' || !isFinite(c)) return { w: 'Unknown', k: 'none' };
  return c >= 0.8 ? { w: 'High', k: 'high' } : c >= 0.6 ? { w: 'Medium', k: 'med' } : { w: 'Low', k: 'low' };
}
// model text without evidence ids and pipeline notes ("[E9]", "(S2)", "(from domain agent finding)")
const stripRefs = (t) => String(t || '').replace(/\s*\[[^\]]*\]/g, '').replace(/\s*\((?:S\d+(?:\.E\d+)?(?:,\s*)?)+\)/g, '')
  .replace(/\s*\(from [^)]*\)/gi, '').replace(/\s+([.,;])/g, '$1').replace(/\s{2,}/g, ' ').trim();
// model sentences -> one paragraph: evidence ids stripped, each sentence closed with punctuation
function joinSentences(list) {
  return (list || []).map(stripRefs).filter(Boolean).map((t) => t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? '' : '.')).join(' ');
}
// the reasoner/rule title -> one plain headline ("Tank level falling slowly · KH-98 tank")
function plainTitle(t) {
  const s = String(t || '');
  let m = /^(\d+) sensors (?:alarming|confirmed): (.*)$/.exec(s);
  if (m) return m[1] + ' sensors need attention: ' + m[2];
  m = /^All clear: (\d+) sensors checked/.exec(s);
  if (m) return 'All clear: ' + m[1] + ' sensors checked, nothing wrong';
  m = /^(.*?)\s*judged normal: (.+)$/.exec(s);
  if (m) return (m[1].trim() || 'Sensor') + ' checked: normal · ' + placeShort(m[2]);
  m = /^([^:]+): (.+ (?:building|substation).*)$/.exec(s);
  if (!m) return s;
  const head = m[1], place = placeShort(m[2]);
  let name = '', rest = head;
  for (const v of Object.values(METRIC_NAME).concat(['Temperature', 'Humidity', 'Power', 'Flow'])) {
    if (head.toLowerCase().startsWith(v.toLowerCase() + ' ') && v.length > name.length) { name = v; rest = head.slice(v.length + 1); }
  }
  if (!name) return head + ' · ' + place;
  const r0 = rest.trim(), paren = (/\s*(\([^)]*\))$/.exec(r0) || [])[1] || '', p = r0.replace(/\s*\([^)]*\)$/, '').replace(/ /g, '_');
  return name + ' ' + (PATTERN_PLAIN[p] ? PATTERN_PLAIN[p] + (paren ? ' ' + paren : '') : r0) + ' · ' + place;
}
/* ----- end plain language ----- */

/* ----- domain health ----- */
/* Level-1 overview (ISA-101): one tile per domain, worst first, grey when normal, colour + glyph + word
   when not. A tile says what the state is, since when, what changed and the one thing to do now; a tap
   opens the domain (Level 2: open incidents, all steps, its sensors). GET /api/health, SSE "health";
   backend domainhealth.go. */
// approval lifecycle (workflow.go): glyph + word, never colour alone
const WF_WORD = { analysing: { g: '◌', w: 'Analysing' }, needs_decision: { g: '●', w: 'Needs decision' }, in_progress: { g: '▶', w: 'In progress' },
  resolved: { g: '✓', w: 'Resolved' }, closed: { g: '◻', w: 'Closed' }, interrupted: { g: '○', w: 'Interrupted' } };
// data quality (dataquality.go): good | uncertain | bad | stale | maintenance
const Q_WORD = { uncertain: 'Data uncertain', bad: 'Data unusable', stale: 'Not reporting', maintenance: 'Out of service' };
const qGlyph = (q) => (q === 'maintenance' ? '⊘' : '◆');
function qualityChip(s) {
  const q = s && s.quality; if (!q || q === 'good' || !Q_WORD[q]) return null;
  return h('span', { class: 'qchip q-' + q, title: s.quality_reason || Q_WORD[q] }, h('i', { 'aria-hidden': 'true', text: qGlyph(q) }), Q_WORD[q]);
}
// the reason one tap away (sheets): a button that shows / hides it
function qualityBtn(s, k) {
  const q = s && s.quality; if (!q || q === 'good' || !Q_WORD[q]) return null;
  const open = S.qOpen === k, id = 'qr-' + String(k).replace(/[^\w-]/g, '_');
  return h('span', { class: 'qwrap' }, h('button', { type: 'button', class: 'qchip q-' + q, 'aria-expanded': open ? 'true' : 'false', 'aria-controls': id,
    onclick: (e) => { S.qOpen = open ? null : k; const b = e.currentTarget, r = b.nextSibling; b.setAttribute('aria-expanded', open ? 'false' : 'true'); if (r) r.hidden = open; } },
  h('i', { 'aria-hidden': 'true', text: qGlyph(q) }), Q_WORD[q]), h('span', { class: 'qreason', id, hidden: open ? null : true, text: s.quality_reason || Q_WORD[q] }));
}
const DH_WORD = { normal: 'Normal', warning: 'Warning', critical: 'Critical', sensor_fault: 'Sensor problem', insufficient_data: 'Starting up', none: 'Info only' };
const DH_HINT = { critical: 'act now', warning: 'check soon', sensor_fault: 'readings unreliable', insufficient_data: 'collecting readings' };
const DH_RANK = { critical: 5, warning: 4, sensor_fault: 3, insufficient_data: 2, normal: 1, none: 0 };
const DH_NAME = { air_quality: 'Air quality', water: 'Water', power: 'Power', occupancy: 'Occupancy', weather: 'Weather', hvac: 'HVAC' };
const DH_SRC = { report: 'AI report', agent: 'Domain agent', playbook: 'Standard playbook' };
const DH_STAGE = { provisional: 'provisional', early: 'early', '1.5h': '1.5 h', '3h': '3 h' };
function dhAgo(sec) {
  if (!(sec >= 0) || sec < 60) return 'under 1 min';
  const m = Math.floor(sec / 60);
  return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
}
function healthModel(d, now) {
  const lv = d.context_only ? 'none' : (d.headline || 'normal');
  const word = DH_WORD[lv] || nice(lv), hint = DH_HINT[lv] || '';
  const title = DH_NAME[d.domain] || roleTitle[d.domain] || nice(d.domain);
  const c = d.counts || {}, n = d.sensors || 0, parts = [];
  if (c.critical) parts.push(c.critical + ' critical');
  if (c.warning) parts.push(c.warning + ' warning');
  if (d.sensor_faults) parts.push(d.sensor_faults + ' faulty');
  if (c.insufficient_data) parts.push(c.insufficient_data + ' starting up');
  if (d.out_of_service) parts.push(d.out_of_service + ' out of service');
  const counts = d.context_only ? d.context_sensors + ' sensor' + (d.context_sensors === 1 ? '' : 's') + ' shown for context'
    : parts.length ? parts.join(', ') + ' of ' + n + ' sensor' + (n === 1 ? '' : 's') : (n === 1 ? 'Its sensor is normal' : 'All ' + n + ' sensors normal');
  const tr = d.trend === 'elevated' || d.trend === 'curbed' ? d.trend : 'steady';
  const from = DH_WORD[d.trend_from] || nice(d.trend_from);
  const changed = tr === 'elevated' ? '↑ Got worse (was ' + from + ')' : tr === 'curbed' ? (lv === 'normal' ? '✓ Back to normal (was ' + from + ')' : '↓ Improving (was ' + from + ')') : '';
  const trendText = tr === 'elevated' ? '↑ Elevated from ' + from : tr === 'curbed' ? '↓ Curbed from ' + from : 'Steady';
  const stale = (d.stale || []).length;
  const data = d.fresh !== false || lv === 'insufficient_data' ? '' : stale + ' sensor' + (stale === 1 ? ' is' : 's are') + ' not reporting fresh readings';
  const ai = d.raised_by_ai ? 'The AI review rated this ' + (DH_WORD[d.status] || d.status) + '; the live readings alone say ' + (DH_WORD[d.live_status] || d.live_status) + '.' : '';
  const incs = (d.incidents || []).map((i) => ({ id: i.id, sev: i.severity, title: i.title || '', plain: plainTitle(i.title || i.id), state: i.state, workflow: i.workflow, owner: i.owner,
    text: i.id + ' · ' + (i.state === 'running' ? 'Analysing' : (SEV_LABEL[i.severity] || nice(i.severity))) + (i.workflow && i.workflow !== 'analysing' && WF_WORD[i.workflow] ? ' · ' + WF_WORD[i.workflow].w + (i.workflow === 'in_progress' && i.owner ? ' (' + i.owner + ')' : '') : '') + (DH_STAGE[i.refine_stage] && i.refine_stage !== 'early' ? ' · re-checked ' + DH_STAGE[i.refine_stage] : '') +
      (i.change === 'elevated' ? ' ↑' : i.change === 'curbed' ? ' ↓' : '') }));
  // "1 needs decision · 1 in progress (Ravi)": every incident that is not closed, whatever its state
  const wfc = {}, owners = [], rOwners = [];
  for (const i of d.incidents || []) {
    if (!i.workflow) continue; wfc[i.workflow] = (wfc[i.workflow] || 0) + 1;
    const o = i.workflow === 'in_progress' ? owners : i.workflow === 'resolved' ? rOwners : null;
    if (o && i.owner && !o.includes(i.owner)) o.push(i.owner);
  }
  const wfSum = [wfc.analysing ? wfc.analysing + ' analysing' : '', wfc.needs_decision ? wfc.needs_decision + ' needs decision' : '',
    wfc.in_progress ? wfc.in_progress + ' in progress' + (owners.length ? ' (' + owners.join(', ') + ')' : '') : '',
    wfc.resolved ? wfc.resolved + ' back to normal' + (rOwners.length ? ' (' + rOwners.join(', ') + ')' : '') : '', wfc.interrupted ? wfc.interrupted + ' interrupted' : ''].filter(Boolean).join(' · ');
  const dq = d.data_quality || [], qn = {};
  dq.forEach((x) => { qn[x.quality] = (qn[x.quality] || 0) + 1; });
  const qual = Object.keys(qn).map((q) => qn[q] + ' ' + (Q_WORD[q] || q).toLowerCase()).join(' · ');
  const abnormal = lv === 'warning' || lv === 'critical' || lv === 'sensor_fault';
  const steps = abnormal ? (d.steps || []).map((s) => s.text) : [];
  const fromAI = abnormal && (d.steps || []).some((s) => s.source !== 'playbook');
  const src = !steps.length ? '' : fromAI ? 'Suggested by the AI analysis. You decide; nothing is switched automatically.' : 'Standard playbook steps (no AI recommendation yet).';
  const ago = dhAgo(now - d.since);
  const since = d.since ? 'since ' + hm(d.since) + ' (' + ago + ')' : '';
  const todo = steps[0] || '';
  const aria = [title + ': ' + word + (hint ? ', ' + hint : ''), changed.replace(/^[↑↓✓] /, ''), since, counts, data, ai,
    incs.length ? incs.length + ' open incident' + (incs.length === 1 ? '' : 's') + (wfSum ? ': ' + wfSum : '') : '', qual ? 'Sensor data: ' + qual : '', todo ? 'Do now: ' + todo : '', 'Open details'].filter(Boolean).join('. ');
  return { domain: d.domain, title, lv, cls: stClass(lv), glyph: STATUS_GLYPH[lv] || '○', word, hint, trend: tr, trendText, changed, since, ago, counts, data, ai,
    incs, steps, src, todo, abnormal, rank: DH_RANK[lv] || 0, wide: abnormal, aria, raw: d, wfSum, qual, dq };
}
const DH = { tiles: {}, prev: {}, stripSig: '', t: 0, open: null, sheetSig: '' };
function openIncidentFromHealth(id) { selectIncident(id); }
function dhOrder(list) { // worst first, then the fixed domain order (stable while nothing changes)
  return list.slice().sort((a, b) => b.rank - a.rank || ROLE_ORDER.indexOf(a.domain) - ROLE_ORDER.indexOf(b.domain));
}
// decisions still owed in a domain that the health window no longer counts as open (older than 12 h of
// sensor time, or from before a clock restart): they must not disappear from the domain's view
function pendingFor(domain, skip) {
  const ids = new Set((skip || []).map((i) => i.id));
  return (S.incs || []).filter((i) => (i.workflow ? i.workflow === 'needs_decision' : i.approval === 'pending' && i.state !== 'running') && (i.roles || []).includes(domain) && !ids.has(i.id));
}
function dhTileBody(t, m) {
  const older = pendingFor(m.domain, m.incs).length;
  fill(t.root,
    h('span', { class: 'dh-top' }, h('span', { class: 'dh-ico', 'aria-hidden': 'true' }, icon(m.domain)), h('span', { class: 'dh-name', text: m.title }),
      h('span', { class: 'dh-st ' + m.cls }, h('i', { 'aria-hidden': 'true', text: m.glyph }), m.word)),
    h('span', { class: 'dh-sum' }, m.counts),
    m.changed ? h('span', { class: 'dh-chg ' + m.trend, text: m.changed }) : null,
    m.data ? h('span', { class: 'dh-stale', text: '○ ' + m.data }) : null,
    m.qual ? h('span', { class: 'dh-q' }, h('i', { 'aria-hidden': 'true', text: '◆' }), 'Data: ' + m.qual) : null,
    m.todo ? h('span', { class: 'dh-do' }, h('b', { text: 'Do now: ' }), m.todo) : null,
    h('span', { class: 'dh-foot' }, h('span', { class: 'dh-time', text: m.abnormal || m.trend !== 'steady' ? m.since : '' }),
      m.incs.length ? h('span', { class: 'dh-n', text: m.wfSum || (m.incs.length + ' open incident' + (m.incs.length === 1 ? '' : 's')) })
        : older ? h('span', { class: 'dh-n', text: older + ' awaiting decision' }) : null,
      h('span', { class: 'dh-go', 'aria-hidden': 'true', text: '›' })));
  t.time = $('.dh-time', t.root);
}
function renderHealth() {
  const hv = S.health, grid = $('#dh-grid');
  if (!hv || !Array.isArray(hv.domains) || !grid) return;
  const ph = $('.empty', grid); if (ph) ph.remove();
  const now = Math.max(S.simNow || 0, hv.sim_time || 0);
  const said = [];
  const ms = dhOrder(hv.domains.map((d) => healthModel(d, now)));
  ms.forEach((m, idx) => {
    let t = DH.tiles[m.domain];
    if (!t) {
      t = DH.tiles[m.domain] = {};
      t.root = h('button', { type: 'button', class: 'dh-tile', tabindex: '0', onclick: () => openDomain(m.domain) });
    }
    if (grid.children[idx] !== t.root) grid.insertBefore(t.root, grid.children[idx] || null);
    setCls(t.root, 'dh-tile ' + m.cls + (m.lv === 'normal' || m.lv === 'none' ? ' calm' : '') + (m.wide ? ' wide' : ''));
    setAttr(t.root, 'aria-label', m.aria);
    const sig = JSON.stringify([m.lv, m.counts, m.changed, m.data, m.todo, m.incs.length, m.wfSum, m.qual, pendingFor(m.domain, m.incs).length, m.abnormal || m.trend !== 'steady']);
    if (t.sig !== sig) { t.sig = sig; dhTileBody(t, m); }
    else if (t.time) setText(t.time, m.abnormal || m.trend !== 'steady' ? m.since : ''); // a tick only moves the time
    const was = DH.prev[m.domain];
    if (was && was !== m.lv) said.push(m.title + (m.trend === 'curbed' ? ' improved to ' : m.trend === 'elevated' ? ' got worse: ' : ' now ') + m.word);
    DH.prev[m.domain] = m.lv;
  });
  if (said.length) setText($('#dh-live'), said.join('. '));
  const bad = ms.filter((m) => m.abnormal);
  setText($('#dh-sub'), !bad.length ? 'All ' + ms.length + ' areas normal'
    : bad.length + ' of ' + ms.length + ' areas ' + (bad.length === 1 ? 'needs' : 'need') + ' attention: ' + bad.map((m) => m.title + ' (' + m.word.toLowerCase() + ')').join(', '));
  setCls($('#dh-sub'), 'dh-sum0' + (bad.length ? ' ' + bad[0].cls + ' bad' : ''));
  renderHealthConn();
  const strip = $('#dh-strip');
  if (strip) {
    const sig = JSON.stringify(ms.map((m) => [m.domain, m.lv, m.trend, m.word]));
    if (sig !== DH.stripSig) {
      DH.stripSig = sig;
      fill(strip, ms.map((m) => h('button', { type: 'button', class: 'dh-chip ' + m.cls, onclick: () => openDomain(m.domain),
        'aria-label': m.title + ': ' + m.word + (m.trend !== 'steady' ? ', ' + (m.trend === 'elevated' ? 'got worse' : 'improving') : '') + '. Open details' },
        h('span', { class: 'g', 'aria-hidden': 'true', text: m.glyph }), roleShort[m.domain] || m.title,
        m.trend !== 'steady' ? h('span', { class: 'dh-tr ' + m.trend, 'aria-hidden': 'true', text: m.trend === 'elevated' ? '↑' : '↓' }) : null)));
    }
  }
  if (DH.open) renderDomainSheet();
}
// "Live" when the backend has been heard from recently; otherwise say the tiles may be out of date
function renderHealthConn() {
  const e = $('#dh-conn'); if (!e) return;
  const seen = Math.max(S.lastStatus || 0, S.lastLiveEv || 0, S.lastHealth || 0);
  const live = S.sse && seen && Date.now() - seen < 12000;
  setCls(e, 'dh-conn ' + (live ? 'on' : 'off'));
  setText(e, live ? '● Live' : '○ Not updating');
  setAttr(e, 'title', live ? 'Receiving live updates from the edge device' : 'No update for a while: values shown may be out of date');
  const dec = $('#dh-dec');
  if (dec) {
    const n = (S.incs || []).filter((i) => (i.workflow ? i.workflow === 'needs_decision' : i.approval === 'pending' && i.state !== 'running')).length;
    dec.hidden = !n;
    setText(dec, n + ' decision' + (n === 1 ? '' : 's') + ' waiting ›');
  }
}
// Level 2: one domain - what is wrong, what to do, its open incidents and its sensors
function openDomain(domain) {
  DH.open = domain; DH.sheetSig = '';
  $('#dsheet-bd').scrollTop = 0; // a newly opened domain starts at its status, not where the last one was left
  renderDomainSheet();
  openSheet('dsheet');
  const x = $('#dsheet [data-close]'); if (x) x.focus();
}
function renderDomainSheet() {
  const hv = S.health, dom = DH.open; if (!dom || !hv) return;
  const d = (hv.domains || []).find((x) => x.domain === dom); if (!d) return;
  const now = Math.max(S.simNow || 0, hv.sim_time || 0), m = healthModel(d, now);
  const live = ((S.live && S.live.roles[dom]) || {}).sensors || [];
  const older = pendingFor(dom, m.incs);
  const sig = JSON.stringify([m.lv, m.counts, m.changed, m.since, m.data, m.ai, m.incs, m.steps, m.dq, older.map((i) => i.id), live.map((s) => [s.node, s.metric, s.status, s.last, s.quality])]);
  if (sig === DH.sheetSig) return;
  DH.sheetSig = sig;
  setText($('#dsheet-t'), m.title);
  const bd = $('#dsheet-bd'), sc = bd.scrollTop;
  const sorted = live.slice().sort((a, b) => (DH_RANK[b.status] || 0) - (DH_RANK[a.status] || 0) || (a.node + a.metric).localeCompare(b.node + b.metric));
  const sensRow = (s) => h('button', { type: 'button', class: 'ds-row ' + stClass(s.status), title: s.node + ' · ' + s.location, onclick: () => openSensor(s.node, s.metric),
    'aria-label': metricName(s.metric) + ', ' + s.location + ': ' + (s.metric === 'occ' ? (s.last ? 'occupied' : 'vacant') : fmt(s.last) + ' ' + (s.unit || '')) + ', ' + (STATUS_LABEL[s.status] || nice(s.status)) + '. Open chart' },
    h('span', { class: 'ds-g', 'aria-hidden': 'true', text: STATUS_GLYPH[s.status] || '○' }),
    h('span', { class: 'ds-n' }, h('b', { text: metricName(s.metric) }), h('span', { text: placeShort(s.location) })),
    h('span', { class: 'ds-v', text: s.metric === 'occ' ? (s.last ? 'Occupied' : 'Vacant') : s.metric === 'ac_on' ? (s.last >= 0.5 ? 'On' : 'Off') : fmt(s.last) + (s.unit && s.unit !== '0/1' ? ' ' + s.unit : '') }),
    s.quality === 'maintenance' ? h('span', { class: 'ds-s', text: '⊘ Out of service' }) : h('span', { class: 'ds-s', text: STATUS_LABEL[s.status] || nice(s.status) }),
    s.quality !== 'maintenance' ? qualityChip(s) : null);
  const staleNames = (d.stale || []).map((k) => { const [node, metric] = k.split(' '); const s = live.find((x) => x.node === node && x.metric === metric); return s ? sensorLabel(metric, s.location) : k; });
  const kv = (rows) => h('dl', { class: 'kv' }, rows.map(([k, v]) => [h('dt', { text: k }), h('dd', { text: v })]));
  fill(bd,
    h('div', { class: 'ds-head ' + m.cls },
      h('div', { class: 'ds-big' }, h('span', { 'aria-hidden': 'true', text: m.glyph }), ' ' + m.word, m.hint ? h('small', { text: ' · ' + m.hint }) : null),
      h('p', { text: m.counts + (m.since && (m.abnormal || m.trend !== 'steady') ? ' · ' + m.since : '') }),
      m.changed ? h('p', { class: 'dh-chg ' + m.trend, text: m.changed }) : null,
      m.ai ? h('p', { class: 'ds-ai', text: m.ai }) : null,
      m.data ? h('p', { class: 'dh-stale', text: '○ ' + m.data + (staleNames.length ? ': ' + staleNames.join(', ') : '') }) : null),
    m.dq.length ? h('section', { class: 'op-sec' }, h('h3', { text: 'Sensor data quality (' + m.dq.length + ')' }),
      h('ul', { class: 'dq-list' }, m.dq.map((x) => { const [node, metric] = String(x.sensor).split(' '); const s = live.find((y) => y.node === node && y.metric === metric);
        return h('li', {}, h('span', { class: 'qchip q-' + x.quality }, h('i', { 'aria-hidden': 'true', text: qGlyph(x.quality) }), Q_WORD[x.quality] || x.quality), ' ',
          h('b', { text: s ? sensorLabel(metric, s.location) : x.sensor }), x.reason ? h('span', { class: 'muted', text: ': ' + x.reason }) : null); })),
      h('p', { class: 'op-note', text: 'Problems with the data, not with the facility. Out-of-service sensors are shown but never raise an alarm.' })) : null,
    m.steps.length ? h('section', { class: 'op-sec' }, h('h3', { text: 'What to do now' }),
      h('ol', { class: 'op-steps' }, m.steps.map((s) => h('li', { text: s }))), h('p', { class: 'op-note', text: m.src })) : null,
    m.incs.length ? h('section', { class: 'op-sec' }, h('h3', { text: 'Open incidents (' + m.incs.length + ')' }),
      h('div', { class: 'ds-incs' }, m.incs.map((i) => h('button', { type: 'button', class: 'ds-inc sev-' + (i.state === 'running' ? 'pending' : i.sev), onclick: () => openIncidentFromHealth(i.id),
        'aria-label': 'Open incident ' + i.id + ': ' + i.plain + ', ' + i.text.replace(/ ↑$/, ', got worse').replace(/ ↓$/, ', improved') },
        h('b', { text: i.plain }), h('span', { text: i.text }))))) :
      (m.abnormal && !older.length ? h('p', { class: 'op-note', text: 'No incident yet: the AI is asked once a reading stays abnormal for 8 readings in a row.' }) : null),
    older.length ? h('section', { class: 'op-sec' }, h('h3', { text: 'Earlier, still awaiting your decision (' + older.length + ')' }),
      h('div', { class: 'ds-incs' }, older.slice(0, 5).map((i) => h('button', { type: 'button', class: 'ds-inc sev-' + (SEV_LABEL[i.severity] ? (i.severity === 'info' ? 'normal' : i.severity) : 'pending'), onclick: () => openIncidentFromHealth(i.id),
        'aria-label': 'Open incident ' + i.id + ': ' + plainTitle(i.title) },
        h('b', { text: plainTitle(i.title) }), h('span', { text: i.id + ' · ' + (SEV_LABEL[i.severity] || nice(i.severity)) + ' · ' + (i.created_sim_ist || '') })))),
      older.length > 5 ? h('a', { class: 'dh-dec', href: '#incidents', onclick: () => closeSheet('dsheet'), text: 'All ' + older.length + ' in Incidents ›' }) : null) : null,
    h('section', { class: 'op-sec' }, h('h3', { text: 'Sensors (' + live.length + ')' }),
      live.length ? h('div', { class: 'ds-list' }, sorted.map(sensRow)) : h('p', { class: 'op-note', text: 'Loading sensors ...' }),
      h('p', { class: 'op-note', text: 'Tap a sensor for its chart.' })),
    h('details', { class: 'tech eng-open' }, h('summary', { text: 'Technical details' }),
      h('div', { class: 'tech-bd' }, kv([['Headline', d.headline], ['Process status', d.status + (d.raised_by_ai ? ' (raised by AI review)' : '')], ['Live status', d.live_status],
        ['Trend', m.trendText], ['Since (sensor time)', d.since ? dhm(d.since) + ' IST' : '-'], ['Counts', JSON.stringify(d.counts || {})],
        ['Judged / context sensors', d.sensors + ' / ' + d.context_sensors], ['Fresh', d.fresh ? 'yes' : 'no' + (d.stale ? ' (' + d.stale.join(', ') + ')' : '')],
        ['Step sources', (d.steps || []).map((s) => (DH_SRC[s.source] || s.source) + (s.action ? ' ' + s.action : '') + (s.incident ? ' ' + s.incident : '')).join('; ') || '-']]))));
  if (S.eng) $$('details.eng-open', bd).forEach((x) => { x.open = true; });
  bd.scrollTop = sc;
}
async function refreshHealth() {
  try { S.health = await api('/api/health'); S.lastHealth = Date.now(); renderHealth(); updateHero(); } catch (e) { /* offline */ }
}
function refreshHealthSoon() { clearTimeout(DH.t); DH.t = setTimeout(refreshHealth, 400); }
// A refinement moved an incident's severity: a toast that opens it when raised, a quiet note when lowered.
function onIncChange(d) {
  const i = S.incs.find((x) => x.id === d.id) || {};
  const doms = (i.roles || []).map((r) => roleShort[r] || nice(r)).join(', ');
  const sev = SEV_LABEL[i.severity] || nice(i.severity);
  const at = DH_STAGE[d.refined] ? ' at the ' + DH_STAGE[d.refined] + ' re-check' : '';
  if (d.change === 'reminder') {
    const t = h('div', { class: 'toast err act', role: 'alert' }, h('span', { class: 'tmsg', text: '! ' + d.id + ' is ' + sev + ' and nobody has taken it for 15 min' + (doms ? ' · ' + doms : '') }),
      h('button', { type: 'button', text: 'Open', onclick: () => { t.remove(); selectIncident(d.id); } }));
    $('#toasts').append(t); setTimeout(() => t.remove(), 12000);
    return;
  }
  if (d.workflow_change === 'resolved' && d.change !== 'elevated') { toast('✓ ' + d.id + ' is back to normal: close it when you have checked'); return; }
  if (d.change === 'elevated') {
    // one coalesced alert, not a stack: several re-checks finishing together used to pile up full-width
    // toasts over the open sheet (board, 2026-10-23)
    S.elev = (S.elev || []).filter((x) => x !== d.id).concat(d.id);
    let t = $('#elev-toast');
    const msg = (S.elev.length > 1 ? '↑ ' + S.elev.length + ' incidents got worse · latest ' + d.id + ': now ' : '↑ ' + d.id + ' got worse: now ') + sev + at + (doms ? ' · ' + doms : '') +
      (d.reack ? ' · acknowledge it again' : '');
    if (!t || !S.elevMsg) {
      S.elevMsg = h('span', { class: 'tmsg' });
      t = h('div', { id: 'elev-toast', class: 'toast err act', role: 'alert' }, S.elevMsg,
        h('button', { type: 'button', text: 'Open', onclick: () => { const id = S.elev[S.elev.length - 1]; t.remove(); S.elev = []; S.elevMsg = null; selectIncident(id); } }));
      $('#toasts').append(t);
    }
    S.elevMsg.textContent = msg;
    clearTimeout(S.elevTimer);
    S.elevTimer = setTimeout(() => { t.remove(); S.elev = []; S.elevMsg = null; }, 9000);
  } else if (d.change === 'curbed') {
    toast('↓ ' + d.id + ' improved: now ' + sev + at);
  }
}
/* ----- end domain health ----- */

/* ============================== LIVE view ============================== */
const cards = {}; let chipsBuilt = false;
function buildChips() {
  const box = $('#dom-chips'); box.replaceChildren();
  [['all', 'All'], ...ROLE_ORDER.map((r) => [r, roleShort[r]])].forEach(([r, t]) => {
    const b = h('button', { type: 'button', class: 'fchip' + (r === S.filter ? ' on' : ''), 'data-r': r, 'aria-pressed': r === S.filter ? 'true' : 'false', onclick: () => {
      S.filter = r; $$('#dom-chips .fchip').forEach((x) => { x.classList.toggle('on', x.dataset.r === r); x.setAttribute('aria-pressed', x.dataset.r === r ? 'true' : 'false'); }); applyFilter();
    } }, h('span', { class: 'sd' }), h('span', { text: t }), h('span', { class: 'n' }));
    box.append(b);
  });
  chipsBuilt = true;
}
function applyFilter() { for (const r in cards) cards[r].root.hidden = S.filter !== 'all' && S.filter !== r; }
function renderLive() {
  if (!S.live) return;
  if (!chipsBuilt) buildChips();
  const grid = $('#live-grid');
  const roles = ROLE_ORDER.filter((r) => S.live.roles[r]);
  for (const role of roles) {
    const data = S.live.roles[role];
    let c = cards[role];
    if (!c) {
      c = cards[role] = { tilesMap: new Map() };
      c.status = h('span'); c.n = h('span', { class: 'n' });
      c.list = h('div', { class: 'list' });
      const ic = h('div', { class: 'dom-ico', style: '--cb:' + ROLE_COLOR[role] }, icon(role));
      c.root = h('section', { class: 'dom', 'aria-label': roleTitle[role] }, h('div', { class: 'dom-h' }, ic, h('h2', {}, roleTitle[role], c.n), c.status), c.list);
    }
    setCls(c.root, 'dom ' + stClass(data.status));
    const want = pill(data.status);
    if (c.status.firstChild == null || c.status.textContent !== want.textContent) c.status.replaceChildren(want);
    else setCls(c.status.firstChild, want.getAttribute('class'));
    setText(c.n, data.sensors.length + ' sensor' + (data.sensors.length === 1 ? '' : 's'));
    const sensors = data.sensors.slice().sort((a, b) => (a.node + a.metric).localeCompare(b.node + b.metric));
    sensors.forEach((s, i) => {
      const k = key(s.node, s.metric);
      let t = c.tilesMap.get(k);
      if (!t) { t = makeTile(s); c.tilesMap.set(k, t); }
      updateTile(t, s);
      if (c.list.children[i] !== t.root) c.list.insertBefore(t.root, c.list.children[i] || null);
    });
    const idx = roles.indexOf(role);
    if (grid.children[idx] !== c.root) grid.insertBefore(c.root, grid.children[idx] || null);
    const chip = $('#dom-chips .fchip[data-r="' + role + '"]');
    if (chip) { setText($('.n', chip), data.sensors.length); const sd = $('.sd', chip); setText(sd, STATUS_GLYPH[data.status]); setCls(sd, 'sd ' + stClass(data.status)); }
  }
  const chipAll = $('#dom-chips .fchip[data-r="all"]');
  if (chipAll) setText($('.n', chipAll), S.sensorMap.size);
  applyFilter();
}
function makeTile(s) {
  const t = { s, sparkAt: 0, sparkUpd: -1 };
  t.met = h('span', { class: 'met' }); t.loc = h('span', { class: 'loc' });
  t.stc = h('span', { class: 'pill stp' });
  t.val = h('div', { class: 'val' });
  t.spark = h('svg', { class: 'spark', viewBox: '0 0 116 38', preserveAspectRatio: 'none', 'aria-hidden': 'true' });
  t.sma = h('span'); t.trend = h('span', { class: 'trend' });
  t.pat = h('span', { class: 'chip' }); t.cause = h('span', { class: 'cause' }); t.q = h('span', { class: 'qslot' });
  t.root = h('button', { class: 'row', type: 'button' },
    h('div', { class: 'nm' }, t.met, t.loc), t.stc, t.val, t.spark,
    h('div', { class: 'meta' }, t.sma, t.trend), h('div', { class: 'chipsr' }, t.q, t.pat, t.cause));
  t.root.onclick = () => openSensor(s.node, s.metric);
  return t;
}
function trendOf(s) {
  if (s.slope_per_h == null) return null;
  const ref = Math.max(Math.abs(s.sma_1h || 0), Math.abs(s.last || 0), 1e-9);
  const rel = Math.abs(s.slope_per_h) / ref;
  const flat = rel < 0.01;
  return { arrow: flat ? '▶' : s.slope_per_h > 0 ? '▲' : '▼', cls: flat ? 'flat' : s.slope_per_h > 0 ? 'up' : 'down',
    txt: (s.slope_per_h > 0 ? '+' : '') + fmt(s.slope_per_h) + (s.unit && s.unit !== '0/1' ? ' ' + s.unit : '') + '/h' };
}
function updateTile(t, s) {
  t.s = s;
  const occ = s.role === 'occupancy';
  const oos = s.quality === 'maintenance', q = s.quality && s.quality !== 'good' && !oos ? s.quality : '';
  setCls(t.root, 'row ' + (oos ? 'st-none grey oos' : stClass(s.status) + (isGrey(s.status) ? ' grey' : '')));
  setText(t.met, metricName(s.metric)); setText(t.loc, placeShort(s.location)); setAttr(t.loc, 'title', s.node + ' - ' + s.location);
  setAttr(t.root, 'aria-label', metricName(s.metric) + ', ' + s.location + ': ' + (oos ? 'out of service' : (STATUS_LABEL[s.status] || s.status)) +
    (q ? '. ' + (Q_WORD[q] || q) + (s.quality_reason ? ': ' + s.quality_reason : '') : '') + '. Open chart');
  const sc = oos ? '⊘ Out of service' : STATUS_GLYPH[s.status] + ' ' + (STATUS_LABEL[s.status] || s.status);
  setText(t.stc, sc); setCls(t.stc, 'pill stp ' + (oos ? 'st-none' : stClass(s.status)));
  const qs = q + '|' + (s.quality_reason || '');
  if (t.qs !== qs) { t.qs = qs; fill(t.q, qualityChip(q ? s : null)); }
  if (occ) setText(t.val, s.last ? 'Occupied' : 'Vacant');
  else if (!t.valInit || t.lastVal !== s.last) t.val.replaceChildren(fmt(s.last), h('small', { text: s.unit || '' }));
  t.valInit = true; t.lastVal = s.last;
  if (occ) { setText(t.sma, 'state ' + (s.last ? '1' : '0') + ' · ' + (s.points_24h || 0) + ' readings today'); setText(t.trend, ''); }
  else {
    setText(t.sma, S.eng ? (s.sma_1h == null ? 'SMA - · EMA -' : 'SMA ' + fmt(s.sma_1h) + ' · EMA ' + fmt(s.ema_1h)) : (s.sma_1h == null ? '' : '1 h average ' + fmt(s.sma_1h)));
    const tr = trendOf(s);
    setText(t.trend, tr ? tr.arrow + ' ' + tr.txt : ''); setCls(t.trend, 'trend ' + (tr ? tr.cls : ''));
  }
  const pat = s.pattern && s.pattern !== '-' ? s.pattern : null;
  t.pat.style.display = pat ? '' : 'none';
  if (pat && t.pat.dataset.p !== pat) { t.pat.dataset.p = pat; t.pat.innerHTML = patIcon(pat) + esc(patternPlain(pat)); }
  setText(t.cause, isGrey(s.status) ? (s.status === 'insufficient_data' ? 'Starting up: waiting for enough readings' : 'No data yet') : causePlain(s.likely_cause));
}

/* sparklines: visible rows only, one row at most every 10 s, two requests at a time */
function sparkSvg(pts, w, h2, cssVar, occ) {
  if (!pts || pts.length < 2) return '';
  const xs = pts.map((p) => p[0]), vs = pts.map((p) => p[1]);
  const x0 = xs[0], x1 = xs[xs.length - 1] || x0 + 1;
  let mn = Math.min(...vs), mx = Math.max(...vs);
  const X = (x) => ((x - x0) / (x1 - x0 || 1)) * w;
  if (occ) {
    // occupancy is binary: a column of dots when occupied, a single baseline dot when vacant
    let out = '';
    const N = Math.max(14, Math.min(52, Math.round(w / 6)));
    let li = 0;
    for (let i = 0; i < N; i++) {
      const t = i / (N - 1), xq = x0 + t * (x1 - x0);
      while (li < pts.length - 1 && xs[li + 1] < xq) li++;
      const cx = (t * w).toFixed(1);
      if (vs[li] > 0) {
        for (let y = 5; y < h2 - 3; y += 5) out += `<circle cx="${cx}" cy="${y}" r="1.25" style="fill:var(--accent)"/>`;
      } else {
        out += `<circle cx="${cx}" cy="${h2 - 5}" r="1" style="fill:var(--fill2)"/>`;
      }
    }
    return out;
  }
  if (mx - mn < 1e-9) { mx += 1; mn -= 1; }
  const Y = (v) => 4 + (1 - (v - mn) / (mx - mn)) * (h2 - 8);
  const c = 'var(' + cssVar + ')';

  // Dot-matrix plot (see UI Reference): the series is resampled onto a fixed column grid and drawn
  // as discrete dots rather than a stroked line, which is the signature of the reference dashboard.
  // A faint dropline under each sample gives the stippled "instrument readout" texture.
  const N = Math.max(14, Math.min(52, Math.round(w / 6)));
  const base = h2 - 4;
  let out = '';
  let li = 0;
  for (let i = 0; i < N; i++) {
    const t = i / (N - 1), xq = x0 + t * (x1 - x0);
    while (li < pts.length - 1 && xs[li + 1] < xq) li++;      // series is time-ordered
    const v = vs[li], cx = (t * w).toFixed(1), cy = Y(v).toFixed(1);
    const lastCol = i === N - 1;
    // dropline: a few faint dots between the sample and the baseline
    for (let y = +cy + 5; y < base; y += 5) {
      out += `<circle cx="${cx}" cy="${y.toFixed(1)}" r="0.7" style="fill:${c};opacity:.18"/>`;
    }
    out += `<circle cx="${cx}" cy="${cy}" r="${lastCol ? 2.6 : 1.35}" style="fill:${lastCol ? 'var(--accent)' : c}${lastCol ? '' : ';opacity:.85'}"/>`;
  }
  return out;
}
const STATUS_VAR = { normal: '--ok-b', warning: '--warn-b', critical: '--crit-b', sensor_fault: '--fault-b' };
let sparkBusy = 0;
async function sparkLoop() {
  if (sparkBusy >= 2 || document.hidden || S.view !== 'live') return;
  let best = null; const now = Date.now();
  for (const role in cards) {
    if (cards[role].root.hidden) continue;
    for (const t of cards[role].tilesMap.values()) {
      if (now - t.sparkAt < 10000) continue;
      if (t.sparkUpd === t.s.updated && t.sparkPts) continue;
      const r = t.root.getBoundingClientRect();
      if (r.bottom < -80 || r.top > innerHeight + 80 || r.height === 0) continue;
      if (!best || t.sparkAt < best.sparkAt) best = t;
    }
  }
  if (!best) return;
  sparkBusy++; best.sparkAt = now;
  try {
    const s = best.s;
    const d = await api('/api/series?node=' + encodeURIComponent(s.node) + '&metric=' + encodeURIComponent(s.metric) + '&hours=4');
    best.sparkUpd = s.updated; best.sparkPts = d.points;
    best.spark.innerHTML = sparkSvg(d.points, 116, 38, STATUS_VAR[s.status] || '--nodata-b', s.role === 'occupancy');
  } catch (e) { /* ignore */ }
  sparkBusy--;
}

/* ============================== sheets ============================== */
function openSheet(id) {
  const s = $('#' + id); s.classList.add('open'); s.setAttribute('aria-hidden', 'false');
  $('#scrim').classList.add('on'); document.body.classList.add('noscroll');
}
function closeSheet(id) {
  const s = $('#' + id); if (!s.classList.contains('open')) return;
  s.classList.remove('open'); s.setAttribute('aria-hidden', 'true');
  if (id === 'sheet') S.drawer = null;
  if (id === 'dsheet') { DH.open = null; DH.sheetSig = ''; }
  if (id === 'isheet') { closeSensorSheet(); S.incId = null; S.inc = null; S.incText = ''; }
  if (!$('.sheet.open')) { $('#scrim').classList.remove('on'); document.body.classList.remove('noscroll'); }
  hidePop(true);
}

/* ============================== SENSOR SHEET + CHARTS ============================== */
function niceTicks(a, b, n) {
  const span = b - a || 1, raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p, t = [];
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) t.push(+v.toFixed(10));
  return { t, step };
}
function pathOf(pts, X, Y, gap) {
  let d = '', prev = null;
  for (const p of pts) { d += (prev == null || p[0] - prev > gap ? 'M' : 'L') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); prev = p[0]; }
  return d;
}
function renderBigChart(box, s, hours, occ, height) { // height: optional, for the compact incident sensor sheet
  const pts = s.points || [];
  if (pts.length < 2) { box.replaceChildren(h('div', { class: 'empty', text: 'Not enough data in the last ' + hours + ' h to draw a chart yet.' })); return; }
  const W = Math.max(320, Math.min(860, box.clientWidth - 12 || 860)), H2 = height || (W < 600 ? 290 : 360), L = W < 600 ? 50 : 62, R = 12, T = 14, B = 32;
  const t1 = pts[pts.length - 1][0], t0 = t1 - hours * 3600;
  const all = pts.map((p) => p[1]).concat((s.bollinger_upper || []).map((p) => p[1]), (s.bollinger_lower || []).map((p) => p[1]));
  let mn = Math.min(...all), mx = Math.max(...all);
  const span0 = mx - mn || Math.max(Math.abs(mx), 1);
  const lim = s.limits, offscale = [], limLines = [];
  if (lim) for (const [k, nm] of [['warn', 'warning'], ['crit', 'critical']]) {
    const v = lim[k]; if (typeof v !== 'number') continue;
    if (v >= mn - span0 * 0.8 && v <= mx + span0 * 0.8) { limLines.push({ v, nm, k }); mn = Math.min(mn, v); mx = Math.max(mx, v); } else offscale.push({ v, nm, up: v > mx });
  }
  if (occ) { mn = Math.min(mn, 0); mx = Math.max(mx, 1); }
  const pd = (mx - mn || 1) * 0.07; mn -= pd; mx += pd;
  const X = (x) => L + ((x - t0) / (t1 - t0)) * (W - L - R);
  const Y = (v) => T + (1 - (v - mn) / (mx - mn)) * (H2 - T - B);
  let g = '';
  const yt = niceTicks(mn, mx, 5), dec = yt.step < 1 ? Math.min(4, Math.ceil(-Math.log10(yt.step))) : 0;
  for (const v of (occ ? [0, 1] : yt.t)) g += `<line class="ch-grid" x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="ch-t" x="${L - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${occ ? (v ? 'occupied' : 'vacant') : v.toFixed(dec)}</text>`;
  const stepH = hours <= 6 ? 1 : hours <= 12 ? 2 : 4;
  const lblEvery = W < 600 ? 2 * stepH : stepH;
  for (let e = Math.ceil((t0 + 19800) / (3600 * stepH)) * 3600 * stepH - 19800; e <= t1; e += 3600 * stepH) {
    const show = ((e + 19800) / 3600) % lblEvery === 0;
    g += `<line class="ch-grid" x1="${X(e).toFixed(1)}" x2="${X(e).toFixed(1)}" y1="${T}" y2="${H2 - B}" style="opacity:.5"/>` + (show ? `<text class="ch-t" x="${X(e).toFixed(1)}" y="${H2 - B + 20}" text-anchor="middle">${hm(e)}</text>` : '');
  }
  g += `<text class="ch-t" x="${W - R}" y="${H2 - 2}" text-anchor="end" style="opacity:.7">IST</text>`;
  const up = s.bollinger_upper || [], lo = s.bollinger_lower || [];
  if (up.length > 1 && lo.length === up.length && !occ) {
    let d = 'M' + up.map((p) => X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('L');
    d += 'L' + lo.slice().reverse().map((p) => X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('L') + 'Z';
    g += `<path d="${d}" style="fill:var(--blue);opacity:.16" stroke="none"/>`;
  }
  for (const l of limLines) {
    const warn = l.k !== 'crit', y = Y(l.v).toFixed(1);
    g += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" style="stroke:var(${warn ? '--warn-b' : '--crit-b'})" stroke-width="2" stroke-dasharray="${warn ? '9 5' : '2 5'}" stroke-linecap="round"/>` +
      `<text class="ch-t" x="${W - R - 4}" y="${(Y(l.v) - 6).toFixed(1)}" text-anchor="end" style="fill:var(${warn ? '--warn' : '--crit'});font-weight:700">${l.nm} limit ${l.v}</text>`;
  }
  offscale.forEach((o, i) => { g += `<text class="ch-t" x="${W - R - 4}" y="${o.up ? T + 14 + i * 16 : H2 - B - 6 - i * 16}" text-anchor="end" style="fill:var(${o.nm === 'critical' ? '--crit' : '--warn'});font-weight:700">${o.up ? '▲' : '▼'} ${o.nm} limit ${o.v} (off scale)</text>`; });
  const gap = 900;
  if (!occ) {
    g += `<path d="${pathOf(s.ema_1h || [], X, Y, gap)}" fill="none" style="stroke:var(--accent)" stroke-width="2.2" stroke-dasharray="7 3 2 3" stroke-linecap="round"/>`;
    g += `<path d="${pathOf(s.sma_1h || [], X, Y, gap)}" fill="none" style="stroke:var(--blue)" stroke-width="2.6" stroke-linecap="round"/>`;
  }
  if (occ) {
    let d = ''; pts.forEach((p, i) => { d += (i ? 'H' + X(p[0]).toFixed(1) + 'V' : 'M' + X(p[0]).toFixed(1) + ' ') + Y(p[1]).toFixed(1); });
    g += `<path d="${d}" fill="none" style="stroke:var(--tx)" stroke-width="2.2"/>`;
  } else g += `<path d="${pathOf(pts, X, Y, gap)}" fill="none" style="stroke:var(--tx)" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>`;
  const lp = pts[pts.length - 1];
  g += `<circle cx="${X(lp[0]).toFixed(1)}" cy="${Y(lp[1]).toFixed(1)}" r="4.5" style="fill:var(--tx)"/>`;
  g += `<line id="xh" x1="0" x2="0" y1="${T}" y2="${H2 - B}" style="stroke:var(--tx2)" visibility="hidden"/><circle id="xhc" r="5.5" style="fill:var(--card);stroke:var(--tx)" stroke-width="2.5" visibility="hidden"/>`;
  const sw = (c, extra) => h('i', { style: 'border-color:var(' + c + ');' + (extra || '') });
  const legend = h('div', { class: 'legend' },
    h('span', {}, sw('--tx'), 'raw'),
    occ || !(s.sma_1h || []).length ? null : h('span', {}, sw('--blue'), 'SMA 1 h'), // a frozen agent window carries raw points only
    occ || !(s.ema_1h || []).length ? null : h('span', {}, sw('--accent', 'border-top-style:dashed'), 'EMA 1 h'),
    occ || !up.length ? null : h('span', {}, h('i', { class: 'band' }), 'Bollinger band'),
    lim ? h('span', {}, sw('--warn-b', 'border-top-style:dashed'), 'warning') : null,
    lim ? h('span', {}, sw('--crit-b', 'border-top-style:dotted'), 'critical') : null);
  const tip = h('div', { class: 'tip', hidden: true });
  const wrap = h('div', { class: 'chartwrap' });
  wrap.innerHTML = `<svg viewBox="0 0 ${W} ${H2}" role="img" aria-label="Chart of ${esc(s.metric)} for the last ${hours} hours">${g}</svg>`;
  wrap.append(tip, legend);
  box.replaceChildren(wrap);
  const svg = $('svg', wrap), xh = $('#xh', wrap), xhc = $('#xhc', wrap);
  const smaM = new Map((s.sma_1h || []).map((p) => [p[0], p[1]])), emaM = new Map((s.ema_1h || []).map((p) => [p[0], p[1]]));
  const mv = (ev) => {
    const r = svg.getBoundingClientRect(), vx = ((ev.clientX - r.left) / r.width) * W;
    let bi = 0, bd = 1e18;
    for (let i = 0; i < pts.length; i++) { const dd = Math.abs(X(pts[i][0]) - vx); if (dd < bd) { bd = dd; bi = i; } }
    const p = pts[bi], px = X(p[0]), py = Y(p[1]);
    xh.setAttribute('x1', px); xh.setAttribute('x2', px); xh.setAttribute('visibility', 'visible');
    xhc.setAttribute('cx', px); xhc.setAttribute('cy', py); xhc.setAttribute('visibility', 'visible');
    const sm = smaM.get(p[0]), em = emaM.get(p[0]);
    tip.hidden = false;
    tip.textContent = hm(p[0]) + ' IST · ' + fmt(p[1]) + (s.unit ? ' ' + s.unit : '') + (sm != null ? ' · SMA ' + fmt(sm) : '') + (em != null ? ' · EMA ' + fmt(em) : '');
    const wr = wrap.getBoundingClientRect();
    tip.style.left = Math.min(Math.max(r.left - wr.left + (px / W) * r.width, 100), wr.width - 100) + 'px';
    tip.style.top = (r.top - wr.top + (py / H2) * r.height - 10) + 'px';
  };
  svg.addEventListener('pointermove', mv); svg.addEventListener('pointerdown', mv);
  svg.addEventListener('pointerleave', () => { tip.hidden = true; xh.setAttribute('visibility', 'hidden'); xhc.setAttribute('visibility', 'hidden'); });
}

async function openSensor(node, metric) {
  S.drawer = { node, metric, data: null, promptOpen: false };
  const live = S.sensorMap.get(key(node, metric)) || {};
  setText($('#sheet-t'), live.location ? sensorLabel(metric, live.location) : metricName(metric) + ' · ' + node);
  $('#sheet-bd').replaceChildren(h('div', { class: 'empty' }, h('span', { class: 'spin' }), ' Loading ' + metricName(metric) + ' ...'));
  $('#sheet-ft').replaceChildren();
  openSheet('sheet');
  await loadDrawer();
}
async function loadDrawer() {
  const d = S.drawer; if (!d) return;
  try {
    const data = await api('/api/series?node=' + encodeURIComponent(d.node) + '&metric=' + encodeURIComponent(d.metric) + '&hours=8');
    if (S.drawer !== d) return;
    d.data = data; S.lastDrawer = Date.now(); renderDrawer();
  } catch (e) { if (S.drawer === d) $('#sheet-bd').replaceChildren(h('div', { class: 'empty', text: 'Could not load series: ' + e.message })); }
}
function evChipsInText(text, evidence) {
  const out = []; let last = 0; const re = /\[([^\]]*)\]/g; let m;
  while ((m = re.exec(text || ''))) {
    const ids = m[1].match(/E\d+/g);
    if (!ids) continue;
    out.push((text || '').slice(last, m.index));
    ids.forEach((id) => { out.push(evChip(id, id, evidence, null), ' '); });
    last = m.index + m[0].length;
  }
  out.push((text || '').slice(last));
  return out;
}
function renderDrawer() {
  const bd = $('#sheet-bd'), d = S.drawer, s = d.data; if (!s) return;
  const sc = bd.scrollTop;
  const live = S.sensorMap.get(key(d.node, d.metric)) || {};
  const win = s.window, rf = win && win.rule_finding;
  const occ = s.role === 'occupancy';
  const chart = h('div', {});
  const kv = h('dl', { class: 'kv' });
  const row = (k, v) => kv.append(h('dt', { text: k }), h('dd', {}, v));
  row('Where', live.location || '-');
  if (!occ) { row(S.eng ? 'SMA / EMA 1 h' : '1 h average', S.eng ? fmt(live.sma_1h) + ' / ' + fmt(live.ema_1h) + ' ' + (s.unit || '') : fmt(live.sma_1h) + ' ' + (s.unit || '')); const tr = trendOf(live); row('Trend', tr ? tr.arrow + ' ' + tr.txt : '-'); }
  row('Shape', (live.pattern && live.pattern !== '-') ? patternPlain(live.pattern) : '-');
  row('Likely cause', causePlain(live.likely_cause));
  if (s.limits) row('Alarm limits', 'warning ' + s.limits.warn + ' · critical ' + s.limits.crit + (s.limits.dir === 'low' ? ' (too low)' : s.limits.dir === 'both' ? ' (either side)' : ' (too high)'));
  if (S.eng) row('Node', d.node + ' (' + nice(s.role) + ')');
  const canAnalyze = !!win && s.role !== 'hvac';
  const btn = h('button', { class: 'btn primary', type: 'button', style: 'width:100%', disabled: canAnalyze ? null : true,
    onclick: async () => {
      btn.disabled = true;
      try { S.pendingNewest = new Set(S.incs.map((i) => i.id)); const r = await post('/api/analyze', { node: d.node, metric: d.metric }); toast(r && r.queued_ahead ? 'Queued: ' + r.queued_ahead + ' analysis ahead on the NPU' : 'AI agents are on it (mode ' + (S.status ? S.status.mode : '?') + ')'); setTimeout(refreshIncidents, 500); setTimeout(refreshIncidents, 1500); }
      catch (e) { S.pendingNewest = null; toast('Analyse: ' + e.message, true); btn.disabled = false; }
    } }, icon('multi'), 'Ask the AI to check this sensor');
  const body = [
    h('div', { class: 'rep-h', style: 'margin-bottom:10px' }, live.quality === 'maintenance' ? h('span', { class: 'pill st-none', text: '⊘ Out of service' }) : live.status ? pill(live.status) : null,
      live.quality !== 'maintenance' ? qualityBtn(live, 'drawer:' + d.node + ':' + d.metric) : null),
    h('div', { class: 'sheet-big' }, occ ? (live.last ? 'Occupied' : 'Vacant') : fmt(live.last) + ' ' + (s.unit || '')),
    h('p', { class: 'muted', style: 'margin:2px 0 14px', text: live.location || d.node }),
    chart,
    h('div', { class: 'card', style: 'margin-top:14px' }, kv),
    maintSec(d, live),
    h('div', { class: 'card' },
      h('h3', { style: 'margin-bottom:8px;font-size:17px', text: S.eng ? 'Rule engine says (Mode 1, no AI)' : 'Automatic check (rules, no AI)' }),
      rf ? h('div', {},
        h('div', { class: 'rep-h', style: 'margin-bottom:8px' }, pill(rf.status), h('span', { class: 'chip', html: patIcon(rf.pattern) + esc(patternPlain(rf.pattern)) })),
        h('dl', { class: 'kv' },
          h('dt', { text: 'Likely cause' }), h('dd', { text: causePlain(rf.likely_cause) }),
          h('dt', { text: 'Confidence' }), h('dd', { text: confWord(rf.confidence).w + (S.eng ? ' (' + pct(rf.confidence) + ')' : '') }),
          h('dt', { text: 'Suggested action' }), h('dd', { text: actionText(rf.action) })),
        h('ul', { class: 'obs' }, (rf.observations || []).map((o) => h('li', {}, S.eng ? evChipsInText(o, win.evidence) : stripRefs(o)))))
        : h('div', { class: 'muted', text: s.role === 'hvac' ? 'HVAC nodes are context only: no agent window.' : 'Not enough history yet for this sensor.' })),
    win && S.eng ? h('div', { class: 'card' }, h('h3', { style: 'margin-bottom:6px;font-size:17px', text: 'Evidence E1..E8' }),
      h('p', { class: 'muted', style: 'font-size:13.5px;margin-bottom:6px', text: 'Computed statistics. These are the only facts the AI may cite.' }),
      h('ul', { class: 'evlist' }, (win.evidence || []).map((e) => h('li', {}, h('b', { text: e.ID }), h('span', { text: e.Text }))))) : null,
    win && S.eng ? h('details', { ontoggle: (e) => { d.promptOpen = e.target.open; }, open: d.promptOpen ? true : null },
      h('summary', { text: 'Prompt sent to the on-device LLM' }), h('pre', { text: win.prompt || '' })) : null,
  ];
  bd.replaceChildren(...body.filter(Boolean));
  $('#sheet-ft').replaceChildren(h('p', { class: 'foot-hint', text: canAnalyze ? 'The result appears under Incidents and waits for your decision.' : 'No AI check is available for this sensor (shown for context).' }), btn);
  renderBigChart(chart, s, 8, occ);
  bd.scrollTop = sc;
}

/* ---------- evidence chips + popover ---------- */
let popPinned = null;
const pop = () => $('#pop');
function hidePop(force) { if (force || !popPinned) pop().hidden = true; if (force) popPinned = null; }
function showPop(chip, nodes) {
  const p = pop(); p.replaceChildren(...nodes); p.hidden = false;
  const r = chip.getBoundingClientRect();
  p.style.left = Math.max(8, Math.min(r.left, innerWidth - p.offsetWidth - 8)) + 'px';
  const below = r.bottom + 6 + p.offsetHeight < innerHeight;
  p.style.top = (below ? r.bottom + 6 : Math.max(8, r.top - p.offsetHeight - 6)) + 'px';
}
function evChip(label, id, evidence, sensor) {
  const ev = (evidence || []).find((e) => e.ID === id);
  const c = h('span', { class: 'chip ev' + (ev ? '' : ' bad'), tabindex: '0', role: 'button', text: label });
  const nodes = () => ev ? [h('div', {}, h('b', { text: label }), sensor ? ' · ' + sensor.node + ' ' + sensor.metric : ''), h('div', { text: '[' + ev.Stat + '] ' + ev.Text })]
    : [h('b', { text: label }), h('div', { text: 'Not found in the evidence list' + (sensor ? ' of ' + sensor.node : '') + ' (possible hallucinated id).' })];
  c.title = ev ? (sensor ? sensor.node + ' ' + sensor.metric + ': ' : '') + ev.Text : 'unresolved evidence id';
  c.addEventListener('mouseenter', () => { if (!popPinned) showPop(c, nodes()); });
  c.addEventListener('mouseleave', () => { if (!popPinned) hidePop(); });
  c.addEventListener('click', (e) => { e.stopPropagation(); if (popPinned === c) hidePop(true); else { popPinned = c; showPop(c, nodes()); } });
  c.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); c.click(); } });
  return c;
}
function refChip(inc, token) {
  const m = /^(S\d+)\.(E\d+)$/.exec(String(token).trim());
  const sensor = m && (inc.sensors || []).find((s) => s.ref === m[1]);
  return evChip(token, m ? m[2] : token, sensor ? sensor.evidence : [], sensor || null);
}

/* ============================== INCIDENTS ============================== */
const incEls = new Map();
const grpEls = new Map(); // group lead id -> wrapper (lead card + "N related")
const wallMs = (inc) => { const t = Date.parse((inc.created_wall || '').replace(' ', 'T')); return isNaN(t) ? null : t; };
function elapsedOf(inc) {
  if (inc.state !== 'running') return inc.total_ms > 0 ? inc.total_ms / 1000 : null;
  const t = wallMs(inc); if (t == null) return null;
  const d = (Date.now() - t) / 1000; return d >= 0 && d < 3600 ? d : null;
}
function usualSecs(mode) {
  const xs = S.incs.filter((i) => i.mode === mode && i.state !== 'running' && i.total_ms > 0).map((i) => i.total_ms / 1000);
  return xs.length >= 2 ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}
function primaryRole(roles) { return (roles && roles.length > 1) ? (roles[0]) : (roles && roles[0]) || 'multi'; }
function renderIncChips() {
  const box = $('#inc-chips'); if (!box.firstChild) {
    INC_STATE.forEach(([k, t]) => {
      box.append(h('button', { type: 'button', class: 'fchip' + (k === S.incFilter ? ' on' : ''), 'data-k': k, 'aria-pressed': k === S.incFilter ? 'true' : 'false', onclick: () => {
        S.incFilter = k; $$('#inc-chips .fchip').forEach((x) => { x.classList.toggle('on', x.dataset.k === k); x.setAttribute('aria-pressed', x.dataset.k === k ? 'true' : 'false'); }); applyIncFilter();
      } }, h('span', { text: t }), h('span', { class: 'n' })));
    });
  }
  const cnt = { all: S.incs.length, running: S.incs.filter((i) => i.state === 'running').length };
  S.incs.forEach((i) => { const w = wfOfI(i); cnt[w] = (cnt[w] || 0) + 1; });
  $$('#inc-chips .fchip').forEach((x) => setText($('.n', x), cnt[x.dataset.k] || 0));
}
// state (workflow), domain, date and free text; 'pending' / 'done' kept for old links
function incMatches(i) {
  const f = S.incFilter || 'all', w = wfOfI(i);
  const st = f === 'all' || (f === 'running' ? i.state === 'running' : f === 'pending' ? w === 'needs_decision' : f === 'done' ? w === 'closed' : w === f);
  return st && (!S.incDom || S.incDom === 'all' || (i.roles || []).includes(S.incDom)) && incDateOk(i) && (!S.incQ || incText(i).includes(S.incQ));
}
function applyIncFilter() { renderIncList(); }
function flaggedRoles(i) {
  if (!i.sensors) { // list payload: roles + count from the title
    const m = /^(\d+) sensors/.exec(i.title || '');
    return { n: m ? +m[1] : 0, roles: ROLE_ORDER.filter((r) => (i.roles || []).includes(r)) };
  }
  const fl = i.sensors.filter((x) => !x.context);
  const roles = ROLE_ORDER.filter((r) => fl.some((x) => x.role === r));
  fl.forEach((x) => { if (x.role && !roles.includes(x.role)) roles.push(x.role); });
  return { n: fl.length, roles };
}
function multiFlag(i) {
  const f = flaggedRoles(i); if (f.n < 2) return null;
  return h('span', { class: 'mflag' }, f.roles.map((r) => h('span', { class: 'mi', style: '--cb:' + (ROLE_COLOR[r] || ROLE_COLOR.multi) }, icon(r, 14))), h('span', { text: f.n + ' sensors' }));
}
function renderIncList() {
  const box = $('#inc-list');
  setBadge();
  renderIncChips();
  renderHealthConn();
  if (!S.incs.length) { box.replaceChildren(h('div', { class: 'empty', style: 'grid-column:1/-1', text: 'All quiet. An incident appears when a reading stays abnormal for a while; you will be asked to decide on each one.' })); incEls.clear(); grpEls.clear(); return; }
  S.incs.forEach((i) => {
    let e = incEls.get(i.id);
    if (!e) { e = { root: h('button', { class: 'icard', type: 'button', onclick: () => selectIncident(i.id) }) }; incEls.set(i.id, e); }
    const sig = JSON.stringify(i);
    if (e.sig !== sig) {
      e.sig = sig;
      const rr = primaryRole(i.roles);
      // coloured by the reasoner's severity; neutral while analysing (sevOf)
      setCls(e.root, 'icard sevrow sev-' + sevOf(i).k);
      const running = i.state === 'running', plain = plainTitle(i.title);
      const doms = (i.roles || []).map((r) => roleShort[r] || nice(r)).join(', ');
      const wf = wfOfI(i), wfw = (WF_WORD[wf] || { w: nice(wf) }).w;
      setAttr(e.root, 'aria-label', plain + '. ' + sevOf(i).t + '. ' + wfw + (i.owner && wf !== 'closed' ? ', ' + i.owner : '') + (i.outcome ? ', ' + (OUTCOME_TEXT[i.outcome] || nice(i.outcome)) : '') + '. ' + i.id);
      fill(e.root,
        h('div', { class: 'top' },
          h('div', { class: 'dico', style: '--cb:' + (ROLE_COLOR[(i.roles || []).length > 1 ? 'multi' : rr] || ROLE_COLOR.multi) }, icon((i.roles || []).length > 1 ? 'multi' : rr)),
          h('div', { style: 'min-width:0;flex:1' },
            h('div', { class: 'ttl', text: plain, title: i.title }),
            h('div', { class: 'sub' }, sevTag(i), running ? h('span', { class: 'livepill', text: 'LIVE' }) : null,
              i.refine_stage && i.refine_stage !== 'early' ? stageTag(i) : null, multiFlag(i),
              h('span', { class: 'pill ghost eng-only', text: 'Mode ' + i.mode }), h('span', { class: 'chip eng-only', text: nice(i.label) })))),
        running ? h('div', { class: 'prog' }) : null,
        // live token preview, so a running incident visibly streams from the list view too.
        // Seeded from S.cardStream because the card is rebuilt whenever the incident JSON changes.
        running ? h('pre', { class: 'cstream', 'data-cs': i.id, text: S.cardStream[i.id] || '' }) : null,
        h('div', { class: 'foot' },
          h('span', { text: i.id + (doms ? ' · ' + doms : '') + ' · ' + (i.created_sim_ist || '-') }),
          h('span', { class: 'eng-only', text: i.npu_calls + ' NPU call' + (i.npu_calls === 1 ? '' : 's') + (running ? '' : ' · ' + (i.total_ms / 1000).toFixed(1) + ' s') }),
          wfChip(i)),
        (i.steps_total && wf !== 'closed') || etaEl(i) ? h('div', { class: 'foot2' },
          i.steps_total && wf !== 'closed' ? h('span', { class: 'stepsn', text: (i.steps_total - i.steps_open) + ' of ' + i.steps_total + ' steps ticked' }) : null,
          wf !== 'closed' ? etaEl(i) : null) : null);
    }
  });
  const ids = new Set(S.incs.map((i) => i.id));
  for (const [id, e] of incEls) if (!ids.has(id)) { e.root.remove(); incEls.delete(id); }
  // filter, then collapse repeats (same sensor, or same domain + pattern, within 30 min: backend group)
  const vis = S.incs.filter(incMatches), groups = new Map();
  for (const i of vis) { const g = i.group || i.id; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(i); }
  const want = [];
  for (const [g, members] of groups) {
    let ge = grpEls.get(g);
    if (!ge) { ge = { root: h('div', { class: 'igrp' }), btn: null }; grpEls.set(g, ge); }
    const lead = members[0], rest = members.slice(1), open = S.grpOpen.has(g);
    const kids = [incEls.get(lead.id).root];
    if (rest.length) {
      const lid = 'rel-' + g;
      kids.push(h('button', { type: 'button', class: 'irel', 'aria-expanded': open ? 'true' : 'false', 'aria-controls': lid,
        onclick: () => { open ? S.grpOpen.delete(g) : S.grpOpen.add(g); renderIncList(); } },
      (open ? '▾ ' : '▸ ') + rest.length + ' related', h('span', { class: 'muted', text: ' · same sensor or same pattern within 30 min' })));
      if (open) kids.push(h('div', { class: 'irel-list', id: lid }, rest.map((i) => incEls.get(i.id).root)));
    }
    if (ge.root.children.length !== kids.length || kids.some((k, n) => ge.root.children[n] !== k)) ge.root.replaceChildren(...kids);
    want.push(ge.root);
  }
  for (const [g, ge] of grpEls) if (!groups.has(g)) { ge.root.remove(); grpEls.delete(g); }
  want.forEach((el, idx) => { if (box.children[idx] !== el) box.insertBefore(el, box.children[idx] || null); });
  while (box.children.length > want.length) box.lastElementChild.remove();
  if (!want.length) box.replaceChildren(h('div', { class: 'empty', style: 'grid-column:1/-1', text: 'No incident matches these filters.' }));
}
async function selectIncident(id) {
  S.incId = id; S.incText = ''; S.inc = null; S.ckNN = null; S.footForm = null;
  delete S.hist[id]; delete S.histReq[id]; // History of this sensor: always fresh on open
  setText($('#isheet-t'), id);
  $('#inc-detail').replaceChildren(h('div', { class: 'empty' }, h('span', { class: 'spin' }), ' Loading ' + id + ' ...'));
  $('#inc-foot').replaceChildren(); $('#inc-foot').dataset.sig = '';
  openSheet('isheet');
  await refreshIncDetail(true);
  // opened mid-run: show what the agents have typed so far, not only what arrives from now on
  if (S.incId === id && S.inc && (S.inc.state === 'running' || ST.rlast[id])) resyncStreams(id);
}

function gate(valid, errors) {
  return h('div', {}, h('span', { class: 'gate ' + (valid ? 'pass' : 'fail') }, icon(valid ? 'check' : 'x'), valid ? 'Safety check passed' : 'Safety check rejected this'),
    !valid && errors && errors.length ? h('ul', { class: 'errs' }, errors.map((e) => h('li', { text: e }))) : null,
    !valid && (!errors || !errors.length) ? h('div', { class: 'errs', text: 'No error detail returned.' }) : null);
}
function details(k, title, text) {
  return h('details', { open: S.open.has(k) ? true : null, ontoggle: (e) => { e.target.open ? S.open.add(k) : S.open.delete(k); } },
    h('summary', { text: title }), h('pre', { text: text == null || text === '' ? '(empty)' : text }));
}
function modelBadge(model, ft) {
  return h('span', { class: 'pill ' + (ft ? 'st-normal' : 'st-warning'), title: model }, h('i', { class: 'dot ' + (ft ? 'ok' : 'warn'), style: 'width:8px;height:8px' }), ft ? 'Fine-tuned' : 'Base model', ' · ', model);
}
const isCtxAgent = (a) => /context agent/i.test((a && a.model) || '');
const isFastModel = (m) => /deterministic/i.test(m || '');
function statChips(c) { // optional per-call metrics; absent on older incidents
  const out = [];
  if (c.cached) out.push('cached \u00B7 instant');
  if (c.ttft_ms != null) out.push('first token ' + (c.ttft_ms / 1000).toFixed(1) + ' s');
  if (c.gen_tokens != null) out.push(c.gen_tokens + ' tok');
  if (c.tokens_per_s != null) out.push(Math.round(c.tokens_per_s) + ' tok/s');
  if (c.early_stopped) out.push('stopped at JSON end');
  if (c.latency_ms && !c.cached) out.push((c.latency_ms / 1000).toFixed(1) + ' s total');
  return out.length ? h('div', { class: 'statrow' }, out.map((t) => h('span', { class: 'chip stat', text: t }))) : null;
}
function reportBody(inc, r) {
  return h('div', {},
    h('div', { class: 'rep-h' }, h('span', { class: 'label-big', text: nice(r.label) }),
      h('span', { class: 'muted' }, h('span', { class: 'confbar' }, h('i', { style: 'width:' + Math.round((r.confidence || 0) * 100) + '%' })), ' ' + pct(r.confidence) + ' sure')),
    h('p', { style: 'margin:10px 0 4px;font-weight:700;font-size:16.5px', text: r.root_cause || '-' }),
    r.explanation ? h('p', { class: 'muted', style: 'margin:4px 0', text: r.explanation }) : null,
    // severity basis (reasoner v3, severityGuard): the rules' view vs the reasoner's, and why the shown one differs
    r.severity_basis ? h('p', { class: 'muted', style: 'margin:4px 0;font-size:13px', text: 'Severity basis: rules ' + nice(r.severity_basis.rule) +
      ' · reasoner ' + nice(r.severity_basis.reasoner) + (r.severity_basis.guard ? ' · ' + r.severity_basis.guard : '') }) : null,
    h('dl', { class: 'kv', style: 'margin-top:12px' },
      h('dt', { text: 'Suggested action' }), h('dd', { style: 'font-weight:700', text: nice(r.action) }),
      h('dt', { text: 'Affected' }), h('dd', {}, (r.affected_domains || []).length ? (r.affected_domains || []).map((d) => h('span', { class: 'chip', style: 'margin:0 6px 4px 0', text: roleTitle[d] || nice(d) })) : '-'),
      h('dt', { text: 'Evidence' }), h('dd', {}, (r.evidence || []).length ? (r.evidence || []).map((t) => h('span', { style: 'margin:0 6px 4px 0;display:inline-block' }, refChip(inc, t))) : h('span', { class: 'muted', text: 'none cited' }))),
    r.requires_human_approval ? h('div', { class: 'note-human', style: 'margin-top:10px', text: 'Requires human approval — no automatic actuation.' }) : null);
}

/* ----- order-tracking model ----- */
function fastText(model) { return /related domains verified steady/i.test(model || '') ? 'Related domains verified steady \u2192 isolated event, no synthesizer call' : 'Single domain \u2192 no synthesizer call needed'; }
function trackModel(inc) {
  const run = inc.state === 'running', mode = inc.mode, f = inc.final && !inc.final.preliminary ? inc.final : null; // stage 1 is not the report
  const ns = (inc.sensors || []).length, na = (inc.agents || []).length;
  const fast = !!(f && isFastModel(f.model));
  const steps = [];
  const nfl = (inc.sensors || []).filter((x) => !x.context).length, nctx = ns - nfl;
  const orch = ((inc.timeline || []).find((x) => /^Orchestrator:/.test(x.msg || '')) || {}).msg;
  steps.push({ t: 'Detected', s: nfl + ' sensor' + (nfl === 1 ? '' : 's') + ' flagged by the event gate' + (nctx ? ' \u00B7 ' + nctx + ' related checked' : ''), st: 'done' });
  if (mode === 1) steps.push({ t: 'Agent on NPU', s: 'Skipped — Rules mode uses no AI', st: 'skip' });
  else if (mode === 2) steps.push({ t: 'Agent on NPU', s: f ? 'One model call finished' : run ? 'Reading all sensors in one prompt' : 'No result', st: f ? 'done' : run ? 'active' : 'fail' });
  else { const all = na >= ns && ns > 0; steps.push({ t: 'Agents on NPU + context agents', s: (orch ? orch.replace(/^Orchestrator:\s*/, '') + ' \u00B7 ' : '') + na + ' of ' + ns + ' finished', st: all ? 'done' : run ? 'active' : 'fail' }); }
  const agentsDone = steps[1].st === 'done' || steps[1].st === 'skip';
  if (mode === 1) steps.push({ t: 'Synthesizer', s: 'Skipped — rule summary used', st: 'skip' });
  else if (mode === 2) steps.push({ t: 'Report written', s: 'Same call writes the cross-domain report', st: f ? 'done' : run ? 'pending' : 'fail' });
  else if (fast) steps.push({ t: 'Synthesizer', s: fastText(f.model), st: 'done' });
  else steps.push({ t: 'Synthesizer', s: f ? 'Cross-domain report written' : agentsDone ? (run ? 'Combining agent findings' : 'No report produced') : 'Waits for the agents', st: f ? 'done' : agentsDone ? (run ? 'active' : 'fail') : 'pending' });
  if (mode === 1) steps.push({ t: 'Safety check', s: 'Skipped — nothing from AI to check', st: 'skip' });
  else steps.push({ t: 'Safety check', s: f ? (f.valid ? 'Policy gate passed' : 'Policy gate rejected the output') : run ? 'Checks every AI output before you see it' : 'Not reached', st: f ? (f.valid ? 'done' : 'fail') : run ? 'pending' : 'fail' });
  const decided = inc.approval && inc.approval !== 'pending';
  steps.push({ t: 'Awaiting your decision', s: run ? 'Starts when the analysis is ready' : decided ? (inc.approval === 'approved' ? 'Taken by an operator' : 'Dismissed') : 'Needs your decision — nothing happens automatically', st: run ? 'pending' : decided ? 'done' : 'active' });
  let done = 0; steps.forEach((x) => { if (x.st === 'done' || x.st === 'skip') done += 1; else if (x.st === 'active') done += 0.5; else if (x.st === 'fail') done += 1; });
  const rejected = mode !== 1 && !run && (!f || !f.valid);
  const title = run ? (mode === 1 ? 'Running the rules ...' : mode === 2 ? 'The model is reading your sensors ...' : na < ns ? 'Agents are thinking ...' : 'Writing the report ...')
    : inc.state === 'failed' ? 'Interrupted (the app restarted mid-analysis) - rerun it' : inc.approval === 'approved' ? 'Approved' : inc.approval === 'dismissed' ? 'Dismissed' : rejected ? 'Done, but the safety check flagged it' : 'Ready for your decision';
  return { steps, pct: Math.min(100, (done / steps.length) * 100), title, run };
}
function trackCard(inc) {
  const tm = trackModel(inc);
  const el = elapsedOf(inc), usual = usualSecs(inc.mode);
  const list = h('ol', { class: 'steps' });
  const fill = h('i', { style: 'height:' + (S.trkPct[inc.id] != null ? S.trkPct[inc.id] : 0) + '%' });
  list.append(h('div', { class: 'line' }, fill));
  tm.steps.forEach((x) => {
    list.append(h('li', { class: 'step ' + (x.st === 'done' ? 'done' : x.st) },
      h('div', { class: 'dotc' }, x.st === 'done' ? icon('check') : x.st === 'fail' ? icon('x') : null),
      h('div', {}, h('div', { class: 'st', text: x.t }), h('div', { class: 'ss', text: x.s }))));
  });
  requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.height = tm.pct + '%'; }));
  S.trkPct[inc.id] = tm.pct;
  return h('div', { class: 'card trk' },
    h('div', { class: 'trk-h' },
      h('div', {}, h('h2', { text: tm.title }), h('p', { text: 'Mode ' + inc.mode + ' · ' + ['Rules', 'Single model', 'Multi-agent'][inc.mode - 1] })),
      h('div', { class: 'eta' }, h('b', { 'data-elapsed': '1', text: el == null ? '…' : el.toFixed(1) + 's' }),
        h('span', { text: tm.run ? 'elapsed' + (usual ? ' · usually ~' + usual.toFixed(1) + 's' : '') : 'total' }))),
    list);
}
function updateElapsed() {
  const inc = S.inc;
  if (inc && inc.state === 'running') { const e = elapsedOf(inc); $$('[data-elapsed]').forEach((x) => setText(x, e == null ? '…' : e.toFixed(1) + 's')); }
}

/* ----- token streaming ----- */
// Tokens arrive as SSE "token" events (one NPU call = one ref; the first chunk of a call carries
// reset, every chunk a per-call seq). A batched htpd run streams all agents at once, so events are
// only buffered here and painted once per animation frame. A gap in seq (dropped event, page opened
// mid-run, reconnect) is repaired from /api/streams, which holds each call's text so far.
// Refinements (1.5 h / 3 h) stream as "rtoken" into S.rstream and a separate panel: the report page
// keeps showing the finished analysis until the refined one replaces it.
function streamKeyOf(incId, ref) { return incId + ':' + ref; }
const ST = { seq: {}, first: {}, batch: {}, rbatch: {}, rseq: {}, rlast: {}, dirty: new Set(), cards: new Set(), raf: 0, sync: {} };
S.rstream = {};
function onToken(d, refine) {
  if (!d || !d.incident || !d.ref) return;
  const k = streamKeyOf(d.incident, d.ref), buf = refine ? S.rstream : S.stream, seqs = refine ? ST.rseq : ST.seq;
  if (d.reset) { buf[k] = ''; seqs[k] = 0; }
  if (d.seq != null) {
    const want = (seqs[k] || 0) + 1;
    if (d.seq < want) return;                                  // already have it (resync overlap)
    if (d.seq > want) { resyncStreams(d.incident); return; }   // missed something: fetch the whole text
    seqs[k] = d.seq;
  }
  buf[k] = (buf[k] || '') + (d.text || '');
  if (refine) { ST.rlast[d.incident] = Date.now(); }
  else {
    if (ST.first[k] == null) ST.first[k] = Date.now();
    // The card preview is updated whether or not the incident is open, so the list itself shows the
    // model thinking. Without this, tokens were only ever painted into an already-open detail sheet,
    // so from the incident list the answer simply appeared all at once after ~17 s.
    S.cardStream[d.incident] = ((S.cardStream[d.incident] || '') + (d.text || '')).slice(-240);
    ST.cards.add(d.incident);
  }
  if (S.incId === d.incident) ST.dirty.add((refine ? 'r|' : '') + d.ref);
  if (!ST.raf) ST.raf = requestAnimationFrame(paintStreams);
}
// keep a stream pinned to its end only while the reader is at the end (they may scroll up to read)
function paintPre(el, text) {
  if (el.textContent === text) return;
  const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  el.textContent = text;
  if (stick) el.scrollTop = el.scrollHeight;
}
function paintStreams() {
  ST.raf = 0;
  for (const id of ST.cards) { const cs = $('.cstream[data-cs="' + id + '"]'); if (cs) paintPre(cs, S.cardStream[id] || ''); }
  ST.cards.clear();
  if (!S.incId) { ST.dirty.clear(); return; }
  let missing = false;
  for (const key of ST.dirty) {
    const refine = key.startsWith('r|'), ref = refine ? key.slice(2) : key, k = streamKeyOf(S.incId, ref);
    const el = $('#inc-detail [data-' + (refine ? 'rs' : 's') + '="' + ref + '"]');
    if (!el) { missing = true; continue; }
    paintPre(el, (refine ? S.rstream : S.stream)[k] || '');
    if (!refine) {
      // rebuild the pill only when its words change (a rebuilt spinner restarts its animation)
      const pill = $('#inc-detail [data-sp="' + ref + '"]'), p = pill && streamPill(S.incId, ref);
      if (p && pill.textContent !== p.textContent) fill(pill, p);
    }
  }
  ST.dirty.clear();
  // a call that has no box yet (first token of an agent, a refinement starting): rebuild once
  if (missing && !paintStreams.t) paintStreams.t = setTimeout(() => { paintStreams.t = 0; refreshIncDetail(true); }, 200);
}
async function resyncStreams(id) {
  if (ST.sync[id]) return; ST.sync[id] = 1;
  try {
    const r = await api('/api/streams?incident=' + encodeURIComponent(id));
    const take = (list, buf, seqs) => (list || []).forEach((s) => {
      const k = streamKeyOf(id, s.ref);
      if ((seqs[k] || 0) <= s.seq) { buf[k] = s.text; seqs[k] = s.seq; }
    });
    take(r.streams, S.stream, ST.seq); take(r.refine_streams, S.rstream, ST.rseq);
    if ((r.refine_streams || []).length) ST.rlast[id] = ST.rlast[id] || Date.now();
    if (r.batch) ST.batch[id] = { at: Date.now() - r.batch.ago_ms, refs: new Set(r.batch.refs || []) };
    if (r.refine_batch) ST.rbatch[id] = { at: Date.now() - r.refine_batch.ago_ms, refs: new Set(r.refine_batch.refs || []) };
    (r.streams || []).forEach((s) => { const k = streamKeyOf(id, s.ref); if (ST.first[k] == null && s.text) ST.first[k] = -1; });
    if (S.incId === id && S.inc) renderIncDetail();
  } catch (e) { /* the next token or incident event retries */ }
  finally { setTimeout(() => { delete ST.sync[id]; }, 1000); }
}
function onBatch(d) {
  if (!d || !d.incident) return;
  (d.refine ? ST.rbatch : ST.batch)[d.incident] = { at: Date.now(), refs: new Set(d.refs || []) };
  if (d.refine) ST.rlast[d.incident] = Date.now();
  if (S.incId === d.incident && S.inc) renderIncDetail();
}
// thinking (in the batch, reading its prompt) -> streaming (first token after N s) -> done (card replaced)
function streamPill(incId, ref) {
  const k = streamKeyOf(incId, ref), b = ST.batch[incId], tx = S.stream[k], f = ST.first[k];
  const spin = h('span', { class: 'spin', style: 'width:12px;height:12px;border-width:2px' });
  if (tx) return h('span', { class: 'pill orange' }, spin, 'Generating' + (b && f > 0 ? ' · first token ' + ((f - b.at) / 1000).toFixed(1) + ' s' : ''));
  return h('span', { class: 'pill orange' }, spin, b && b.refs.has(ref) ? 'Reading the readings' : 'On the NPU');
}
function liveCard(incId, ref, role, text, note) {
  return h('div', { class: 'card agent st-none' },
    h('div', { class: 'rep-h' }, h('b', { text: ref + ' · ' + (role ? (roleTitle[role] || role) + ' agent' : 'Model') }), h('span', { 'data-sp': ref }, streamPill(incId, ref))),
    h('pre', { class: 'stream live', 'data-s': ref, text: text || '' }),
    h('div', { class: 'muted', style: 'font-size:13px;margin-top:6px', text: note }));
}
// a 1.5 h / 3 h refinement in progress: its agents and report typing live, below the current report
const STAGE_NEXT = { early: '1.5h', '1.5h': '3h' };
function refiningCard(inc) {
  const last = ST.rlast[inc.id];
  if (!last || Date.now() - last > 90000) return null; // nothing heard for 90 s: it finished or stepped aside
  const pre = streamKeyOf(inc.id, '');
  const refs = Object.keys(S.rstream).filter((k) => k.startsWith(pre)).map((k) => k.slice(pre.length));
  const rb = ST.rbatch[inc.id];
  if (rb) rb.refs.forEach((r) => { if (!refs.includes(r)) refs.push(r); });
  if (!refs.length) return null;
  refs.sort((a, b) => (a === 'final') - (b === 'final') || a.localeCompare(b, undefined, { numeric: true }));
  const stage = STAGE_NEXT[inc.refine_stage || 'early'];
  return h('div', { class: 'card refining' },
    h('div', { class: 'rep-h' }, h('b', { text: 'Re-checking now' + (stage ? ' (' + (stage === '3h' ? '3 h' : '1.5 h') + ' view)' : '') }),
      h('span', { class: 'pill orange' }, h('span', { class: 'spin', style: 'width:12px;height:12px;border-width:2px' }), 'Live')),
    h('p', { class: 'muted', style: 'font-size:13.5px;margin:4px 0 0', text: 'The AI is reading a longer stretch of the sensors. The current result stays until the new one is ready.' }),
    refs.map((r) => h('div', { class: 'rf-row' }, h('span', { class: 'rf-ref', text: r === 'final' ? 'Report' : r }),
      h('pre', { class: 'stream live rf', 'data-rs': r, text: S.rstream[streamKeyOf(inc.id, r)] || '' }))));
}
function clearRefine(id) {
  const pre = streamKeyOf(id, '');
  for (const k of Object.keys(S.rstream)) if (k.startsWith(pre)) { delete S.rstream[k]; delete ST.rseq[k]; }
  delete ST.rbatch[id]; delete ST.rlast[id];
}

// long operator notes show three lines in the footer; tap/Enter shows the whole note (scrolls if huge)
let footNoteOpen = null; // incident id whose note is expanded (survives footer re-renders)
function toggleFootNote(e) { const n = e.currentTarget, on = !n.classList.contains('open'); n.classList.toggle('open', on); n.setAttribute('aria-expanded', String(on)); footNoteOpen = on ? n.dataset.id : null; }
function renderIncFoot(inc, force) {
  const f = $('#inc-foot'), wf = wfOfI(inc), ff = S.footForm && S.footForm.id === inc.id ? S.footForm : null;
  const sig = [inc.id, inc.approval, inc.state, wf, inc.owner, inc.suggest_outcome, inc.outcome, ff ? ff.kind + ff.outcome : '', opName(), prelimOpen(inc)].join('|');
  if (!force && f.dataset.sig === sig) return; f.dataset.sig = sig;
  if (wf === 'closed') {
    const by = inc.closed_by === 'system' ? 'automatically' : inc.closed_by ? 'by ' + inc.closed_by : '';
    const note = (inc.outcome ? (OUTCOME_TEXT[inc.outcome] || nice(inc.outcome)) : 'Decision recorded') + (by ? ' · ' + by : '') + (inc.closed_at ? ' · ' + dclock(inc.closed_at) : '') +
      ((inc.outcome_note || inc.approval_note) && (inc.outcome_note || inc.approval_note) !== 'auto' ? ' · Note: ' + (inc.outcome_note || inc.approval_note) : '') + '. Nothing was switched automatically.';
    f.replaceChildren(h('div', { class: 'foot-row' }, h('span', { class: 'pill ghost', text: '◻ CLOSED' }), h('span', { class: 'muted foot-note' + (footNoteOpen === inc.id ? ' open' : ''), 'data-id': inc.id, role: 'button', tabindex: '0', 'aria-expanded': String(footNoteOpen === inc.id), title: 'Tap to show the whole note', text: note, onclick: toggleFootNote, onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleFootNote(e); } } })));
    return;
  }
  if (ff) { f.replaceChildren(footForm(inc)); return; }
  const pre = prelimOpen(inc), busy = inc.state === 'running'; // preliminary shown: act now, the AI report merges in
  const running = wf === 'analysing' && !pre, failed = wf === 'interrupted', owned = wf === 'in_progress' || (wf === 'resolved' && inc.owner);
  const hint = running ? 'Waiting for the analysis to finish ...' : pre && !owned ? 'Preliminary report: you can take this and tick steps now. The AI report will update the list; your ticks stay.' : failed ? 'No report: re-run this incident (Technical details), or dismiss it with a note.'
    : owned ? (inc.owner ? inc.owner + ' is on it' + (inc.acked_at ? ' since ' + dclock(inc.acked_at) : '') + '. ' : '') + 'Tick the steps above, then close it with how it ended.'
      : 'I\'m on it = you take this and work through the steps. Dismiss = not needed (note required). Nothing switches automatically.';
  const me = opName();
  fill(f, h('p', { class: 'foot-hint', text: hint }),
    h('div', { class: 'foot-row' },
      h('button', { class: 'btn danger', type: 'button', disabled: running || busy ? true : null, text: 'Dismiss…', onclick: () => openFootForm(inc, 'dismiss') }),
      owned || wf === 'resolved'
        ? h('button', { class: 'btn primary', type: 'button', disabled: busy ? true : null, title: busy ? 'Close once the AI report is in' : null, text: 'Close…', onclick: () => openFootForm(inc, 'close') })
        : h('button', { class: 'btn primary', type: 'button', disabled: running || failed ? true : null, onclick: () => wfAct(inc, '/ack', {}, 'Recorded: you are on it') },
          'I\'m on it' + (me ? ' (' + me + ')' : ''))),
    owned && inc.owner && me && inc.owner !== me && !running ? h('button', { type: 'button', class: 'btn sm plain', onclick: () => wfAct(inc, '/ack', {}, 'You took this over') }, 'Take over as ' + me) : null);
}
/* ----- severity: decided by the cross-domain reasoner (backend severity.go) -----
   The severity an incident opens with is the rule engine's and only provisional; the agents often
   disagree. So nothing is coloured until the analysis has finished and the reasoner has decided:
   a running incident reads as neutral "analysing", never as a red alarm that later turns out fine. */
const SEV_LABEL = { critical: 'Critical', warning: 'Warning', normal: 'Fine', info: 'Fine', sensor_fault: 'Fault' };
function sevOf(i) {
  if (i.state === 'running') return { k: 'pending', t: 'Analysing' };
  if (i.state === 'failed') return { k: 'pending', t: 'Interrupted' };
  if (!SEV_LABEL[i.severity]) return { k: 'pending', t: nice(i.severity) };
  return { k: i.severity === 'info' ? 'normal' : i.severity, t: SEV_LABEL[i.severity] };
}
function sevTag(i) {
  const v = sevOf(i);
  return h('span', { class: 'sevtag sev-' + v.k, title: v.k === 'pending' ? 'Severity is decided by the cross-domain reasoner when the analysis finishes' : 'Severity decided by the cross-domain reasoner' },
    h('i', { class: 'sdot', 'aria-hidden': 'true' }), v.t);
}

/* ----- flagged-sensor chips + floating sensor sheet ----- */
const CTX_GLYPH = { normal: '○', warning: '△', critical: '□', sensor_fault: '◇' }; // hollow: seen, not flagged
// What this sensor's final finding is: its agent's (when it passed the policy gate), else the rule
// finding the report fell back to. Mode 1 and 2 have no per-sensor agents.
function sensorVerdict(inc, s) {
  const a = (inc.agents || []).find((x) => x.ref === s.ref) || null, rf = s.rule_finding || {};
  // the 12 h check raises a sensor its agent called normal to a warning (title.go longRangeRaise)
  if (a && a.parsed && a.valid) return { st: a.parsed.status === 'normal' && !s.context && (s.long_range || []).length ? 'warning' : a.parsed.status, a, f: a.parsed };
  if (a) return { st: rf.status, a, f: null };
  // related sensors are only seen (most get a CPU context agent at the end): show their rule view meanwhile
  if (inc.state === 'running' && inc.mode !== 1 && !s.context) return { st: 'pending', a: null, f: null };
  return { st: rf.status, a: null, f: null };
}
function sensorChip(inc, s) {
  const v = sensorVerdict(inc, s), name = metricName(s.metric), pend = v.st === 'pending';
  const glyph = pend ? '◌' : s.context ? (CTX_GLYPH[v.st] || '○') : (STATUS_GLYPH[v.st] || '○');
  const said = pend ? 'waiting for the AI' : (STATUS_LABEL[v.st] || nice(v.st));
  return h('button', { type: 'button', class: 'schip ' + stClass(pend ? 'none' : v.st) + (s.context ? ' ctx' : '') + (pend ? ' pend' : ''), 'data-ref': s.ref, title: s.location || s.node,
    'aria-haspopup': 'dialog', 'aria-label': name + ', ' + (s.location || s.node) + (s.context ? ', checked for context' : '') + ': ' + said + '. Open details',
    onclick: (e) => openSensorSheet(inc.id, s.ref, e.currentTarget) },
  h('i', { class: 'sglyph', 'aria-hidden': 'true', text: glyph }),
  h('span', { class: 'schip-t' }, h('b', { text: name }), h('span', { text: placeShort(s.location || s.node) + ' · ' + said })));
}
const FS = { inc: null, ref: null, opener: null, sig: '' };
function openSensorSheet(incId, ref, opener) {
  const fs = $('#fs'), was = !fs.hidden;
  FS.inc = incId; FS.ref = ref; FS.opener = opener || document.activeElement; FS.sig = '';
  fs.hidden = false;
  // Android back (WebView goBack) closes the sheet instead of leaving the tab
  if (!was) { try { history.pushState({ fs: 1 }, ''); } catch (e) { /* ignore */ } }
  renderSensorSheet(true);
  requestAnimationFrame(() => fs.classList.add('open'));
  $('#fs-x').focus();
}
function closeSensorSheet(fromHistory) {
  const fs = $('#fs'); if (fs.hidden) return;
  fs.classList.remove('open'); fs.hidden = true;
  const op = FS.opener, ref = FS.ref;
  FS.inc = FS.ref = FS.opener = null; FS.sig = '';
  hidePop(true);
  if (!fromHistory && history.state && history.state.fs) { try { history.back(); } catch (e) { /* ignore */ } }
  // the chips are rebuilt on every refresh: hand focus back to the current chip for that sensor
  const back = op && op.isConnected ? op : ref && $('#inc-detail .schip[data-ref="' + ref + '"]');
  if (back && $('#isheet').classList.contains('open')) back.focus();
}
function trapFocus(e) {
  if (e.key !== 'Tab') return;
  const f = $$('#fs button, #fs summary, #fs [tabindex="0"]').filter((x) => x.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
function renderSensorSheet(force) {
  const inc = S.inc; if (!FS.ref) return;
  if (!inc || inc.id !== FS.inc) { closeSensorSheet(); return; }
  const s = (inc.sensors || []).find((x) => x.ref === FS.ref); if (!s) return;
  const v = sensorVerdict(inc, s), a = v.a, p = v.f, rf = s.rule_finding;
  const sig = JSON.stringify([v.st, a && a.raw, a && a.valid, inc.state, inc.refine_stage, s.window_end, S.eng]);
  if (!force && sig === FS.sig) return;
  FS.sig = sig;
  const bd = $('#fs-bd'), sc = bd.scrollTop;
  const name = metricName(s.metric), occ = s.role === 'occupancy', n = (s.window || []).length;
  const pts = (s.window || []).map((x, i) => [(s.window_end || 0) - (n - 1 - i) * 300, x]);
  setText($('#fs-t'), (S.eng ? s.ref + ' · ' : '') + name + ' · ' + placeShort(s.location || s.node));
  const kv = (rows) => h('dl', { class: 'kv', style: 'margin-top:10px' }, rows.map(([k, val]) => [h('dt', { text: k }), h('dd', { text: val })]));
  const patChip = (f) => h('span', { class: 'chip', html: patIcon(f.pattern) + esc(patternPlain(f.pattern)) });
  const obs = (list) => h('ul', { class: 'obs' }, (list || []).map((o) => h('li', {}, S.eng ? evChipsInText(o, s.evidence) : stripRefs(o))));
  const chart = h('div', { class: 'fs-chart' });
  const out = [
    h('div', { class: 'rep-h' }, v.st === 'pending' ? h('span', { class: 'pill ghost', text: 'Waiting for the AI' }) : pill(v.st),
      s.context ? h('span', { class: 'pill ghost', text: 'Checked for context' }) : null),
    h('p', { class: 'muted', style: 'margin:6px 0 10px', text: (s.location || '-') + (S.eng ? ' · ' + s.node : '') }),
    s.why ? h('div', { class: 'banner', style: 'margin-bottom:10px;font-weight:500;font-size:13.5px;padding:8px 12px' }, icon('info', 20), h('span', { text: 'Checked because: ' + s.why })) : null,
    chart,
    h('p', { class: 'muted fs-cap', text: n ? 'The readings the AI looked at: ' + hm(pts[0][0]) + ' → ' + hm(pts[n - 1][0]) + ' IST (' + n + ' readings)' : 'No readings stored for this sensor.' }),
    // 12 h checks for what the 4 h agent misses (longrange.go); given to the reasoner as S#.E9/E10
    (s.long_range || []).length ? h('div', { class: 'banner', style: 'margin:4px 0 10px;font-size:13.5px;padding:8px 12px;display:block' },
      h('div', { style: 'font-weight:600;margin-bottom:4px', text: 'Longer view (last 12 h)' }),
      ...s.long_range.map((l) => h('div', { text: S.eng ? l.text.replace(/^12 h view: /, '') + ' [' + l.id + ']' : l.text.replace(/^12 h view: /, '').replace(/\s*\(r2 [^)]*\)/, '') }))) : null,
  ];
  const ctxA = a && isCtxAgent(a);
  const who = !S.eng ? 'What the AI found' : ctxA ? 'Context agent (rules, CPU)' : a ? (roleTitle[s.role] || nice(s.role)) + ' agent (NPU)' : inc.mode === 3 ? (roleTitle[s.role] || nice(s.role)) + ' agent' : 'Agent';
  const sec = h('div', { class: 'fs-sec' }, h('h3', { text: who + (S.eng ? ' says' : '') }));
  if (p) {
    const cw = confWord(p.confidence);
    sec.append(h('div', { class: 'rep-h', style: 'margin-top:8px' }, pill(p.status), patChip(p)), earlyNote(inc, s, p) || '',
      kv([['Likely cause', causePlain(p.likely_cause)], ['Confidence', cw.w + (S.eng ? ' (' + pct(p.confidence) + ')' : '')], ['Suggested action', actionText(p.action)]]),
      obs(p.observations));
    if (!ctxA && S.eng) sec.append(h('div', { style: 'margin-top:10px' }, gate(a.valid, a.errors)), statChips(a));
  } else if (a) sec.append(S.eng ? h('div', { style: 'margin-top:8px' }, gate(a.valid, a.errors)) : '', h('p', { class: 'muted', style: 'margin-top:8px', text: 'The AI answer for this sensor failed the safety check, so the automatic rule result below is used.' }));
  else if (v.st === 'pending') sec.append(h('p', { class: 'muted', style: 'margin-top:6px', text: inc.mode === 2 ? 'One AI call reads every sensor; its result appears in the report.' : 'The AI has not answered for this sensor yet. Its result appears here when it does.' }));
  else sec.append(h('p', { class: 'muted', style: 'margin-top:6px', text: inc.mode === 1 ? 'No AI was used (rules only). The rule result is below.' : inc.mode === 2 ? 'One AI call read every sensor at once, so there is no per-sensor answer. See the report.' : 'No AI result stored for this sensor.' }));
  out.push(sec);
  // the rule that raised the alarm, whenever there is no agent finding or the agent sees it differently
  if (rf && (!p || p.status !== rf.status || p.pattern !== rf.pattern)) {
    out.push(h('div', { class: 'fs-sec' }, h('h3', { text: p ? 'Automatic rule check (raised the alarm)' : 'Automatic rule check' }),
      h('div', { class: 'rep-h', style: 'margin-top:8px' }, pill(rf.status), patChip(rf)),
      kv([['Likely cause', causePlain(rf.likely_cause)], ['Suggested action', actionText(rf.action)]]),
      p ? null : obs(rf.observations)));
  }
  const ek = inc.id + ':' + s.ref + ':ev';
  if (S.eng) out.push(h('details', { open: S.open.has(ek) ? true : null, ontoggle: (e) => { e.target.open ? S.open.add(ek) : S.open.delete(ek); } },
    h('summary', { text: 'Evidence ' + s.ref + '.E1..E' + (s.evidence || []).length }),
    h('ul', { class: 'evlist', style: 'padding:6px 16px 10px' }, (s.evidence || []).map((e) => h('li', {}, h('b', { text: e.ID }), h('span', { text: e.Text }))))));
  bd.replaceChildren(...out.filter(Boolean));
  renderBigChart(chart, { points: pts, metric: name }, 4, occ, 210);
  bd.scrollTop = sc;
}
/* ----- detail page pieces ----- */
// One collapsible section. Open state is remembered only once the operator has toggled it, so a
// section can default open while the incident runs and closed once it is done.
function fold(k, title, defOpen, ...kids) {
  const open = k in S.fold ? S.fold[k] : defOpen, id = 'fold-' + k.replace(/[^\w-]/g, '_');
  const bd = h('div', { class: 'fold-bd', id, hidden: open ? null : true }, kids);
  const btn = h('button', { type: 'button', class: 'fold-h', 'aria-expanded': open ? 'true' : 'false', 'aria-controls': id,
    onclick: () => { const o = btn.getAttribute('aria-expanded') !== 'true'; S.fold[k] = o; btn.setAttribute('aria-expanded', o ? 'true' : 'false'); bd.hidden = !o; } },
  h('span', { text: title }), h('i', { class: 'chev', 'aria-hidden': 'true' }));
  return h('div', { class: 'fold' }, btn, bd);
}
// After the analysis the step timeline has nothing left to say; only the latency stays.
function doneLine(inc) {
  if (inc.state === 'failed') return h('div', { class: 'donein fail' }, icon('alert', 16), h('span', { text: 'Interrupted: the app restarted mid-analysis. Rerun it below.' }));
  const el = elapsedOf(inc);
  return h('div', { class: 'donein' }, h('span', { text: 'Done in' }), h('b', { text: el == null ? '-' : el.toFixed(1) + ' s' }));
}
/* ----- early alert + refined re-analysis (backend refine.go) -----
   A Mode-3 incident is analysed when the alert fires (~40 min into the event) and again on the
   windows that end 1.5 h and 3 h later in sensor time, when the agents read the shape far better.
   The page says which analysis it shows, when the next is due, and what each one changed. */
const STAGE_TEXT = { provisional: 'Provisional AI', early: 'At alert', '1.5h': 'Re-checked 1.5 h', '3h': 'Re-checked 3 h' };
function stageTag(i) {
  if (!STAGE_TEXT[i.refine_stage]) return null;
  const prov = i.refine_stage === 'provisional';
  const ref = i.refine_stage !== 'early' && !prov;
  return h('span', { class: 'stagetag' + (prov ? ' prov' : ref ? ' ref' : ''), text: STAGE_TEXT[i.refine_stage],
    title: prov ? 'AI read of a young event window; the full analysis replaces it when the event has lasted 40 min'
      : ref ? 'The AI looked again with a longer view of the event' : 'First analysis at the alert; checked again after 1.5 h and 3 h' });
}
function refineLine(inc) {
  if (inc.next_refine_sim && NEXT_STAGE[inc.refine_stage]) return h('p', { class: 'refnext' }, etaEl(inc), ' (due ' + hm(inc.next_refine_sim) + ' sensor time)');
  const t = inc.next_refine_sim ? 'Next re-check at ' + hm(inc.next_refine_sim) + ' (sensor time)' : inc.refine_note || '';
  return t ? h('p', { class: 'refnext', text: t }) : null;
}
// what one revision changed against the one before it, per flagged sensor
function revChanges(prev, cur) {
  const was = {}; ((prev && prev.sensors) || []).forEach((s) => { was[s.ref] = s; });
  const out = [];
  (cur.sensors || []).forEach((s) => {
    const name = METRIC_NAME[s.metric] || nice(s.metric), p = was[s.ref];
    if (s.kept || s.no_data) out.push(name + ': ' + s.note);
    else if (p && (p.pattern !== s.pattern || p.status !== s.status)) out.push(name + ': ' + patternPlain(p.pattern) + ' (' + (STATUS_LABEL[p.status] || nice(p.status)) + ') → ' + patternPlain(s.pattern) + ' (' + (STATUS_LABEL[s.status] || nice(s.status)) + ')');
  });
  return out;
}
function historyFold(inc) {
  const rv = inc.revisions || []; if (!rv.length) return null;
  const items = rv.map((r, k) => {
    const ch = k ? revChanges(rv[k - 1], r) : [];
    return h('li', {},
      h('div', { class: 'hh' }, h('span', { class: 'stagetag' + (k ? ' ref' : ''), text: STAGE_TEXT[r.stage] || r.stage }), sevTag({ state: 'done', severity: r.severity }),
        h('span', { class: 'muted', text: 'windows to ' + hm(r.sim_end) + (r.npu_calls ? ' · ' + r.npu_calls + ' NPU call' + (r.npu_calls === 1 ? '' : 's') : '') })),
      h('div', { class: 'ht', text: r.title }),
      h('div', { class: 'hc', text: !k ? 'Analysed at the alert' : ch.length ? ch.join(' · ') : 'Same findings' }));
  }).reverse(); // newest first
  return fold(inc.id + ':hist', 'History (' + rv.length + ')', false, h('div', { class: 'card' }, h('ul', { class: 'hist' }, items)));
}
// this sensor at the early stage, when the refined view says something else
function earlyNote(inc, s, p) {
  const rv = inc.revisions || []; if (rv.length < 2) return null;
  const e = (rv[0].sensors || []).find((x) => x.ref === s.ref), cur = (rv[rv.length - 1].sensors || []).find((x) => x.ref === s.ref);
  if (cur && cur.kept && cur.note) return h('p', { class: 'refnext', text: cur.note[0].toUpperCase() + cur.note.slice(1) });
  if (!e || !p || (e.pattern === p.pattern && e.status === p.status)) return null;
  return h('p', { class: 'refnext', text: 'At the alert it was ' + patternPlain(e.pattern) + ' (' + (STATUS_LABEL[e.status] || nice(e.status)) + ')' });
}

function reasonerCard(inc) {
  const pre = inc.final && inc.final.preliminary ? inc.final : null; // two-stage report: stage 1 while the reasoner writes
  const f = pre ? null : inc.final, running = inc.state === 'running', fast = !!(f && isFastModel(f.model)), v = sevOf(inc);
  const card = h('div', { class: 'card reasoner sev-' + v.k },
    h('div', { class: 'rep-h rz-h' }, h('h3', { text: inc.mode === 1 ? 'Rule summary (Mode 1, no AI)' : 'Cross-domain reasoner' }), sevTag(inc)));
  const wait = (t, s) => h('div', { class: 'rz-wait' }, h('b', { text: t }), h('p', { class: 'muted', text: s }));
  if (inc.mode === 1) {
    if (!running && inc.mode1_report) card.append(reportBody(inc, inc.mode1_report));
    else card.append(running ? wait('Running the rules …', 'Rules mode: statistics and a rule engine decide. No AI model is used.') : h('div', { class: 'muted', text: 'No rule summary stored.' }));
  } else if (f) {
    if (fast) card.append(h('div', { class: 'banner', style: 'margin-bottom:12px' }, icon('check'), h('span', { text: fastText(f.model) + '. The agent finding became the report instantly.' })));
    card.append(h('div', { class: 'rep-h', style: 'margin-bottom:12px' }, gate(f.valid, f.errors), fast ? null : modelBadge(f.model || 'model', false)));
    if (!fast) { const sc = statChips(f); if (sc) card.append(sc); }
    if (f.parsed) {
      if (!f.valid) card.append(h('div', { class: 'errs', style: 'margin:10px 0;padding:0;list-style:none', text: 'Rejected by the policy gate: do not act on the output below.' }));
      card.append(h('div', { style: 'margin-top:12px' }, reportBody(inc, f.parsed)));
    } else card.append(h('div', { class: 'muted', style: 'margin-top:10px', text: 'The model output could not be parsed into a report.' }));
    if (!fast) card.append(details(inc.id + ':final:raw', 'Raw model output', f.raw), details(inc.id + ':final:prompt', 'Prompt (synthesizer)', f.prompt));
  } else if (running && pre) {
    const tx = S.stream[streamKeyOf(inc.id, 'final')];
    card.append(h('div', { class: 'banner', style: 'margin-bottom:12px' }, icon('clock'), h('span', { text: pre.note ? pre.note.replace(/ - /g, ' — ') + '. The AI report will replace this one.' : 'Preliminary report from the rules and the agent findings. The AI reasoner is writing the full report and will replace this one.' })));
    if (pre.parsed) card.append(h('div', { style: 'margin-top:12px;opacity:.85' }, reportBody(inc, pre.parsed)));
    card.append(h('pre', { class: 'stream live', 'data-s': 'final', text: tx || '' }), h('div', { class: 'muted', style: 'font-size:13px;margin-top:6px', text: 'Reasoner typing live …' }));
  } else if (running) {
    // reserved from the start so the page does not jump when the report arrives; no animation
    const tx = S.stream[streamKeyOf(inc.id, 'final')];
    const npu = (inc.sensors || []).filter((s) => !s.context).length, got = (inc.agents || []).filter((a) => !isCtxAgent(a)).length;
    const allAgents = inc.mode === 2 || got >= npu;
    if (tx || allAgents) card.append(h('pre', { class: 'stream live', 'data-s': 'final', text: tx || '' }),
      h('div', { class: 'muted', style: 'font-size:13px;margin-top:6px', text: inc.mode === 2 ? 'One model call reads every sensor and writes the report, typing live …' : 'Combining the agent findings, typing live …' }));
    else card.append(wait('Waiting for agents …', got + ' of ' + npu + ' flagged sensor' + (npu === 1 ? '' : 's') + ' answered. The reasoner then decides root cause, severity and action across domains.'));
  } else card.append(h('div', { class: 'muted', text: 'No cross-domain report was produced.' }));
  return card;
}

/* ----- operator summary (what is happening / why it matters / what to do / what changed) ----- */
// The result the operator acts on: the AI report when it passed the safety check, else the rule result.
function mainReport(inc) {
  const f = inc.final;
  if (inc.mode === 1) return inc.mode1_report ? { r: inc.mode1_report, src: 'rules' } : null;
  if (f && f.preliminary && f.parsed) return { r: f.parsed, src: 'rules', preliminary: true };
  if (f && f.valid && f.parsed) return { r: f.parsed, src: 'ai' };
  if (f && inc.mode1_report) return { r: inc.mode1_report, src: 'rules', rejected: true };
  return null;
}
const REV_LABEL = { early: 'At the alert', '1.5h': 'Re-check after 1.5 h', '3h': 'Re-check after 3 h' };
const SEV_RANK = { normal: 0, info: 0, sensor_fault: 1, warning: 2, critical: 3 };
// the re-checks as a story: one row per analysis, each saying what it changed (elevated / curbed / resolved)
function revStory(inc) {
  const rv = inc.revisions || [];
  const rows = rv.map((r, k) => {
    const pv = rv[k - 1];
    let ch = 'First analysis', cls = 'first';
    if (pv) {
      const a = SEV_RANK[pv.severity] || 0, b = SEV_RANK[r.severity] || 0;
      [ch, cls] = b > a ? ['↑ Got worse', 'elevated'] : b < a ? (b === 0 ? ['✓ Resolved', 'resolved'] : ['↓ Improved', 'curbed']) : ['No change', 'same'];
    }
    return { label: REV_LABEL[r.stage] || nice(r.stage), at: r.sim_end ? hm(r.sim_end) : '', sev: r.severity, ch, cls, detail: pv ? revChanges(pv, r) : [] };
  });
  let verdict = '';
  if (rows.length > 1) {
    const a = rv[0], z = rv[rv.length - 1], sa = SEV_LABEL[a.severity] || nice(a.severity), sz = SEV_LABEL[z.severity] || nice(z.severity);
    const ra = SEV_RANK[a.severity] || 0, rz = SEV_RANK[z.severity] || 0, nre = rows.length - 1;
    verdict = rz > ra ? 'Got worse since the alert: ' + sa + ' → ' + sz : rz < ra ? (rz === 0 ? 'Resolved: the re-check found nothing wrong any more (was ' + sa + ')' : 'Improved since the alert: ' + sa + ' → ' + sz)
      : 'Checked again ' + (nre === 1 ? 'once' : nre === 2 ? 'twice' : nre + ' times') + ': still ' + sz;
  }
  return { rows, verdict };
}
function confButton(inc, c) {
  const cw = confWord(c), k = inc.id + ':conf', shown = S.eng || S.open.has(k);
  const num = h('span', { class: 'conf-n', text: ' · ' + pct(c), hidden: shown ? null : true });
  const b = h('button', { type: 'button', class: 'conf conf-' + cw.k, 'aria-expanded': shown ? 'true' : 'false',
    title: 'Tap to show the model\'s own score', onclick: () => {
      const o = b.getAttribute('aria-expanded') !== 'true'; o ? S.open.add(k) : S.open.delete(k);
      b.setAttribute('aria-expanded', o ? 'true' : 'false'); num.hidden = !o;
    } }, h('span', { class: 'confbar' }, h('i', { style: 'width:' + Math.round((c || 0) * 100) + '%' })), ' ' + cw.w, num);
  return b;
}
function findingOf(inc, s) { const v = sensorVerdict(inc, s); return { st: v.st, f: v.f || s.rule_finding || null }; }
// like title.go what(): a steady shape with an abnormal status is named by its status ("above normal")
function sensorPhrase(s, f, st) {
  const where = placeShort(s.location || s.node), p = f && f.pattern;
  const word = p && STEADY[p] && PATTERN_PLAIN[st] ? PATTERN_PLAIN[st] : p ? patternPlain(p) : 'checked';
  return metricName(s.metric) + ' at ' + where + ' ' + word;
}
function happening(inc, flagged, related) {
  const lead = [], obs = [], ok = [], bad = [];
  for (const s of flagged) {
    const { st, f } = findingOf(inc, s);
    if (st === 'pending') continue;
    lead.push(sensorPhrase(s, f, st) + (st && st !== 'normal' ? ' (' + (STATUS_LABEL[st] || nice(st)).toLowerCase() + ')' : ''));
    ((f && f.observations) || []).slice(0, 2).forEach((o) => obs.push(o));
  }
  for (const s of related) {
    const { st, f } = findingOf(inc, s);
    (st && st !== 'normal' && st !== 'insufficient_data' ? bad : ok).push(sensorPhrase(s, f, st) + (st && st !== 'normal' && st !== 'insufficient_data' ? ' (' + (STATUS_LABEL[st] || nice(st)).toLowerCase() + ')' : ''));
  }
  const allNormal = flagged.length && flagged.every((s) => findingOf(inc, s).st === 'normal');
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  let rel = '';
  if (bad.length) rel = 'Also abnormal nearby: ' + bad.join('; ') + '.';
  if (ok.length) rel += (rel ? ' ' : '') + 'Checked nearby and normal: ' + ok.join('; ') + '.' + (!bad.length && !allNormal ? ' So the cause looks local.' : '');
  return { lead: lead.length ? (allNormal ? 'Nothing abnormal confirmed: ' : '') + cap(lead.join('; ')) + '.' : '', obs: joinSentences(obs.slice(0, 3)), related: rel };
}
function opSummary(inc, main, flagged) {
  const out = [], r = main && main.r;
  const role = primaryRole(inc.roles);
  if (main && main.rejected) out.push(h('div', { class: 'banner op-warn', role: 'note' }, icon('alert'), h('span', { text: 'The AI report failed the safety check, so the automatic rule result is shown. See Technical details.' })));
  // what is happening: composed from each sensor's structured finding (pattern, status, place) so it reads
  // the same in every mode; the model's own wording stays under Technical details
  const hap = happening(inc, flagged, (inc.sensors || []).filter((x) => x.context));
  const what = hap.lead || (r ? stripRefs(r.root_cause) : '');
  out.push(h('section', { class: 'op-sec' }, h('h3', { text: 'What is happening' }),
    h('p', { class: 'op-lead', text: what || 'No summary was produced.' }),
    hap.obs ? h('p', { class: 'op-more', text: hap.obs }) : null,
    hap.related ? h('p', { class: 'op-more', text: hap.related }) : null));
  // why it matters: consequence from the report label, and the likely cause from the flagged sensors
  const causes = [];
  for (const sr of flagged) { const v = sensorVerdict(inc, sr), f = v.f || sr.rule_finding; if (f && f.likely_cause && !/^normal|sensor_fault$/.test(f.likely_cause) && !causes.includes(causePlain(f.likely_cause))) causes.push(causePlain(f.likely_cause)); }
  out.push(h('section', { class: 'op-sec' }, h('h3', { text: 'Why it matters' }),
    h('p', { text: (r && LABEL_IMPACT[r.label]) || DOMAIN_IMPACT[role] || 'A person should take a look.' }),
    causes.length ? h('p', { class: 'op-more', text: 'Likely cause: ' + causes.slice(0, 2).join('; ') + '.' }) : null));
  // what to do: the recommended action, then the domain playbook (de-duplicated)
  const steps = [];
  if (r && r.action && r.action !== 'none') steps.push(actionText(r.action));
  const dh = S.health && (S.health.domains || []).find((d) => d.domain === role);
  const sev = SEV_RANK[inc.severity] || 0;
  if (sev > 0) ((dh && dh.steps) || []).forEach((st) => { if (steps.length < 3 && !steps.includes(st.text)) steps.push(st.text); });
  if (inc.workflow && inc.state !== 'failed') out.push(checklist(inc)); // UX v34: per-step checklist (workflow.go)
  else out.push(h('section', { class: 'op-sec' }, h('h3', { text: 'What to do' }),
    steps.length && (sev > 0 || (r && r.action && r.action !== 'none')) ? h('ol', { class: 'op-steps' }, steps.map((t) => h('li', { text: t })))
      : h('p', { text: 'Nothing to do on site. Dismiss it with a short note if you agree.' })));
  // how sure (a word; the number one tap away)
  if (r && typeof r.confidence === 'number') {
    out.push(h('section', { class: 'op-sec op-row' }, h('h3', { text: 'How sure the AI is' }), confButton(inc, r.confidence),
      h('p', { class: 'op-note', text: main.src === 'rules' ? 'From the automatic rules (no AI).' : 'Based on ' + flagged.length + ' flagged sensor' + (flagged.length === 1 ? '' : 's') + ' and the related ones it checked. The evidence is under Technical details.' })));
  }
  // what changed at the 1.5 h / 3 h re-checks
  const st = revStory(inc), nx = refineLine(inc);
  if (st.rows.length > 1 || nx) {
    out.push(h('section', { class: 'op-sec' }, h('h3', { text: 'What changed since the alert' }),
      st.verdict ? h('p', { class: 'op-lead', text: st.verdict }) : null,
      st.rows.length ? h('ol', { class: 'op-rev' }, st.rows.map((x) => h('li', { class: 'rv-' + x.cls },
        h('span', { class: 'rv-l', text: x.label + (x.at ? ' · ' + x.at : '') }), sevTag({ state: 'done', severity: x.sev }), h('span', { class: 'rv-c', text: x.ch }),
        x.detail.length ? h('span', { class: 'rv-d', text: x.detail.join(' · ') }) : null))) : null,
      nx));
  }
  return out;
}
function renderIncDetail() {
  const inc = S.inc, box = $('#inc-detail'); if (!inc) return;
  const running = inc.state === 'running';
  // finished calls no longer need their stream buffer
  const drop = (ref) => { const k = streamKeyOf(inc.id, ref); delete S.stream[k]; delete ST.first[k]; };
  (inc.agents || []).forEach((a) => drop(a.ref));
  if (inc.final) drop('final');
  if (!running) delete ST.batch[inc.id];
  const parts = [];
  const doms = (inc.roles || []).map((r) => DH_NAME[r] || roleTitle[r] || nice(r));
  setText($('#isheet-t'), inc.id + (doms.length ? ' · ' + doms.join(', ') : ''));
  const sensors = inc.sensors || [];
  const flagged = sensors.filter((s) => !s.context), related = sensors.filter((s) => s.context);
  const main = running ? null : mainReport(inc);
  // 1. headline: severity + decision state + plain title (the rules' title and the timing stay under Technical details)
  parts.push(h('div', { class: 'op-head' },
    h('div', { class: 'rep-h', style: 'margin-bottom:8px' }, sevTag(inc),
      wfChip(inc),
      stageTag(inc), running ? h('span', { class: 'livepill', text: 'LIVE' }) : null, multiFlag(inc)),
    h('h1', { class: 'inc-title', text: plainTitle(inc.title), title: inc.title }),
    h('p', { class: 'op-meta', text: (doms.join(', ') || 'Campus') + ' · detected ' + (inc.created_sim ? dhm(inc.created_sim) : '-') + ' (sensor time)' }),
    wfOfI(inc) !== 'closed' && etaEl(inc) ? h('p', { class: 'op-meta' }, etaEl(inc)) : null));
  const bn = wfBanner(inc); if (bn) parts.push(bn);
  // 2. while the AI works: the progress steps (plain), its live text is under Technical details (open)
  if (running) parts.push(trackCard(inc));
  else if (inc.state === 'failed') parts.push(doneLine(inc));
  // 3. what is happening / why / what to do / how sure / what changed
  if (!running) parts.push(...opSummary(inc, main, flagged));
  // 4. sensors: titles only, tap for the chart and what the AI found for that sensor
  parts.push(h('section', { class: 'op-sec' }, h('h3', { text: 'Sensors involved (' + flagged.length + ')' }), h('div', { class: 'schips' }, flagged.map((s) => sensorChip(inc, s))),
    related.length ? [h('h4', { class: 'op-h4', text: 'Also checked nearby (' + related.length + ')' }), h('div', { class: 'schips' }, related.map((s) => sensorChip(inc, s)))] : null,
    h('p', { class: 'op-note', text: 'Tap a sensor for its chart and what the AI found.' })));
  if (!running) { const hs = historySec(inc); if (hs) parts.push(hs); const tl = evTimeline(inc); if (tl) parts.push(tl); }
  if (!running) { const rf = refiningCard(inc); if (rf) parts.push(rf); }
  // 5. Technical details: the full engineering record (open while the AI works, or in Engineering view)
  const tech = [];
  tech.push(h('dl', { class: 'kv tech-kv' },
    h('dt', { text: 'Incident' }), h('dd', { text: inc.id + ' · Mode ' + inc.mode + ' (' + ['Rules', 'Single model', 'Multi-agent'][inc.mode - 1] + ')' }),
    h('dt', { text: 'Title' }), h('dd', { text: inc.title }),
    inc.rule_title && inc.rule_title !== inc.title ? [h('dt', { text: 'Raised by the rules as' }), h('dd', { text: inc.rule_title })] : null,
    h('dt', { text: 'Sensor time' }), h('dd', { text: inc.created_sim ? dhm(inc.created_sim) + ' IST' : '-' }),
    h('dt', { text: 'Analysed (device time)' }), h('dd', { text: inc.created_wall || '-' }),
    h('dt', { text: 'Work' }), h('dd', { text: sensors.length + ' sensors · ' + inc.npu_calls + ' NPU call' + (inc.npu_calls === 1 ? '' : 's') + (running ? '' : ' · ' + (elapsedOf(inc) == null ? '-' : elapsedOf(inc).toFixed(1) + ' s')) }),
    main && main.r ? [h('dt', { text: 'Label / action' }), h('dd', { text: (main.r.label || '-') + ' / ' + (main.r.action || '-') })] : null));
  tech.push(h('div', { style: 'height:12px' }), reasonerCard(inc));
  // compare (rerun) sits with the decision it questions; approve/dismiss stay in the sheet footer
  const seg = makeSeg([{ v: 1, t: 'Rules' }, { v: 2, t: 'Single' }, { v: 3, t: 'Agents' }], async (m) => {
    try { S.pendingNewest = new Set(S.incs.map((i) => i.id)); const r = await post('/api/incidents/' + inc.id + '/rerun?mode=' + m); toast(r && r.queued_ahead ? 'Rerun queued: ' + r.queued_ahead + ' ahead on the NPU' : 'Re-running ' + inc.id + ' in mode ' + m); setTimeout(refreshIncidents, 400); setTimeout(refreshIncidents, 1500); }
    catch (e) { S.pendingNewest = null; toast('Rerun: ' + e.message, true); }
  }, 'Re-run in another mode');
  setSeg(seg, inc.mode); $$('button', seg).forEach((b) => b.setAttribute('aria-pressed', 'false'));
  tech.push(h('div', { class: 'card' }, h('h3', { style: 'font-size:17px;margin-bottom:4px', text: 'Compare modes' }), h('p', { class: 'muted', style: 'font-size:14px;margin-bottom:10px', text: 'Re-analyse the same frozen sensor windows in another mode. A new incident is created.' }), seg));
  // agents: NPU agents (streaming + metrics) and compact CPU context agents
  const ag = h('div', { class: 'agents' }), cg = h('div', { class: 'agents' });
  let nextShown = false;
  for (const s of sensors) {
    const a = (inc.agents || []).find((x) => x.ref === s.ref);
    if (a && isCtxAgent(a)) {
      const p = a.parsed || s.rule_finding;
      cg.append(h('div', { class: 'card agent ctxa ' + stClass(p ? p.status : 'none') },
        h('div', { class: 'rep-h' }, h('div', { class: 'dico', style: '--cb:' + (ROLE_COLOR[s.role] || ROLE_COLOR.multi) + ';width:34px;height:34px;border-radius:11px' }, icon(s.role, 18)),
          h('div', { style: 'min-width:0;flex:1' }, h('b', { text: a.ref + ' · ' + (roleTitle[a.role] || a.role) }), h('div', { class: 'muted', style: 'font-size:13px', text: s.node + ' ' + s.metric })),
          p ? pill(p.status) : null),
        h('div', { class: 'statrow' }, h('span', { class: 'chip stat', text: 'Context agent · CPU · instant' })),
        p ? h('div', { style: 'margin-top:8px;font-size:14.5px' }, h('span', { class: 'chip', html: patIcon(p.pattern) + esc(nice(p.pattern)) }), ' ' + nice(p.likely_cause)) : null,
        s.why ? h('div', { class: 'muted', style: 'font-size:13.5px;margin-top:6px', text: s.why }) : null));
      continue;
    }
    if (a) {
      const p = a.parsed;
      ag.append(h('div', { class: 'card agent ' + stClass(p ? p.status : 'none') },
        h('div', { class: 'rep-h' }, h('b', { text: a.ref + ' · ' + (roleTitle[a.role] || a.role) + ' agent' }), p ? pill(p.status) : null),
        h('div', { class: 'rep-h', style: 'margin:8px 0' }, modelBadge(a.model, a.fine_tuned)),
        h('div', { class: 'muted', style: 'font-size:14px', text: s.node + ' ' + s.metric + ' — ' + s.location }),
        statChips(a),
        p ? h('div', {}, h('div', { style: 'margin-top:10px' }, h('span', { class: 'chip', html: patIcon(p.pattern) + esc(nice(p.pattern)) })),
          h('dl', { class: 'kv', style: 'margin-top:10px' }, h('dt', { text: 'Likely cause' }), h('dd', { text: nice(p.likely_cause) }), h('dt', { text: 'Action' }), h('dd', { text: nice(p.action) }), h('dt', { text: 'Confidence' }), h('dd', { text: pct(p.confidence) })),
          h('ul', { class: 'obs' }, (p.observations || []).map((o) => h('li', {}, evChipsInText(o, s.evidence)))))
          : h('div', { class: 'muted', style: 'margin-top:8px', text: 'No parsed finding.' }),
        h('div', { style: 'margin-top:10px' }, gate(a.valid, a.errors)),
        details(inc.id + ':' + a.ref + ':raw', 'Raw model output', a.raw), details(inc.id + ':' + a.ref + ':prompt', 'Prompt', a.prompt)));
    } else if (running && inc.mode === 3 && !s.context) {
      const tx = S.stream[streamKeyOf(inc.id, s.ref)], b = ST.batch[inc.id], inBatch = b && b.refs.has(s.ref);
      // batched (htpd): every agent of the batch is on the NPU at once, so each gets its live box
      if (tx || inBatch || !nextShown) { nextShown = true; ag.append(liveCard(inc.id, s.ref, s.role, tx, s.node + ' ' + s.metric + ' — ' + s.location)); }
      else ag.append(h('div', { class: 'card agent st-none' }, h('div', { class: 'rep-h' }, h('b', { text: s.ref + ' · ' + (roleTitle[s.role] || s.role) + ' agent' }), h('span', { class: 'pill ghost', text: 'Queued' })), h('div', { class: 'muted', style: 'font-size:14px;margin-top:6px', text: 'Waiting for the NPU.' })));
    }
  }
  // open while running so the agents are seen thinking; collapsed once the reasoner has decided
  const nNpu = running ? ag.children.length : (inc.agents || []).filter((a) => !isCtxAgent(a)).length;
  if (ag.children.length) tech.push(fold(inc.id + ':agents', 'NPU agents (' + nNpu + ')', running, ag));
  if (cg.children.length) tech.push(fold(inc.id + ':ctx', 'Context agents (' + cg.children.length + ', CPU)', false, cg));
  const m1 = inc.mode1_report;
  const hist = historyFold(inc); if (hist) tech.push(hist);
  if (m1 && inc.mode !== 1) tech.push(fold(inc.id + ':m1', 'Mode 1 rules baseline', false,
    h('div', { class: 'card shadowc' }, h('p', { class: 'muted', style: 'margin-bottom:10px;font-size:14px', text: 'Deterministic rule engine, no AI. Always computed for comparison.' }), reportBody(inc, m1))));
  tech.push(fold(inc.id + ':log', 'Activity log', false, h('div', { class: 'card' }, h('ul', { class: 'tl', id: 'tl' }, (inc.timeline || []).map((t) => h('li', {}, h('time', { text: t.t }), h('span', { text: t.msg })))))));
  parts.push(h('div', { class: 'tech-wrap' }, fold(inc.id + ':tech', running ? 'Technical details · AI working live' : 'Technical details (modes, agents, evidence, log)', running || S.eng, tech)));
  const bd = $('#inc-detail'), sc = bd.scrollTop, ae = document.activeElement, fk = ae && ae.dataset && ae.dataset.k, sel = fk ? [ae.selectionStart, ae.selectionEnd] : null;
  box.replaceChildren(...parts);
  if (fk) { const n = box.querySelector('[data-k="' + fk.replace(/"/g, '') + '"]'); if (n) { n.focus(); try { n.setSelectionRange(sel[0], sel[1]); } catch (e) { /* not a text input */ } } }
  renderIncFoot(inc);
  const tl = $('#tl'); if (tl) tl.scrollTop = tl.scrollHeight;
  bd.scrollTop = sc;
  $$('#inc-detail .stream.live').forEach((p) => { p.scrollTop = p.scrollHeight; }); // rebuilt boxes resume at the newest text
  if (FS.ref) renderSensorSheet(false);
}
/* ============================== APPROVAL LIFECYCLE (UX v34) ==============================
   Backend: workflow.go. Spec: proofs/2026-10-23_reasoner_research/APPROVAL_AND_MEMORY.md §3.
   One field, workflow, kept apart from severity: Analysing -> Needs decision -> In progress ->
   Resolved -> Closed. "I'm on it" records who; each step is Done or Not needed; Close needs an
   outcome; Dismiss needs a note. Nothing is ever switched automatically. */
const OUTCOME_TEXT = { fixed_by_action: 'Fixed by action', sensor_replaced: 'Sensor replaced', sensor_repaired: 'Sensor repaired or recalibrated',
  resolved_on_its_own: 'Resolved on its own', false_alarm: 'False alarm', no_action_needed: 'No action needed' };
const OUTCOMES = ['fixed_by_action', 'sensor_replaced', 'sensor_repaired', 'resolved_on_its_own', 'false_alarm', 'no_action_needed'];
const NOTE_NEEDED = { false_alarm: 1, no_action_needed: 1 };
const EV_TEXT = { created: 'Alert raised', analysed: 'Report ready', interrupted: 'Analysis interrupted', ack: 'Acknowledged: on it',
  approve_all: 'Accepted every step', step_done: 'Done', step_not_needed: 'Not needed', step_reopened: 'Reopened', step_added: 'Step added',
  step_withdrawn: 'No longer suggested', recheck_elevated: 'Re-check: got worse', recheck_curbed: 'Re-check: improved', recheck_same: 'Re-check: no change',
  recheck_resolved: 'Re-check: back to normal', recheck_after_close: 'Re-check after closing', resolved: 'Back to normal', abnormal_again: 'Abnormal again',
  reminder: 'Reminder: still needs a decision', closed: 'Closed', dismissed: 'Dismissed', auto_closed: 'Closed automatically' };
const wfOfI = (i) => i.workflow || (i.state === 'running' ? 'analysing' : i.state === 'failed' ? 'interrupted' : i.approval === 'approved' ? 'in_progress' : i.approval === 'dismissed' ? 'closed' : 'needs_decision');
const clock = (u) => { if (!u) return ''; const d = new Date(u * 1000); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
const dclock = (u) => { if (!u) return ''; const d = new Date(u * 1000), t = new Date(); return (d.toDateString() === t.toDateString() ? '' : pad(d.getDate()) + ' ' + MON[d.getMonth()] + ' ') + clock(u); };
function wfChip(i) {
  const w = wfOfI(i), m = WF_WORD[w] || { g: '○', w: nice(w) };
  const extra = (w === 'in_progress' || w === 'resolved') && i.owner ? ' · ' + i.owner : w === 'closed' && i.outcome ? ' · ' + (OUTCOME_TEXT[i.outcome] || nice(i.outcome)) : '';
  return h('span', { class: 'dec wfchip wf-' + w }, h('i', { 'aria-hidden': 'true', text: m.g }), m.w + extra);
}

/* ----- who is using this shared device (name picker, no password; DECISIONS.md) ----- */
const OP = { list: [], cur: '', at: 0, then: null };
const OP_IDLE = 30 * 60 * 1000; // the chosen name is forgotten after 30 min without a decision
function opSave() {
  try { localStorage.setItem('sce-ops', JSON.stringify(OP.list)); localStorage.setItem('sce-op', JSON.stringify({ name: OP.cur, at: OP.at })); } catch (e) { /* private mode */ }
}
function opLoad() {
  try {
    const l = JSON.parse(localStorage.getItem('sce-ops') || '[]'); if (Array.isArray(l)) OP.list = l.filter((x) => typeof x === 'string' && x.trim()).slice(0, 30);
    const c = JSON.parse(localStorage.getItem('sce-op') || 'null'); if (c && c.name && Date.now() - c.at < OP_IDLE) { OP.cur = c.name; OP.at = c.at; }
  } catch (e) { /* private mode or bad data: start empty */ }
  renderOpBtn();
}
function opName() { if (OP.cur && Date.now() - OP.at > OP_IDLE) { OP.cur = ''; renderOpBtn(); } return OP.cur; }
function opTouch() { OP.at = Date.now(); opSave(); }
function renderOpBtn() {
  const b = $('#op'); if (!b) return;
  fill(b, icon('occupancy', 18), h('span', { class: 'op-n', text: OP.cur || 'Who?' }));
  setAttr(b, 'aria-label', OP.cur ? 'Operator: ' + OP.cur + '. Change' : 'Choose who is using this device');
}
function withOperator(fn) {
  const n = opName();
  if (n) { opTouch(); return Promise.resolve(fn(n)); }
  return new Promise((res) => openOpSheet((name) => res(fn(name))));
}
function openOpSheet(then) { OP.then = then || null; renderOpSheet(); openSheet('opsheet'); const x = $('#opsheet .op-pick'); if (x) x.focus(); else { const i = $('#op-new'); if (i) i.focus(); } }
function pickOp(name) {
  OP.cur = name; OP.at = Date.now(); opSave(); renderOpBtn(); closeSheet('opsheet');
  toast('Decisions are now recorded as ' + name);
  const f = OP.then; OP.then = null; if (f) f(name);
}
function renderOpSheet() {
  const inp = h('input', { id: 'op-new', class: 'note-in', type: 'text', maxlength: '40', placeholder: 'Your name', 'aria-label': 'Add a name', autocomplete: 'off' });
  const add = () => {
    const n = inp.value.replace(/\s+/g, ' ').trim(); if (!n) { inp.focus(); return; }
    if (!OP.list.includes(n)) OP.list.push(n);
    pickOp(n);
  };
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
  fill($('#opsheet-bd'),
    h('p', { class: 'op-note', text: 'Every decision is recorded with your name and the time. There is no password: this is a shared device.' }),
    OP.list.length ? h('div', { class: 'op-list', role: 'list' }, OP.list.map((n) => h('div', { class: 'op-item', role: 'listitem' },
      h('button', { type: 'button', class: 'btn op-pick' + (n === OP.cur ? ' primary' : ''), 'aria-pressed': n === OP.cur ? 'true' : 'false', onclick: () => pickOp(n) }, n),
      h('button', { type: 'button', class: 'btn op-del', 'aria-label': 'Remove ' + n + ' from this device', onclick: () => { OP.list = OP.list.filter((x) => x !== n); if (OP.cur === n) OP.cur = ''; opSave(); renderOpBtn(); renderOpSheet(); } }, icon('x', 18)))))
      : h('p', { class: 'muted', text: 'No names on this device yet.' }),
    h('h3', { class: 'op-h', text: 'Add a name' }),
    h('div', { class: 'ck-add' }, inp, h('button', { type: 'button', class: 'btn sm tint', onclick: add }, 'Add and use')));
}

/* ----- next re-check countdown: sensor time converted to the poll rate (2 s polls = 150x) ----- */
const NEXT_STAGE = { early: '1.5 h', '1.5h': '3 h' };
function etaText(next) {
  const now = Math.max(S.simNow || 0, (S.status && S.status.sim_time) || 0);
  if (!next || !now) return '';
  const rp = (S.status && S.status.replay) || {}, poll = rp.poll_ms || 2000, per = rp.speed_buckets_per_poll || 1;
  const rem = next - now; if (rem <= 0) return 'due now';
  const s = Math.ceil(rem / 300 / per) * poll / 1000;
  return s < 90 ? 'in ~' + Math.max(1, Math.round(s)) + ' s' : 'in ' + dhAgo(s);
}
function nextCheckText(i) {
  if (!i.next_refine_sim || !NEXT_STAGE[i.refine_stage]) return '';
  return 'Next check at ' + NEXT_STAGE[i.refine_stage] + ' · ' + etaText(i.next_refine_sim);
}
function etaEl(i) {
  const t = nextCheckText(i);
  return t ? h('span', { class: 'eta', 'data-next': String(i.next_refine_sim), 'data-stage': i.refine_stage, title: 'Re-check due at ' + hm(i.next_refine_sim) + ' sensor time', text: t }) : null;
}
function tickEtas() { $$('[data-next]').forEach((e) => setText(e, nextCheckText({ next_refine_sim: +e.dataset.next, refine_stage: e.dataset.stage }))); }

/* ----- actions ----- */
async function wfAct(inc, path, body, okMsg) {
  return withOperator(async (op) => {
    try {
      const r = await post('/api/incidents/' + inc.id + path, Object.assign({ operator: op }, body || {}));
      if (okMsg) toast(okMsg);
      await Promise.all([refreshIncidents(), refreshIncDetail(true)]);
      refreshHealthSoon();
      return r || true;
    } catch (e) { toast(e.message, true); return false; }
  });
}

/* ----- the checklist (replaces "What to do" once the backend has built it) ----- */
const STEP_GLYPH = { open: '☐', done: '☑', not_needed: '⊘', withdrawn: '–' };
const NN_REASONS = ['Already fine', 'Not possible now', 'Wrong suggestion'];
const SRC_WORD = { report: 'From the AI report', agent: 'From the domain agent', rules: 'From the automatic rules', playbook: 'Standard playbook', rule: 'Repair rule (fault came back within 30 days)' };
// preliminary report shown while the reasoner writes: the checklist is live (backend decidableEarly)
function prelimOpen(inc) { return !!(inc.state === 'running' && inc.final && inc.final.preliminary && inc.final.parsed); }
function checklist(inc) {
  const wf = wfOfI(inc), pre = prelimOpen(inc), live = (wf !== 'closed' && wf !== 'analysing' && wf !== 'interrupted') || (wf === 'analysing' && pre);
  const all = inc.steps || [];
  const steps = all.filter((s) => s.state !== 'withdrawn' || ((wf === 'in_progress' || wf === 'resolved') && s.by));
  const counted = steps.filter((s) => s.state !== 'withdrawn'), ticked = counted.filter((s) => s.state !== 'open').length;
  const own = all.filter((s) => s.source === 'operator').length;
  const items = steps.map((s) => {
    const k = inc.id + ':' + s.id, nn = S.ckNN === k;
    const by = s.state === 'done' || s.state === 'not_needed' ? (s.state === 'done' ? 'Done' : 'Not needed') + (s.by ? ' · ' + s.by : '') + (s.at ? ' · ' + dclock(s.at) : '') + (s.note ? ' · “' + s.note + '”' : '') : '';
    const tags = [s.new ? 'New since you acknowledged' : null, s.accepted && s.state === 'open' ? 'Accepted' : null, s.state === 'withdrawn' ? 'No longer suggested' : null,
      s.added_at_stage === 'preliminary' ? (pre ? 'Preliminary: may change when the AI report arrives' : 'From the preliminary report') : null].filter(Boolean);
    let act = null;
    if (live && s.state === 'open') {
      act = nn ? nnForm(inc, s, k) : h('div', { class: 'ck-act' },
        h('button', { type: 'button', class: 'btn sm tint', 'aria-label': 'Mark done: ' + s.text, onclick: () => wfAct(inc, '/steps/' + s.id, { state: 'done' }, 'Step marked done') }, icon('check'), 'Done'),
        h('button', { type: 'button', class: 'btn sm', 'aria-label': 'Mark not needed: ' + s.text, onclick: () => { S.ckNN = k; renderIncDetail(); } }, 'Not needed'));
    } else if (live && (s.state === 'done' || s.state === 'not_needed')) {
      act = h('div', { class: 'ck-act' }, h('button', { type: 'button', class: 'btn sm plain', 'aria-label': 'Undo: ' + s.text, onclick: () => wfAct(inc, '/steps/' + s.id, { state: 'open' }, 'Step reopened') }, 'Undo'));
    }
    return h('li', { class: 'ck ck-' + s.state },
      h('div', { class: 'ck-row' }, h('span', { class: 'ck-g', 'aria-hidden': 'true', text: STEP_GLYPH[s.state] || '☐' }),
        h('div', { class: 'ck-body' }, h('div', { class: 'ck-t', text: s.text }),
          tags.length ? h('div', { class: 'ck-tags' }, tags.map((t) => h('span', { class: 'ck-tag', text: t }))) : null,
          s.why ? h('div', { class: 'ck-why', text: 'Why: ' + s.why }) : null,
          h('div', { class: 'ck-src', text: (s.source === 'operator' ? 'Added by ' + (s.by || 'an operator') : (SRC_WORD[s.source] || nice(s.source))) + (s.added_at_stage && s.added_at_stage !== 'early' && s.added_at_stage !== 'preliminary' ? ' · at the ' + (DH_STAGE[s.added_at_stage] || s.added_at_stage) + ' re-check' : '') }),
          by ? h('div', { class: 'ck-by', text: by }) : null)),
      act);
  });
  return h('section', { class: 'op-sec ck-sec' }, h('h3', { text: 'What to do' + (counted.length ? ' · ' + ticked + ' of ' + counted.length + ' ticked' : '') }),
    steps.length ? h('ol', { class: 'cklist' }, items) : h('p', { text: 'No step suggested. If you agree nothing is needed, dismiss it with a short note.' }),
    live && own < 5 ? addStepForm(inc) : null,
    live ? h('p', { class: 'op-note', text: 'Mark each step Done or Not needed. Not right? Mark it Not needed and add your own. Nothing switches automatically.' }) : null);
}
function nnForm(inc, s, k) {
  const dk = 'nn:' + k;
  const inp = h('input', { class: 'note-in', type: 'text', maxlength: '300', placeholder: 'Why not needed? (optional)', 'aria-label': 'Why is this step not needed? (optional)', 'data-k': dk, oninput: (e) => { S.draft[dk] = e.target.value; } });
  inp.value = S.draft[dk] || '';
  const send = (note) => wfAct(inc, '/steps/' + s.id, { state: 'not_needed', note }, 'Step marked not needed').then((ok) => { if (ok) { S.ckNN = null; delete S.draft[dk]; renderIncDetail(); } });
  return h('div', { class: 'ck-nn' },
    h('div', { class: 'ck-reasons', role: 'group', 'aria-label': 'Quick reasons' }, NN_REASONS.map((t) => h('button', { type: 'button', class: 'fchip', text: t, onclick: () => send(t) }))),
    inp,
    h('div', { class: 'ck-act' }, h('button', { type: 'button', class: 'btn sm', text: 'Cancel', onclick: () => { S.ckNN = null; renderIncDetail(); } }),
      h('button', { type: 'button', class: 'btn sm primary', text: 'Not needed', onclick: () => send(inp.value.trim()) })));
}
function addStepForm(inc) {
  const k = 'add:' + inc.id;
  const inp = h('input', { class: 'note-in', type: 'text', maxlength: '200', placeholder: 'Add my own step', 'aria-label': 'Add my own step', 'data-k': k, oninput: (e) => { S.draft[k] = e.target.value; } });
  inp.value = S.draft[k] || '';
  const go = () => { const t = inp.value.trim(); if (!t) { inp.focus(); return; } wfAct(inc, '/steps', { text: t }, 'Step added').then((ok) => { if (ok) { delete S.draft[k]; renderIncDetail(); } }); };
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  return h('div', { class: 'ck-add' }, inp, h('button', { type: 'button', class: 'btn sm tint', onclick: go }, '+ Add step'));
}

/* ----- banners: got worse after an acknowledgement, back to normal (close?), reminder ----- */
function wfBanner(inc) {
  const wf = wfOfI(inc), ev = (inc.events || []).slice().reverse();
  const lastAck = ev.find((e) => e.event === 'ack'), lastWorse = ev.find((e) => e.event === 'recheck_elevated');
  if (wf === 'needs_decision' && inc.owner && lastWorse && lastAck && lastWorse.seq > lastAck.seq) {
    return h('div', { class: 'banner wfb crit', role: 'alert' }, h('span', { 'aria-hidden': 'true', text: '↑' }),
      h('span', { text: 'Got worse since ' + inc.owner + ' acknowledged it (' + (lastWorse.detail || 're-check') + '). Please look again and acknowledge.' }));
  }
  if (wf === 'resolved') {
    const since = inc.resolved_sim ? hm(inc.resolved_sim) + ' sensor time' : clock(inc.resolved_at);
    return h('div', { class: 'banner wfb ok', role: 'status' }, h('span', { 'aria-hidden': 'true', text: '✓' }),
      h('span', { text: 'Back to normal since ' + since + (inc.owner ? '' : ', not yet reviewed') + '. Close it' + (inc.suggest_outcome ? ' as “' + (OUTCOME_TEXT[inc.suggest_outcome] || nice(inc.suggest_outcome)) + '”' : '') + '?' }),
      h('button', { type: 'button', class: 'btn sm primary', onclick: () => openFootForm(inc, 'close') }, 'Close…'));
  }
  if (wf === 'needs_decision' && inc.reminded) {
    return h('div', { class: 'banner wfb warn', role: 'status' }, h('span', { 'aria-hidden': 'true', text: '!' }), h('span', { text: 'Critical and still waiting for someone to take it (over 15 min).' }));
  }
  return null;
}

/* ----- activity: the append-only event log as a small timeline ----- */
function evTimeline(inc) {
  const ev = (inc.events || []).slice().reverse(); if (!ev.length) return null;
  const k = inc.id + ':evall', all = S.open.has(k), shown = all ? ev : ev.slice(0, 6);
  const stepTxt = (id) => { const s = (inc.steps || []).find((x) => x.id === id); return s ? s.text : id; };
  const what = (e) => (EV_TEXT[e.event] || nice(e.event)) + (e.step_id ? ': ' + stepTxt(e.step_id) : '') +
    (e.outcome && (e.event === 'closed' || e.event === 'dismissed' || e.event === 'auto_closed') ? ' · ' + (OUTCOME_TEXT[e.outcome] || nice(e.outcome)) : '') +
    (e.note && e.note !== 'auto' ? ' · “' + e.note + '”' : '') + (e.detail && !e.step_id && /^(recheck|resolved|reminder|analysed|created)/.test(e.event) ? ' · ' + e.detail : '');
  return h('section', { class: 'op-sec' }, h('h3', { text: 'Activity (' + ev.length + ')' }),
    h('ol', { class: 'evtl' }, shown.map((e) => h('li', { class: 'ev-' + e.event },
      h('time', { text: dclock(e.at) }), h('b', { class: 'ev-who', text: e.actor === 'system' ? 'App' : e.actor === 'reasoner' ? 'AI' : e.actor }), h('span', { class: 'ev-what', text: what(e) })))),
    ev.length > 6 ? h('button', { type: 'button', class: 'btn sm plain', 'aria-expanded': all ? 'true' : 'false', onclick: () => { all ? S.open.delete(k) : S.open.add(k); renderIncDetail(); } }, all ? 'Show less' : 'Show all ' + ev.length) : null,
    h('p', { class: 'op-note', text: 'Times are the device clock. Every decision is kept, nothing is overwritten.' }));
}

/* ----- memory: History of this sensor (earlier incidents, steps, outcomes, maintenance) ----- */
const MAINT_TEXT = { out_of_service: 'Marked out of service', back_in_service: 'Back in service', replaced: 'Sensor replaced' };
async function loadHistory(id) {
  try { const d = await api('/api/incidents/' + encodeURIComponent(id) + '/history'); S.hist[id] = d; if (S.incId === id && S.inc) renderIncDetail(); } catch (e) { S.hist[id] = { error: e.message }; }
}
function historySec(inc) {
  if (inc.state === 'running') return null;
  const d = S.hist[inc.id];
  if (!d) { if (!S.histReq[inc.id]) { S.histReq[inc.id] = 1; loadHistory(inc.id); } return h('section', { class: 'op-sec' }, h('h3', { text: 'History of this sensor' }), h('p', { class: 'op-note', text: 'Loading …' })); }
  if (d.error) return h('section', { class: 'op-sec' }, h('h3', { text: 'History of this sensor' }), h('p', { class: 'op-note', text: 'Could not load: ' + d.error }));
  const secs = (d.sensors || []).map((sh) => {
    const items = (sh.incidents || []).map((x) => h('li', { class: 'hs-i' },
      h('button', { type: 'button', class: 'hs-open', onclick: () => selectIncident(x.id), 'aria-label': 'Open ' + x.id + ': ' + plainTitle(x.title) },
        h('b', { text: x.id }), ' · ' + (x.created_wall || '').slice(5, 16) + ' · ' + (SEV_LABEL[x.severity] || nice(x.severity))),
      h('div', { class: 'hs-o', text: (WF_WORD[x.workflow] || { w: nice(x.workflow) }).w + (x.outcome ? ': ' + (OUTCOME_TEXT[x.outcome] || nice(x.outcome)) : '') +
        (x.closed_by ? ' · ' + (x.closed_by === 'system' ? 'automatically' : 'by ' + x.closed_by) : x.owner ? ' · ' + x.owner : '') + (x.outcome_note && x.outcome_note !== 'auto' ? ' · “' + x.outcome_note + '”' : '') + (x.legacy_decision ? ' (before checklists)' : '') }),
      (x.steps || []).length ? h('ul', { class: 'hs-steps' }, x.steps.map((s) => h('li', { text: (STEP_GLYPH[s.state] || '') + ' ' + s.text + (s.by ? ' (' + s.by + ')' : '') + (s.note ? ': “' + s.note + '”' : '') }))) : null,
      x.recurred_by ? h('div', { class: 'hs-rec', text: '↻ Came back within 7 days (' + x.recurred_by + '): that fix did not hold' }) : null));
    const mts = (sh.maintenance || []).map((m) => h('li', { class: 'hs-m', text: '⊘ ' + (MAINT_TEXT[m.kind] || nice(m.kind)) + (m.minutes ? ' for ' + dhAgo(m.minutes * 60) : '') + (m.reason ? ' · ' + m.reason : '') + (m.operator ? ' · ' + m.operator : '') + ' · ' + dclock(m.at) }));
    return h('div', { class: 'hs' }, h('h4', { class: 'op-h4', text: metricName(sh.metric) + ' · ' + placeShort(sh.location || sh.node) }),
      items.length || mts.length ? h('ul', { class: 'hs-list' }, items, mts) : h('p', { class: 'op-note', text: 'No earlier incidents or maintenance on this sensor.' }));
  });
  return h('section', { class: 'op-sec' }, h('h3', { text: 'History of this sensor' }), secs.length ? secs : h('p', { class: 'op-note', text: 'No sensor to look up.' }));
}

/* ----- footer: I'm on it / Dismiss / Close with an outcome ----- */
function openFootForm(inc, kind) { S.footForm = { id: inc.id, kind, outcome: kind === 'dismiss' ? 'no_action_needed' : (inc.suggest_outcome || '') }; renderIncFoot(inc, true); const n = $('#inc-foot .note-in'); if (n && kind === 'dismiss') n.focus(); }
function footForm(inc) {
  const ff = S.footForm, dismiss = ff.kind === 'dismiss', opts = dismiss ? ['false_alarm', 'no_action_needed'] : OUTCOMES;
  const dk = 'foot:' + inc.id;
  const ta = h('input', { class: 'note-in', type: 'text', maxlength: '500', 'data-k': dk, placeholder: NOTE_NEEDED[ff.outcome] ? 'Note (needed)' : 'Note (optional)',
    'aria-label': 'Note' + (NOTE_NEEDED[ff.outcome] ? ' (needed)' : ' (optional)'), oninput: (e) => { S.draft[dk] = e.target.value; ta.classList.remove('need'); } });
  ta.value = S.draft[dk] || '';
  const go = async () => {
    const note = ta.value.trim();
    if (!ff.outcome) { toast('Choose how it ended', true); return; }
    if (NOTE_NEEDED[ff.outcome] && !note) { ta.classList.add('need'); ta.focus(); toast('Add a short note for ' + OUTCOME_TEXT[ff.outcome].toLowerCase(), true); return; }
    const ok = await wfAct(inc, dismiss ? '/dismiss' : '/close', { outcome: ff.outcome, note }, dismiss ? 'Dismissed: ' + OUTCOME_TEXT[ff.outcome] : 'Closed: ' + OUTCOME_TEXT[ff.outcome]);
    if (ok) { S.footForm = null; delete S.draft[dk]; renderIncFoot(S.inc || inc, true); }
  };
  return h('div', { class: 'ffm' },
    h('p', { class: 'foot-hint', id: 'ffm-q', text: dismiss ? 'Dismiss: why is nothing needed?' : 'Close: how did it end?' + (inc.suggest_outcome ? ' (pre-filled from what happened)' : '') }),
    h('div', { class: 'ffm-opts', role: 'radiogroup', 'aria-labelledby': 'ffm-q' }, opts.map((o) => h('button', { type: 'button', role: 'radio', 'aria-checked': ff.outcome === o ? 'true' : 'false',
      class: 'fchip' + (ff.outcome === o ? ' on' : ''), onclick: () => { ff.outcome = o; renderIncFoot(inc, true); } }, OUTCOME_TEXT[o]))),
    ta,
    h('div', { class: 'foot-row', style: 'margin-top:10px' }, h('button', { type: 'button', class: 'btn', onclick: () => { S.footForm = null; renderIncFoot(inc, true); } }, 'Cancel'),
      h('button', { type: 'button', class: 'btn ' + (dismiss ? 'danger' : 'primary'), onclick: go }, dismiss ? 'Dismiss' : 'Close incident')));
}

/* ----- incident list: filters, search, grouping ----- */
const INC_STATE = [['all', 'All'], ['needs_decision', 'Needs decision'], ['in_progress', 'In progress'], ['resolved', 'Resolved'], ['closed', 'Closed'], ['running', 'Analysing']];
function incDateOk(i) {
  const d = S.incDate; if (!d || d === 'any') return true;
  const t = (i.created_unix || 0) * 1000 || wallMs(i) || 0, now = Date.now();
  if (d === 'today') { const m = new Date(); m.setHours(0, 0, 0, 0); return t >= m.getTime(); }
  return t >= now - (d === '24h' ? 864e5 : 7 * 864e5);
}
function incText(i) { return [i.id, i.title, plainTitle(i.title || ''), i.owner, (i.roles || []).map((r) => DH_NAME[r] || r).join(' '), (i.sensors || []).join(' '), OUTCOME_TEXT[i.outcome] || ''].join(' ').toLowerCase(); }
function bindIncTools() {
  const q = $('#inc-q'), dom = $('#inc-dom'), dt = $('#inc-date');
  if (!q || q.dataset.b) return; q.dataset.b = '1';
  dom.append(...ROLE_ORDER.map((r) => h('option', { value: r, text: DH_NAME[r] || r })));
  q.addEventListener('input', () => { S.incQ = q.value.trim().toLowerCase(); renderIncList(); });
  dom.addEventListener('change', () => { S.incDom = dom.value; renderIncList(); });
  dt.addEventListener('change', () => { S.incDate = dt.value; renderIncList(); });
}

/* ----- shift summary: what happened since this device last looked (per device, localStorage) ----- */
const SHIFT = { last: 0, done: false };
function shiftInit() {
  try { SHIFT.last = +localStorage.getItem('sce-last-visit') || 0; } catch (e) { SHIFT.last = 0; }
  const mark = () => { try { localStorage.setItem('sce-last-visit', String(Date.now())); } catch (e) { /* private mode */ } };
  setInterval(() => { if (!document.hidden && SHIFT.done) mark(); }, 60000);
  document.addEventListener('visibilitychange', () => { if (document.hidden && SHIFT.done) mark(); });
  SHIFT.mark = mark;
}
function shiftSummary() {
  if (SHIFT.done || !S.lastIncList) return;
  SHIFT.done = true;
  const last = SHIFT.last; SHIFT.mark();
  if (!last) return; // first visit on this device: nothing to compare with
  const s = last / 1000, incs = S.incs || [];
  const nw = incs.filter((i) => (i.created_unix || 0) > s).length;
  const worse = incs.filter((i) => (i.worse_at || 0) > s).length;
  const res = incs.filter((i) => (i.resolved_at || 0) > s || ((i.closed_at || 0) > s && (i.outcome === 'resolved_on_its_own' || i.outcome === 'fixed_by_action' || i.outcome === 'sensor_repaired' || i.outcome === 'sensor_replaced'))).length;
  const box = $('#shift'); if (!box) return;
  const d = new Date(last), since = (Date.now() - last > 864e5 ? pad(d.getDate()) + ' ' + MON[d.getMonth()] + ' ' : '') + pad(d.getHours()) + ':' + pad(d.getMinutes());
  const parts = [nw + ' new', worse + ' got worse', res + ' resolved'];
  fill(box, h('span', { class: 'sh-t' }, h('b', { text: 'Since ' + since + ': ' }), parts.join(' · ')),
    nw || worse ? h('a', { class: 'sh-go', href: '#incidents', text: 'See incidents ›' }) : null,
    h('button', { type: 'button', class: 'ibtn sh-x', 'aria-label': 'Dismiss the summary since your last visit', onclick: () => { box.hidden = true; } }, icon('x', 18)));
  box.hidden = false;
}

/* ----- maintenance on the sensor sheet (POST /api/maintenance; the backend never alarms an
   out-of-service sensor) ----- */
async function maintPost(d, body, msg) {
  return withOperator(async (op) => {
    try {
      await post('/api/maintenance', Object.assign({ node: d.node, metric: d.metric, operator: op }, body));
      toast(msg); d.mform = null; await refreshLive(); refreshHealthSoon(); await loadDrawer(true);
    } catch (e) { toast('Maintenance: ' + e.message, true); }
  });
}
function maintSec(d, live) {
  const out = live.quality === 'maintenance';
  const until = live.maint_until ? hm(live.maint_until) : '';
  let body;
  if (d.mform === 'oos') {
    const t = h('input', { class: 'note-in', type: 'time', 'aria-label': 'Out of service until (sensor time, optional)', 'data-k': 'm-until' });
    const why = h('input', { class: 'note-in', type: 'text', maxlength: '200', placeholder: 'Reason (optional)', 'aria-label': 'Reason (optional)', 'data-k': 'm-why' });
    const go = () => {
      let min = 24 * 60;
      if (t.value) {
        const [hh, mm] = t.value.split(':').map(Number), now = Math.max(S.simNow || 0, (S.status && S.status.sim_time) || 0) || Date.now() / 1000;
        const p = istParts(now), cur = p.getUTCHours() * 60 + p.getUTCMinutes();
        min = ((hh * 60 + mm) - cur + 1440) % 1440 || 1440;
      }
      maintPost(d, { minutes: min, reason: why.value.trim(), replaced: false }, 'Out of service for ' + dhAgo(min * 60) + ': no alarms from this sensor');
    };
    body = h('div', { class: 'mform' }, h('label', { class: 'mlbl' }, 'Until (sensor time, empty = 24 h)', t), why,
      h('div', { class: 'foot-row' }, h('button', { type: 'button', class: 'btn', onclick: () => { d.mform = null; renderDrawer(); } }, 'Cancel'),
        h('button', { type: 'button', class: 'btn primary', onclick: go }, 'Mark out of service')));
  } else if (d.mform === 'repl') {
    body = h('div', { class: 'mform' }, h('p', { class: 'op-note', text: 'Replaced: the old sensor\'s readings are dropped so the new one is never compared with them. The AI waits for a full 4 h window of new readings.' }),
      h('div', { class: 'foot-row' }, h('button', { type: 'button', class: 'btn', onclick: () => { d.mform = null; renderDrawer(); } }, 'Cancel'),
        h('button', { type: 'button', class: 'btn primary', onclick: () => maintPost(d, { minutes: 0, replaced: true, reason: 'sensor replaced' }, 'Sensor replaced: collecting new readings') }, 'Sensor replaced')));
  } else {
    body = h('div', { class: 'foot-row mbtns' },
      out ? h('button', { type: 'button', class: 'btn tint', onclick: () => maintPost(d, { minutes: 0, replaced: false }, 'Back in service') }, 'Back in service')
        : h('button', { type: 'button', class: 'btn', onclick: () => { d.mform = 'oos'; renderDrawer(); } }, 'Mark out of service'),
      h('button', { type: 'button', class: 'btn', onclick: () => { d.mform = 'repl'; renderDrawer(); } }, 'Sensor replaced'));
  }
  return h('div', { class: 'card msec' }, h('h3', { style: 'margin-bottom:8px;font-size:17px', text: 'Maintenance' }),
    out ? h('p', { class: 'oos', text: '⊘ Out of service' + (until ? ' until ' + until + ' (sensor time)' : '') + (live.quality_reason ? ' · ' + live.quality_reason.replace(/^out of service:?\s*/, '') : '') + '. Its readings are shown but never raise an alarm.' }) : null,
    body);
}
/* ----- end approval lifecycle ----- */

/* ============================== SENSORS (the user is the sensor) ============================== */
const SN = { data: null, rows: new Map(), live: new Map(), buf: new Map(), touch: new Set(), local: new Map(), timers: new Map(), built: false,
  noise: 1, pollMs: 2000, lastFetch: 0, fetchT: 0, noiseTouch: false };
const decOf = (st) => { const s = String(st); return s.includes('.') ? s.split('.')[1].length : 0; };
const snFmt = (s, v) => (s.metric === 'occ' ? (v >= 0.5 ? 'Occupied' : 'Vacant') : Number(v).toFixed(decOf(s.step)));
const snKey = (s) => key(s.node, s.metric);
function snSend(s, v) {
  return post('/api/sensors', { node: s.node, metric: s.metric, value: v }).catch((e) => { toast('Set ' + s.label + ': ' + e.message, true); });
}
function snReflect(resp, force) {
  if (!resp || !Array.isArray(resp.sensors)) return;
  SN.lastFetch = Date.now();
  SN.data = resp;
  if (!SN.built) snBuild();
  if (typeof resp.noise_scale === 'number' && !SN.noiseTouch) snSetNoise(resp.noise_scale);
  for (const s of resp.sensors) {
    const k = snKey(s), r = SN.rows.get(k); if (!r) continue;
    r.s = s;
    const busy = SN.touch.has(k) || Date.now() - (SN.local.get(k) || 0) < 2500;
    if (force || !busy) snSetRowValue(r, s.value);
    r.badge.hidden = s.source !== 'api';
  }
}
function snSetRowValue(r, v) {
  const s = r.s;
  if (s.metric === 'occ') {
    const on = v >= 0.5; r.sw.setAttribute('aria-checked', on ? 'true' : 'false');
    r.val.replaceChildren(snFmt(s, v));
  } else {
    if (+r.inp.value !== v) r.inp.value = v;
    snFill(r);
    r.val.replaceChildren(snFmt(s, v), h('small', { text: s.unit || '' }));
  }
}
function snFill(r) { const s = r.s, p = ((+r.inp.value - s.min) / (s.max - s.min)) * 100; r.inp.style.setProperty('--p', Math.max(0, Math.min(100, p)) + '%'); }
function snFetch() { return api('/api/sensors').then((d) => snReflect(d)).catch(() => {}); }
function snLater() { clearTimeout(SN.fetchT); SN.fetchT = setTimeout(snFetch, 250); }
function snSetNoise(v) {
  SN.noise = v; if (!SN.noiseInp) return;
  if (+SN.noiseInp.value !== v) SN.noiseInp.value = v;
  SN.noiseInp.style.setProperty('--p', (v / 3) * 100 + '%');
  setText(SN.noiseVal, v === 0 ? 'Exact' : v.toFixed(1) + '×');
}
function snMakeRow(s) {
  const k = snKey(s), r = { s };
  r.val = h('div', { class: 'sn-val' });
  r.badge = h('span', { class: 'pill orange sn-badge', text: 'set by device', hidden: true });
  r.live = h('b', { class: 'sn-last', text: '-' });
  r.stc = h('span', { class: 'pill stp' }); r.pat = h('span', { class: 'chip' });
  r.spark = h('svg', { class: 'sn-spark', viewBox: '0 0 80 24', preserveAspectRatio: 'none', 'aria-hidden': 'true' });
  let ctl;
  if (s.metric === 'occ') {
    r.sw = h('button', { type: 'button', class: 'sn-sw', role: 'switch', 'aria-checked': 'false', 'aria-label': s.label + ': occupied' }, h('i'));
    r.sw.onclick = () => {
      const on = r.sw.getAttribute('aria-checked') !== 'true'; SN.local.set(k, Date.now());
      snSetRowValue(r, on ? 1 : 0); snSend(s, on ? 1 : 0).then(snLater);
    };
    ctl = h('div', { class: 'sn-ctl' }, r.sw, h('span', { class: 'muted', text: 'Tap to toggle occupied / vacant' }));
  } else {
    r.inp = h('input', { type: 'range', class: 'sn-range', min: s.min, max: s.max, step: s.step, value: s.value, 'aria-label': s.label });
    const send = () => { clearTimeout(SN.timers.get(k)); SN.timers.delete(k); SN.local.set(k, Date.now()); return snSend(s, +r.inp.value); };
    r.inp.addEventListener('input', () => {
      SN.touch.add(k); SN.local.set(k, Date.now()); snFill(r);
      r.val.replaceChildren(snFmt(s, +r.inp.value), h('small', { text: s.unit || '' }));
      clearTimeout(SN.timers.get(k)); SN.timers.set(k, setTimeout(send, 150));
    });
    r.inp.addEventListener('change', () => { send().then(snLater); });
    const down = () => SN.touch.add(k), up = () => setTimeout(() => SN.touch.delete(k), 600);
    r.inp.addEventListener('pointerdown', down); r.inp.addEventListener('touchstart', down, { passive: true });
    r.inp.addEventListener('pointerup', up); r.inp.addEventListener('pointercancel', up); r.inp.addEventListener('touchend', up); r.inp.addEventListener('blur', up);
    ctl = h('div', { class: 'sn-ctl' }, h('span', { class: 'sn-lim', text: s.min }), r.inp, h('span', { class: 'sn-lim', text: s.max }));
  }
  r.ai = h('span', { class: 'chip aichip', hidden: true });
  r.root = h('div', { class: 'sn-row', 'data-k': k },
    h('div', { class: 'sn-top' }, h('div', { class: 'sn-nm' }, h('b', { text: s.label }), h('span', { class: 'loc', text: s.location }), r.badge), r.val),
    ctl,
    h('div', { class: 'sn-live' }, h('span', { class: 'muted', text: 'Live' }), r.live, r.stc, r.ai, r.pat, r.spark));
  snSetRowValue(r, s.value);
  return r;
}
function snBuild() {
  SN.built = true;
  const d = SN.data, box = $('#sens');
  const noiseInp = h('input', { type: 'range', class: 'sn-range', min: 0, max: 3, step: 0.1, value: 1, 'aria-label': 'Sensor jitter' });
  SN.noiseInp = noiseInp; SN.noiseVal = h('b', { class: 'sn-val', text: '1.0×' });
  const sendNoise = () => post('/api/sensors', { noise_scale: +noiseInp.value }).catch((e) => toast(e.message, true));
  let nt = 0;
  noiseInp.addEventListener('input', () => { SN.noiseTouch = true; snSetNoise(+noiseInp.value); clearTimeout(nt); nt = setTimeout(sendNoise, 150); });
  noiseInp.addEventListener('change', () => { clearTimeout(nt); sendNoise(); setTimeout(() => { SN.noiseTouch = false; }, 1500); });
  SN.pollSeg = makeSeg([[500, '0.5 s'], [1000, '1 s'], [2000, '2 s'], [5000, '5 s']].map(([v, t]) => ({ v, t })), async (v) => {
    try { const r = await post('/api/replay', { poll_ms: v }); SN.pollMs = r.poll_ms || v; setSeg(SN.pollSeg, SN.pollMs); } catch (e) { toast('Poll: ' + e.message, true); }
  }, 'Poll interval');
  setSeg(SN.pollSeg, SN.pollMs);
  const reset = h('button', { class: 'btn', type: 'button', onclick: async () => {
    try { const r = await post('/api/sensors', { reset_values: true }); snReflect(r, true); toast('All sensors back to normal values'); } catch (e) { toast('Reset: ' + e.message, true); }
  } }, icon('restart'), 'Reset to normal values');
  const restart = h('button', { class: 'btn', type: 'button', onclick: async () => {
    try { await post('/api/replay', { restart: true }); toast('Clock restarted: 4 h window refilled at current values'); await Promise.all([refreshStatus(), refreshLive()]); } catch (e) { toast('Restart: ' + e.message, true); }
  } }, icon('play'), 'Restart clock');
  const ids = d.sensors.map((s) => s.node + '  ' + s.metric + '  (' + s.label + ', ' + s.location + ')').join('\n');
  const host = /^(localhost|127\.|\[)/.test(location.hostname) ? '<qidk-ip>' : location.hostname;
  const curl = 'curl -X POST http://' + host + ":8000/api/ingest -H 'Content-Type: application/json' -d '{\"node\":\"SR-AQ-KH03-03\",\"metric\":\"co2\",\"value\":850}'";
  const ctl = h('div', { class: 'card sn-top-card' },
    h('div', { class: 'sn-banner' }, icon('info'), h('p', { text: 'You are the sensor: every poll the app reads these values as the next 5-minute reading. Only warning, critical or stuck readings call the AI, after they last 8 readings; everything alarming at the same time becomes one incident.' })),
    h('div', { class: 'sn-set' }, h('div', { class: 'sn-top' }, h('div', { class: 'sn-nm' }, h('b', { text: 'Sensor jitter' }), h('span', { class: 'loc', text: '0 = exact values. A perfectly constant value eventually looks like a stuck sensor, which the app flags.' })), SN.noiseVal),
      h('div', { class: 'sn-ctl' }, h('span', { class: 'sn-lim', text: '0' }), noiseInp, h('span', { class: 'sn-lim', text: '3' }))),
    h('div', { class: 'sn-set' }, h('div', { class: 'sn-nm' }, h('b', { text: 'Poll interval' }), h('span', { class: 'loc', text: 'How often a new reading is taken' })), SN.pollSeg),
    h('div', { class: 'sn-set' }, h('div', { class: 'sn-nm' }, h('b', { text: 'Sensor time of day' }),
      h('span', { class: 'loc', text: 'Each reading is 5 sensor-minutes, so the clock runs fast. Occupancy at 22:00-06:00 counts as off-hours. Changing it keeps all readings.' })),
      makeSeg([['09:00', 'Morning'], ['14:00', 'Afternoon'], ['19:00', 'Evening'], ['23:00', 'Night']].map(([v, t]) => ({ v, t })), async (v) => {
        try { const r = await post('/api/replay', { clock: v }); toast('Sensor time set to ' + (r.sensor_time_ist || v)); await refreshStatus(); } catch (e) { toast('Clock: ' + e.message, true); }
      }, 'Sensor time of day')),
    h('div', { class: 'sn-btns' }, reset, restart));
  const conn = h('details', { class: 'card sn-conn' }, h('summary', { text: 'Connect a real sensor' }),
    h('p', { class: 'muted', text: 'A real device (ESP32, curl) can set any of these values with the same call the sliders use:' }),
    h('pre', { class: 'sn-pre', text: curl }), h('p', { class: 'muted', text: 'Sensor ids (node, metric):' }), h('pre', { class: 'sn-pre', text: ids }));
  const groups = h('div', { class: 'sn-grid' });
  for (const role of ROLE_ORDER) {
    const list = d.sensors.filter((s) => s.role === role); if (!list.length) continue;
    const card = h('div', { class: 'card sn-card', style: '--cb:' + ROLE_COLOR[role] },
      h('div', { class: 'sn-h' }, h('span', { class: 'sn-ic' }, icon(role)), h('h3', { text: roleTitle[role] }), h('span', { class: 'muted', text: list.length + ' sensors' })));
    for (const s of list) { const r = snMakeRow(s); SN.rows.set(snKey(s), r); card.append(r.root); }
    groups.append(card);
  }
  box.replaceChildren(ctl, groups, conn);
  snLiveAll();
}
function snSparkSvg(vals) {
  if (vals.length < 2) return '';
  let mn = Math.min(...vals), mx = Math.max(...vals); if (mx - mn < 1e-9) { mn -= 1; mx += 1; }
  const pts = vals.map((v, i) => (i / (vals.length - 1) * 78 + 1).toFixed(1) + ',' + (22 - ((v - mn) / (mx - mn)) * 20).toFixed(1)).join(' ');
  return '<polyline points="' + pts + '" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>';
}
function snLiveRow(k) {
  const r = SN.rows.get(k); if (!r) return;
  const u = SN.live.get(k) || S.sensorMap.get(k); if (!u) return;
  const s = r.s;
  setText(r.live, s.metric === 'occ' ? (u.last ? 'Occupied' : 'Vacant') : fmt(u.last) + (s.unit ? ' ' + s.unit : ''));
  const st = u.status || 'none';
  setText(r.stc, (STATUS_GLYPH[st] || '○') + ' ' + (STATUS_LABEL[st] || st)); setCls(r.stc, 'pill stp ' + stClass(st));
  const pat = u.pattern && u.pattern !== '-' ? u.pattern : null;
  r.pat.style.display = pat ? '' : 'none';
  if (pat && r.pat.dataset.p !== pat) { r.pat.dataset.p = pat; r.pat.innerHTML = patIcon(pat) + esc(nice(pat)); }
  setCls(r.root, 'sn-row ' + stClass(st));
  const af = +u.abnormal_for || 0, pr = +u.persist_readings || 8;
  let ai = '';
  if (af > 0 && u.reported) ai = 'Reported to AI';
  else if (af > 0) ai = pr - af > 0 ? 'AI check in ' + (pr - af) + ' reading' + (pr - af === 1 ? '' : 's') : 'AI checking…';
  r.ai.hidden = !ai; setText(r.ai, ai);
  const html = snSparkSvg(SN.buf.get(k) || []);
  if (r.spark.dataset.h !== html) { r.spark.dataset.h = html; r.spark.innerHTML = html; }
}
function snLiveAll() { SN.rows.forEach((_, k) => snLiveRow(k)); }
function snOnLive(d) {
  if (!d || !Array.isArray(d.sensors)) return;
  for (const u of d.sensors) {
    const k = key(u.node, u.metric); SN.live.set(k, u);
    if (typeof u.last === 'number') { let b = SN.buf.get(k); if (!b) SN.buf.set(k, b = []); b.push(u.last); if (b.length > 40) b.shift(); }
  }
  if (SN.built && S.view === 'sensors') snLiveAll();
}

/* ============================== MAP ============================== */
const cellMap = new Map();
function renderMap() {
  const box = $('#map'), t = S.topo;
  if (!t) { box.replaceChildren(h('div', { class: 'empty', text: 'Loading topology ...' })); return; }
  if (box.dataset.built) return; box.dataset.built = '1';
  const cov = Object.values(t.coverage || {}); const mean = cov.length ? cov.reduce((a, b) => a + b, 0) / cov.length : null;
  const lg = h('div', { class: 'legend-row' }, ['normal', 'warning', 'critical', 'sensor_fault', 'insufficient_data'].map((s) => pill(s)));
  const grid = h('div', { class: 'bgrid' });
  Object.keys(t.buildings).sort().forEach((b) => {
    const levels = t.buildings[b]; let n = 0;
    const card = h('div', { class: 'card bld' });
    Object.keys(levels).sort().forEach((lv) => {
      const cells = h('div', { class: 'dots' });
      levels[lv].forEach((nd) => (nd.metrics || []).forEach((m) => {
        n++;
        const c = h('button', { class: 'dotb', type: 'button', onclick: () => openSensor(nd.node, m) }, '○');
        const cv = (t.coverage || {})[key(nd.node, m)];
        c.dataset.k = key(nd.node, m);
        c.dataset.tip = nd.node + ' ' + m + ' | ' + nd.location + (cv != null ? ' | coverage ' + Math.round(cv * 100) + '%' : '');
        cellMap.set(key(nd.node, m), c); cells.append(c);
      }));
      card.append(h('div', { class: 'lvl' }, h('b', { text: 'L' + lv }), cells));
    });
    card.prepend(h('div', { class: 'bld-h' }, h('div', { class: 'tile', text: b }), h('div', {}, h('b', { text: 'Building ' + b }), h('span', { text: n + ' sensor stream' + (n === 1 ? '' : 's') }))));
    grid.append(card);
  });
  box.replaceChildren(
    h('div', { class: 'card' }, h('h3', { style: 'font-size:18px', text: 'Campus sensors, driven by you' }),
      h('p', { class: 'muted', style: 'margin-top:6px', text: 'Every dot is a sensor whose value you set on the Sensors tab (or a real device posts).' }),
      mean != null ? h('p', { style: 'margin-top:8px' }, 'Mean data coverage ', h('b', { text: (mean * 100).toFixed(1) + '%' }), ' across ' + cov.length + ' sensor streams.') : null,
      h('p', { class: 'muted', style: 'margin-top:8px;font-size:14px', text: 'Schematic, not a geographic map. Tap a dot to open that sensor.' }), lg),
    grid);
  renderMapColors();
}
function renderMapColors() {
  cellMap.forEach((c, k) => {
    const s = S.sensorMap.get(k), st = s ? s.status : 'none';
    setCls(c, 'dotb ' + stClass(st) + (isGrey(st) ? ' grey' : ''));
    setText(c, STATUS_GLYPH[st] || '○');
    const lbl = (c.dataset.tip || '') + ' | ' + (STATUS_LABEL[st] || st) + (s && s.pattern && s.pattern !== '-' ? ' | ' + nice(s.pattern) : '');
    setAttr(c, 'title', lbl); setAttr(c, 'aria-label', lbl);
  });
}

/* ============================== ABOUT ============================== */
function buildAbout() {
  const gi = (n, t, s) => `<div class="gi"><div class="gn">${n}</div><div class="gk"><b>${t}</b><span>${s}</span></div></div>`;
  $('#about').innerHTML =
    `<div class="card eng-card"><div class="sn-top"><div class="sn-nm"><b>Engineering view</b><span class="loc">Shows reasoning modes, AI models, NPU status, evidence ids, prompts and the full pipeline on every screen. Off: plain language for operators. Also in the header (&lt;/&gt; button).</span></div><button type="button" id="eng-sw" class="sn-sw" role="switch" aria-checked="false" aria-label="Engineering view"><i></i></button></div></div>
    <div class="card"><h3 style="font-size:19px;margin-bottom:6px">Everything runs on this device</h3><p class="muted">You set the sensor values on the Sensors tab (or a real device posts them) and a Qualcomm QIDK board analyses them. Statistics, rules, language-model calls and policy checks are all computed locally on the Hexagon NPU. <b style="color:var(--tx)">No cloud, no laptop, no internet connection is used for inference.</b></p></div>
    <div class="sec-h">The pipeline</div>
    <div class="glist">${[['Poll sensors', 'Every poll, each current sensor value becomes its next 5-minute reading.'], ['Stats and rules', 'SMA, EMA, trend, Bollinger bands and a rule-based pattern per sensor.'], ['Event gate', 'Only warning, critical or stuck sensors wake the AI, so the NPU stays free and cool.'], ['Domain agents on the NPU', 'One small agent per flagged sensor reads its evidence (E1..E8) and writes a finding.'], ['Synthesizer', 'Combines the agent findings into one cross-domain report.'], ['Safety check', 'The policy gate rejects bad JSON, unknown labels and made-up evidence ids.'], ['Human approval', 'Nothing is actuated automatically. You approve or dismiss every recommendation.']].map((x, i) => gi(i + 1, x[0], x[1])).join('')}</div>
    <div class="sec-h">How alerts work</div>
    <div class="card"><p class="muted">A sensor calls the AI only when its status is warning, critical or stuck (sensor fault) and stays that way for 8 readings in a row. Every sensor that is alarming at that moment, plus any that join within 3 more readings, goes into one incident with one batch of NPU agent calls. A sensor reports once per episode and re-arms after it returns to normal.</p></div>
    <div class="sec-h">The three modes</div>
    <div class="glist">${gi('1', 'Rules', 'Deterministic statistics and rules. No AI. Always computed as the shadow baseline.')}${gi('2', 'Single', 'One AI call reads all flagged sensors and writes the report.')}${gi('3', 'Multi-Agent', 'One agent call per sensor (fine-tuned model when deployed), then a synthesizer.')}</div>
    <div class="sec-h">Model in use</div>
    <div class="glist" id="about-model"><div class="gi"><div class="gk"><span>Loading ...</span></div></div></div>
    <div class="sec-h">Speed on the Hexagon NPU</div>
    <div class="glist">${gi('⚡', 'Model init 0.7 s · prompt 1,160 tok/s · generation ~19 tok/s', 'Measured on this board with the Genie runtime.')}${gi('1', 'One NPU job at a time', 'Parallel NPU jobs are unsafe on this device, so agents run one after another.')}</div>
    <div class="sec-h">Status key</div>
    <div class="card"><div class="legend-row" style="margin-top:0">${['normal', 'warning', 'critical', 'sensor_fault', 'insufficient_data'].map((s) => `<span class="pill ${stClass(s)}">${STATUS_GLYPH[s]} ${STATUS_LABEL[s]}</span>`).join('')}</div>
    <p class="muted" style="margin-top:10px;font-size:14px">Status always comes with a symbol and a word, never colour alone. Greyed rows mean the sensor is still warming up, which is not an error.</p></div>`;
}
function renderAboutModel() {
  const e = $('#about-model'); if (!e || !S.status) return;
  const m = S.status.models || {};
  const row = (lbl, x) => x ? `<div class="gi"><div class="gk"><b>${lbl}</b><span>${esc(x.name || '-')} · ${x.fine_tuned ? 'fine-tuned' : 'base'} · ${x.available ? 'available' : 'not available'}${x.note ? ' · ' + esc(x.note) : ''}</span></div></div>` : '';
  const html = row('Agents use', m.agent) + row('Synthesizer', m.reasoner) + row('Base fallback', m.base) + row('Fine-tuned bundle', m.tuned) + `<div class="gi"><div class="gk"><b>Running on</b><span>${esc(S.status.running_on || '-')}</span></div></div>`;
  if (e.dataset.h !== html) { e.dataset.h = html; e.innerHTML = html; }
}

/* ============================== navigation ============================== */
function setView(v) {
  const deep = /^incident\/(INC-\d+)$/.exec(v || '');
  if (deep) { setView('incidents'); selectIncident(deep[1]); try { history.replaceState(null, '', '#incidents'); } catch (e) { /* ignore */ } return; }
  if (!['sensors', 'live', 'incidents', 'map', 'about'].includes(v)) v = 'sensors';
  S.view = v;
  $$('.view').forEach((x) => x.classList.toggle('on', x.id === 'view-' + v));
  $$('#rail a').forEach((a) => { const on = a.dataset.view === v; a.classList.toggle('on', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  window.scrollTo(0, 0);
  if (v === 'incidents') refreshIncidents();
  if (v === 'sensors') { snFetch().then(() => snLiveAll()); refreshStatus(); if (!S.live) refreshLive(); }
  if (v === 'map') { (S.topo ? Promise.resolve() : api('/api/topology').then((t) => { S.topo = t; }).catch(() => {})).then(() => { renderMap(); refreshLive(); }); }
  if (v === 'live') refreshLive();
}

/* ============================== SSE ============================== */
function onLive(d) {
  snOnLive(d);
  if (!S.live || !d || !Array.isArray(d.sensors)) return;
  let changed = false;
  for (const u of d.sensors) {
    const s = S.sensorMap.get(key(u.node, u.metric)); if (!s) continue;
    if (u.status !== s.status || u.pattern !== s.pattern) changed = true;
    if (u.quality !== s.quality) changed = true;
    for (const k of ['last', 'sma_1h', 'ema_1h', 'slope_per_h', 'pattern', 'status', 'injected', 'data_ok', 'updated', 'quality', 'quality_reason', 'maint_until']) if (k in u) s[k] = u[k];
  }
  for (const r in S.live.roles) { let w = 'normal'; for (const s of S.live.roles[r].sensors) if (sevRank(s.status) > sevRank(w)) w = s.status; S.live.roles[r].status = w; }
  S.lastLive = S.lastLiveEv = Date.now();
  renderLive(); renderMapColors(); updateHero();
  if (changed && !onLive.t) onLive.t = setTimeout(() => { onLive.t = 0; refreshLive(); }, 6000); // refresh likely_cause text
}
let es = null;
function connect() {
  if (es) es.close();
  es = new EventSource('/api/events');
  es.onopen = () => { S.sse = true; if (S.incId) resyncStreams(S.incId); }; // catch up on tokens sent while disconnected
  es.onerror = () => { S.sse = false; if (es.readyState === 2) setTimeout(connect, 3000); };
  const J = (e) => { try { return JSON.parse(e.data); } catch (x) { return {}; } };
  es.addEventListener('tick', (e) => {
    const d = J(e);
    if (d.sim_time_ist) { setText($('#c-time'), d.sim_time_ist.replace(/^\w+ \d+ \w+( \d+)? /, '') + ' IST'); setText($('#l-sub'), 'Sensor time ' + d.sim_time_ist + ' IST'); }
    if (d.npu && S.status) { S.status.npu = d.npu; updateHero(); }
    if (d.sim_time) { S.simNow = d.sim_time; renderHealth(); } // time-in-state on the domain tiles
    const now = Date.now();
    if (now - S.lastLiveEv >= 15000 && now - S.lastLive >= 15000 && S.view !== 'about') refreshLive();
    if (now - S.lastStatus >= 4000) refreshStatus();
    if (S.drawer && !S.drawer.mform && now - S.lastDrawer >= 5000) loadDrawer();
  });
  es.addEventListener('incident', (e) => {
    const d = J(e);
    if (d.id && d.refined) clearRefine(d.id); // the refined analysis is in; its live panel goes
    const listed = refreshIncidents();
    if (d.change || d.workflow_change === 'resolved') listed.then(() => onIncChange(d)); // re-check moved it, reminder, back to normal
    refreshHealthSoon();
    if (d.id && d.id === S.incId) refreshIncDetail(false);
    if (d.workflow_change === 'auto_closed' && d.id) delete S.hist[d.id];
    // Open a newly running incident so the agents are seen thinking, which is the whole point of
    // streaming tokens. Only when nothing else is open, so this can never steal the view from
    // someone reading another incident or working on the sensors tab.
    if (d.id && d.state === 'running' && !S.autoOpened[d.id] && !$('.sheet.open')) {
      S.autoOpened[d.id] = 1;
      selectIncident(d.id);
    }
    refreshStatus();
  });
  es.addEventListener('token', (e) => onToken(J(e)));
  es.addEventListener('rtoken', (e) => onToken(J(e), true));
  es.addEventListener('batch', (e) => onBatch(J(e)));
  es.addEventListener('live', (e) => onLive(J(e)));
  es.addEventListener('health', (e) => { const d = J(e); if (d && Array.isArray(d.domains)) { S.health = d; S.lastHealth = Date.now(); renderHealth(); updateHero(); } });
  es.addEventListener('ingest', () => { snLater(); });
  es.addEventListener('mode', (e) => { const d = J(e); if (S.status && d.mode) { S.status.mode = d.mode; renderMode(); } });
}

/* ============================== boot ============================== */
function boot() {
  tabIcons(); buildAbout(); bindHeader(); bindTheme(); bindEng(); buildHero();
  opLoad(); shiftInit(); bindIncTools();
  $('#op').onclick = () => openOpSheet(null);
  window.addEventListener('hashchange', () => setView(location.hash.slice(1)));
  $('#scrim').onclick = () => { closeSheet('opsheet'); closeSheet('sheet'); closeSheet('isheet'); closeSheet('dsheet'); };
  $$('[data-close]').forEach((b) => b.onclick = () => closeSheet(b.dataset.close));
  $('#fs-x').onclick = () => closeSensorSheet();
  $('#fs .fs-back').onclick = () => closeSensorSheet();
  $('#fs').addEventListener('keydown', trapFocus);
  $('#fs-bd').addEventListener('scroll', () => hidePop(true), { passive: true });
  window.addEventListener('popstate', () => { if (!$('#fs').hidden) closeSensorSheet(true); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { if ($('#opsheet').classList.contains('open')) closeSheet('opsheet'); else if (!$('#fs').hidden) closeSensorSheet(); else if ($('#isheet').classList.contains('open')) closeSheet('isheet'); else if ($('#sheet').classList.contains('open')) closeSheet('sheet'); else if ($('#dsheet').classList.contains('open')) closeSheet('dsheet'); else hidePop(true); } });
  document.addEventListener('click', (e) => { if (!e.target.closest || !e.target.closest('.chip.ev')) hidePop(true); });
  $('#sheet-bd').addEventListener('scroll', () => hidePop(true), { passive: true });
  $('#inc-detail').addEventListener('scroll', () => hidePop(true), { passive: true });
  setView(location.hash.slice(1) || 'sensors');
  refreshStatus(); refreshLive(); refreshIncidents(); refreshHealth();
  connect();
  setInterval(sparkLoop, 1000); // each tick measures every tile (layout); 1 Hz is plenty for 10 s refreshes
  setInterval(() => { if (!document.hidden && Date.now() - SN.lastFetch > 4500) snFetch(); }, 1000);
  post('/api/replay', {}).then((r) => { if (r && r.poll_ms) { SN.pollMs = r.poll_ms; if (SN.pollSeg) setSeg(SN.pollSeg, r.poll_ms); } }).catch(() => {});
  setInterval(updateElapsed, 500);
  setInterval(tickEtas, 2000); // "Next check at 1.5 h · in 23 min"
  setInterval(() => { if (OP.cur && !opName()) toast('Name cleared after 30 min idle: choose who you are before the next decision'); }, 60000);
  setInterval(() => {
    if (!S.sse || Date.now() - S.lastLiveEv > 15000) { refreshStatus(); refreshLive(); }
    // Backend unreachable (restart, crash, reboot): say so instead of silently showing stale data.
    const seen = Math.max(S.lastStatus || 0, S.lastLiveEv || 0), off = seen > 0 && Date.now() - seen > 12000;
    let ob = document.getElementById('offline');
    if (off && !ob) { ob = h('div', { id: 'offline', role: 'status', text: 'Reconnecting to the on-device backend ... values shown may be stale' }); document.body.appendChild(ob); }
    else if (!off && ob) ob.remove();
    if (Date.now() - S.lastIncList > 15000) refreshIncidents();
    renderHealthConn();
    if (!S.sse || Date.now() - S.lastHealth > 60000) refreshHealth();
    if (S.inc && S.inc.state === 'running') refreshIncDetail(false);
  }, 3000);
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
}
boot();
})();

/* ---------- dot-matrix headings (UI Reference: "DEERFLOW", "THINKING...") ----
   A 5x7 LED font rendered as SVG dots. This is the single most identifying mark
   of the reference dashboard and cannot be had from a system font, so the glyphs
   live here as data - no webfont, no external asset, works offline. */
const DOT5x7 = {
  A: '01110,10001,10001,11111,10001,10001,10001', B: '11110,10001,10001,11110,10001,10001,11110',
  C: '01110,10001,10000,10000,10000,10001,01110', D: '11110,10001,10001,10001,10001,10001,11110',
  E: '11111,10000,10000,11110,10000,10000,11111', F: '11111,10000,10000,11110,10000,10000,10000',
  G: '01110,10001,10000,10111,10001,10001,01111', H: '10001,10001,10001,11111,10001,10001,10001',
  I: '11111,00100,00100,00100,00100,00100,11111', J: '00111,00010,00010,00010,00010,10010,01100',
  K: '10001,10010,10100,11000,10100,10010,10001', L: '10000,10000,10000,10000,10000,10000,11111',
  M: '10001,11011,10101,10101,10001,10001,10001', N: '10001,11001,10101,10011,10001,10001,10001',
  O: '01110,10001,10001,10001,10001,10001,01110', P: '11110,10001,10001,11110,10000,10000,10000',
  Q: '01110,10001,10001,10001,10101,10010,01101', R: '11110,10001,10001,11110,10100,10010,10001',
  S: '01111,10000,10000,01110,00001,00001,11110', T: '11111,00100,00100,00100,00100,00100,00100',
  U: '10001,10001,10001,10001,10001,10001,01110', V: '10001,10001,10001,10001,10001,01010,00100',
  W: '10001,10001,10001,10101,10101,11011,10001', X: '10001,10001,01010,00100,01010,10001,10001',
  Y: '10001,10001,01010,00100,00100,00100,00100', Z: '11111,00001,00010,00100,01000,10000,11111',
  0: '01110,10001,10011,10101,11001,10001,01110', 1: '00100,01100,00100,00100,00100,00100,01110',
  2: '01110,10001,00001,00010,00100,01000,11111', 3: '11111,00010,00100,00010,00001,10001,01110',
  4: '00010,00110,01010,10010,11111,00010,00010', 5: '11111,10000,11110,00001,00001,10001,01110',
  6: '00110,01000,10000,11110,10001,10001,01110', 7: '11111,00001,00010,00100,01000,01000,01000',
  8: '01110,10001,10001,01110,10001,10001,01110', 9: '01110,10001,10001,01111,00001,00010,01100',
  '.': '00000,00000,00000,00000,00000,01100,01100', '-': '00000,00000,00000,11111,00000,00000,00000',
  ':': '00000,01100,01100,00000,01100,01100,00000', '/': '00001,00010,00010,00100,01000,01000,10000',
};

/* Render text as an SVG grid of dots. step = pixels per dot cell. */
function dotTextSvg(text, step, cls) {
  const s = String(text).toUpperCase();
  const GW = 5, GH = 7, GAP = 1;                      // glyph is 5x7 cells, 1 cell between glyphs
  const cols = s.length * (GW + GAP) - GAP;
  const w = Math.max(1, cols * step), h = GH * step;
  const r = (step * 0.36).toFixed(2);
  let dots = '';
  let cx = 0;
  for (const ch of s) {
    const g = DOT5x7[ch];
    if (g) {
      const rows = g.split(',');
      for (let y = 0; y < GH; y++) {
        for (let x = 0; x < GW; x++) {
          if (rows[y][x] === '1') {
            dots += `<circle cx="${((cx + x) * step + step / 2).toFixed(2)}" cy="${(y * step + step / 2).toFixed(2)}" r="${r}"/>`;
          }
        }
      }
    }
    cx += GW + GAP;
  }
  return `<svg class="dotttl ${cls || ''}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${s}">${dots}</svg>`;
}

/* Swap each page heading for its dot-matrix rendering. Keeps the original text as
   the accessible label and leaves light mode untouched. */
function applyDotTitles() {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  // page headings only: never the incident title, which also lives in an .ltitle and is long
  document.querySelectorAll('.ltitle h1:not(.inc-title)').forEach((el) => {
    if (!el.dataset.txt) el.dataset.txt = el.textContent.trim();
    if (!dark) { el.textContent = el.dataset.txt; el.classList.remove('is-dots'); return; }
    const step = Math.max(3, Math.min(5, Math.floor((el.clientWidth || 320) / (el.dataset.txt.length * 6))));
    el.innerHTML = dotTextSvg(el.dataset.txt, step);
    el.classList.add('is-dots');
  });
}
addEventListener('DOMContentLoaded', applyDotTitles);
addEventListener('hashchange', () => setTimeout(applyDotTitles, 0));
