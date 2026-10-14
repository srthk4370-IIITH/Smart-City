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
  $('#toasts').append(t);
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
  filter: 'all', incFilter: 'all', stream: {}, cardStream: {}, autoOpened: {}, trkPct: {}, modeTimer: 0,
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
    const l = await api('/api/incidents');
    S.incs = (Array.isArray(l) ? l : []).sort((a, b) => b.id.localeCompare(a.id));
    S.lastIncList = Date.now();
    renderIncList();
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
  setText($('#n-inc'), st.incidents ? st.incidents : '');
  renderAboutModel();
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
    h('div', { class: 'hero-sys' }, H.npu, H.model, H.therm, H.run, H.mem)));
}
function updateHero() {
  if (!H.ico) return;
  let crit = 0, warn = 0, fault = 0, tot = 0, worst = 'normal';
  if (S.live) for (const r in S.live.roles) {
    if (r === 'hvac') continue;
    for (const s of S.live.roles[r].sensors) {
      tot++;
      if (s.status === 'critical') crit++; else if (s.status === 'warning') warn++; else if (s.status === 'sensor_fault') fault++;
    }
  }
  if (crit) worst = 'critical'; else if (warn) worst = 'warning'; else if (fault) worst = 'sensor_fault';
  const title = !S.live ? 'Checking campus ...' : crit ? 'Action needed' : warn ? 'A few things to watch' : fault ? 'Some sensors need a check' : 'All clear';
  const sub = !S.live ? '' : crit ? crit + ' critical reading' + (crit === 1 ? '' : 's') + ' right now' : warn ? warn + ' reading' + (warn === 1 ? '' : 's') + ' above normal' : fault ? fault + ' sensor' + (fault === 1 ? '' : 's') + ' look faulty or flat' : 'Everything is within normal range';
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
  t.pat = h('span', { class: 'chip' }); t.cause = h('span', { class: 'cause' });
  t.root = h('button', { class: 'row', type: 'button' },
    h('div', { class: 'nm' }, t.met, t.loc), t.stc, t.val, t.spark,
    h('div', { class: 'meta' }, t.sma, t.trend), h('div', { class: 'chipsr' }, t.pat, t.cause));
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
  setCls(t.root, 'row ' + stClass(s.status) + (isGrey(s.status) ? ' grey' : ''));
  setText(t.met, s.metric); setText(t.loc, s.location); setAttr(t.loc, 'title', s.node + ' - ' + s.location);
  const sc = STATUS_GLYPH[s.status] + ' ' + (STATUS_LABEL[s.status] || s.status);
  setText(t.stc, sc); setCls(t.stc, 'pill stp ' + stClass(s.status));
  if (occ) setText(t.val, s.last ? 'Occupied' : 'Vacant');
  else if (!t.valInit || t.lastVal !== s.last) t.val.replaceChildren(fmt(s.last), h('small', { text: s.unit || '' }));
  t.valInit = true; t.lastVal = s.last;
  if (occ) { setText(t.sma, 'state ' + (s.last ? '1' : '0') + ' · ' + (s.points_24h || 0) + ' readings today'); setText(t.trend, ''); }
  else {
    setText(t.sma, s.sma_1h == null ? 'SMA - · EMA -' : 'SMA ' + fmt(s.sma_1h) + ' · EMA ' + fmt(s.ema_1h));
    const tr = trendOf(s);
    setText(t.trend, tr ? tr.arrow + ' ' + tr.txt : ''); setCls(t.trend, 'trend ' + (tr ? tr.cls : ''));
  }
  const pat = s.pattern && s.pattern !== '-' ? s.pattern : null;
  t.pat.style.display = pat ? '' : 'none';
  if (pat && t.pat.dataset.p !== pat) { t.pat.dataset.p = pat; t.pat.innerHTML = patIcon(pat) + esc(nice(pat)); }
  setText(t.cause, isGrey(s.status) ? (s.status === 'insufficient_data' ? 'Warming up: waiting for enough history' : 'No data yet') : nice(s.likely_cause));
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
  if (id === 'isheet') { S.incId = null; S.inc = null; S.incText = ''; }
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
function renderBigChart(box, s, hours, occ) {
  const pts = s.points || [];
  if (pts.length < 2) { box.replaceChildren(h('div', { class: 'empty', text: 'Not enough data in the last ' + hours + ' h to draw a chart yet.' })); return; }
  const W = Math.max(320, Math.min(860, box.clientWidth - 12 || 860)), H2 = W < 600 ? 290 : 360, L = W < 600 ? 50 : 62, R = 12, T = 14, B = 32;
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
    occ ? null : h('span', {}, sw('--blue'), 'SMA 1 h'),
    occ ? null : h('span', {}, sw('--accent', 'border-top-style:dashed'), 'EMA 1 h'),
    occ ? null : h('span', {}, h('i', { class: 'band' }), 'Bollinger band'),
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
  setText($('#sheet-t'), metric + ' · ' + node);
  $('#sheet-bd').replaceChildren(h('div', { class: 'empty' }, h('span', { class: 'spin' }), ' Loading ' + metric + ' ...'));
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
  row('Node', d.node + ' (' + nice(s.role) + ')');
  row('Where', live.location || '-');
  if (!occ) { row('SMA / EMA 1 h', fmt(live.sma_1h) + ' / ' + fmt(live.ema_1h) + ' ' + (s.unit || '')); const tr = trendOf(live); row('Trend', tr ? tr.arrow + ' ' + tr.txt : '-'); }
  row('Pattern', (live.pattern && live.pattern !== '-') ? nice(live.pattern) : '-');
  row('Likely cause', nice(live.likely_cause));
  if (s.limits) row('Limits', 'warn ' + s.limits.warn + ' · crit ' + s.limits.crit + ' (' + s.limits.dir + ')');
  const canAnalyze = !!win && s.role !== 'hvac';
  const btn = h('button', { class: 'btn primary', type: 'button', style: 'width:100%', disabled: canAnalyze ? null : true,
    onclick: async () => {
      btn.disabled = true;
      try { S.pendingNewest = new Set(S.incs.map((i) => i.id)); await post('/api/analyze', { node: d.node, metric: d.metric }); toast('AI agents are on it (mode ' + (S.status ? S.status.mode : '?') + ')'); setTimeout(refreshIncidents, 500); setTimeout(refreshIncidents, 1500); }
      catch (e) { S.pendingNewest = null; toast('Analyse: ' + e.message, true); btn.disabled = false; }
    } }, icon('multi'), 'Analyse with AI agents');
  const body = [
    h('div', { class: 'rep-h', style: 'margin-bottom:10px' }, live.status ? pill(live.status) : null),
    h('div', { class: 'sheet-big' }, occ ? (live.last ? 'Occupied' : 'Vacant') : fmt(live.last) + ' ' + (s.unit || '')),
    h('p', { class: 'muted', style: 'margin:2px 0 14px', text: live.location || d.node }),
    chart,
    h('div', { class: 'card', style: 'margin-top:14px' }, kv),
    h('div', { class: 'card' },
      h('h3', { style: 'margin-bottom:8px;font-size:17px', text: 'Rule engine says (Mode 1, no AI)' }),
      rf ? h('div', {},
        h('div', { class: 'rep-h', style: 'margin-bottom:8px' }, pill(rf.status), h('span', { class: 'chip', html: patIcon(rf.pattern) + esc(nice(rf.pattern)) })),
        h('dl', { class: 'kv' },
          h('dt', { text: 'Likely cause' }), h('dd', { text: nice(rf.likely_cause) }),
          h('dt', { text: 'Confidence' }), h('dd', { text: pct(rf.confidence) }),
          h('dt', { text: 'Action' }), h('dd', { text: nice(rf.action) })),
        h('ul', { class: 'obs' }, (rf.observations || []).map((o) => h('li', {}, evChipsInText(o, win.evidence)))))
        : h('div', { class: 'muted', text: s.role === 'hvac' ? 'HVAC nodes are context only: no agent window.' : 'Not enough history yet for this sensor.' })),
    win ? h('div', { class: 'card' }, h('h3', { style: 'margin-bottom:6px;font-size:17px', text: 'Evidence E1..E8' }),
      h('p', { class: 'muted', style: 'font-size:13.5px;margin-bottom:6px', text: 'Computed statistics. These are the only facts the AI may cite.' }),
      h('ul', { class: 'evlist' }, (win.evidence || []).map((e) => h('li', {}, h('b', { text: e.ID }), h('span', { text: e.Text }))))) : null,
    win ? h('details', { ontoggle: (e) => { d.promptOpen = e.target.open; }, open: d.promptOpen ? true : null },
      h('summary', { text: 'Prompt sent to the on-device LLM' }), h('pre', { text: win.prompt || '' })) : null,
  ];
  bd.replaceChildren(...body.filter(Boolean));
  $('#sheet-ft').replaceChildren(h('p', { class: 'foot-hint', text: canAnalyze ? 'Uses the current mode. The result appears under Incidents.' : 'No AI analysis available for this sensor.' }), btn);
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
    [['all', 'All'], ['pending', 'Needs your decision'], ['running', 'Live now'], ['done', 'Decided']].forEach(([k, t]) => {
      box.append(h('button', { type: 'button', class: 'fchip' + (k === S.incFilter ? ' on' : ''), 'data-k': k, onclick: () => {
        S.incFilter = k; $$('#inc-chips .fchip').forEach((x) => x.classList.toggle('on', x.dataset.k === k)); applyIncFilter();
      } }, h('span', { text: t }), h('span', { class: 'n' })));
    });
  }
  const cnt = { all: S.incs.length, pending: S.incs.filter((i) => i.approval === 'pending' && i.state !== 'running').length, running: S.incs.filter((i) => i.state === 'running').length, done: S.incs.filter((i) => i.approval !== 'pending').length };
  $$('#inc-chips .fchip').forEach((x) => setText($('.n', x), cnt[x.dataset.k]));
}
function incMatches(i) {
  return S.incFilter === 'all' || (S.incFilter === 'pending' && i.approval === 'pending' && i.state !== 'running') ||
    (S.incFilter === 'running' && i.state === 'running') || (S.incFilter === 'done' && i.approval !== 'pending');
}
function applyIncFilter() { S.incs.forEach((i) => { const e = incEls.get(i.id); if (e) e.root.hidden = !incMatches(i); }); }
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
  setText($('#n-inc'), S.incs.length ? S.incs.length : '');
  renderIncChips();
  if (!S.incs.length) { box.replaceChildren(h('div', { class: 'empty', style: 'grid-column:1/-1', text: 'All quiet. Incidents appear when the event gate flags a sensor. Change a value on the Sensors tab to trigger one.' })); incEls.clear(); return; }
  const em = $('.empty', box); if (em) em.remove();
  S.incs.forEach((i, idx) => {
    let e = incEls.get(i.id);
    if (!e) { e = { root: h('button', { class: 'icard', type: 'button', onclick: () => selectIncident(i.id) }) }; incEls.set(i.id, e); }
    const sig = JSON.stringify(i);
    if (e.sig !== sig) {
      e.sig = sig;
      const rr = primaryRole(i.roles);
      setCls(e.root, 'icard ' + stClass(i.severity));
      const running = i.state === 'running';
      fill(e.root,
        h('div', { class: 'top' },
          h('div', { class: 'dico', style: '--cb:' + (ROLE_COLOR[(i.roles || []).length > 1 ? 'multi' : rr] || ROLE_COLOR.multi) }, icon((i.roles || []).length > 1 ? 'multi' : rr)),
          h('div', { style: 'min-width:0;flex:1' },
            h('div', { class: 'ttl', text: i.title }),
            h('div', { class: 'sub' }, pill(i.severity), h('span', { class: 'pill ghost', text: 'Mode ' + i.mode }),
              running ? h('span', { class: 'livepill', text: 'LIVE' }) : null,
              h('span', { class: 'chip', text: nice(i.label) }), multiFlag(i)))),
        running ? h('div', { class: 'prog' }) : null,
        // live token preview, so a running incident visibly streams from the list view too.
        // Seeded from S.cardStream because the card is rebuilt whenever the incident JSON changes.
        running ? h('pre', { class: 'cstream', 'data-cs': i.id, text: S.cardStream[i.id] || '' }) : null,
        h('div', { class: 'foot' },
          h('span', { text: i.id + ' · sensor time ' + (i.created_sim_ist || '-') }),
          h('span', { text: i.npu_calls + ' NPU call' + (i.npu_calls === 1 ? '' : 's') + (running ? '' : ' · ' + (i.total_ms / 1000).toFixed(1) + ' s') }),
          h('span', { class: 'appr ' + i.approval, text: running ? 'Working ...' : i.approval === 'pending' ? 'Needs your decision' : nice(i.approval) })));
    }
    if (box.children[idx] !== e.root) box.insertBefore(e.root, box.children[idx] || null);
  });
  const ids = new Set(S.incs.map((i) => i.id));
  for (const [id, e] of incEls) if (!ids.has(id)) { e.root.remove(); incEls.delete(id); }
  applyIncFilter();
}
async function selectIncident(id) {
  S.incId = id; S.incText = ''; S.inc = null;
  setText($('#isheet-t'), id);
  $('#inc-detail').replaceChildren(h('div', { class: 'empty' }, h('span', { class: 'spin' }), ' Loading ' + id + ' ...'));
  $('#inc-foot').replaceChildren(); $('#inc-foot').dataset.sig = '';
  openSheet('isheet');
  await refreshIncDetail(true);
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
    h('dl', { class: 'kv', style: 'margin-top:12px' },
      h('dt', { text: 'Suggested action' }), h('dd', { style: 'font-weight:700', text: nice(r.action) }),
      h('dt', { text: 'Affected' }), h('dd', {}, (r.affected_domains || []).length ? (r.affected_domains || []).map((d) => h('span', { class: 'chip', style: 'margin:0 6px 4px 0', text: roleTitle[d] || nice(d) })) : '-'),
      h('dt', { text: 'Evidence' }), h('dd', {}, (r.evidence || []).length ? (r.evidence || []).map((t) => h('span', { style: 'margin:0 6px 4px 0;display:inline-block' }, refChip(inc, t))) : h('span', { class: 'muted', text: 'none cited' }))),
    r.requires_human_approval ? h('div', { class: 'note-human', style: 'margin-top:10px', text: 'Requires human approval — no automatic actuation.' }) : null);
}

/* ----- order-tracking model ----- */
function fastText(model) { return /related domains verified steady/i.test(model || '') ? 'Related domains verified steady \u2192 isolated event, no synthesizer call' : 'Single domain \u2192 no synthesizer call needed'; }
function trackModel(inc) {
  const run = inc.state === 'running', mode = inc.mode, f = inc.final;
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
  steps.push({ t: 'Awaiting your approval', s: run ? 'Starts when the analysis is ready' : decided ? (inc.approval === 'approved' ? 'Approved by you' : 'Dismissed by you') : 'Needs your decision — nothing happens automatically', st: run ? 'pending' : decided ? 'done' : 'active' });
  let done = 0; steps.forEach((x) => { if (x.st === 'done' || x.st === 'skip') done += 1; else if (x.st === 'active') done += 0.5; else if (x.st === 'fail') done += 1; });
  const rejected = mode !== 1 && !run && (!f || !f.valid);
  const title = run ? (mode === 1 ? 'Running the rules ...' : mode === 2 ? 'The model is reading your sensors ...' : na < ns ? 'Agents are thinking ...' : 'Writing the report ...')
    : inc.approval === 'approved' ? 'Approved' : inc.approval === 'dismissed' ? 'Dismissed' : rejected ? 'Done, but the safety check flagged it' : 'Ready for your decision';
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
function streamKeyOf(incId, ref) { return incId + ':' + ref; }
function onToken(d) {
  if (!d || !d.incident || !d.ref) return;
  const k = streamKeyOf(d.incident, d.ref);
  S.stream[k] = (S.stream[k] || '') + (d.text || '');
  // The card preview is updated whether or not the incident is open, so the list itself shows the
  // model thinking. Without this, tokens were only ever painted into an already-open detail sheet,
  // so from the incident list the answer simply appeared all at once after ~17 s.
  S.cardStream[d.incident] = ((S.cardStream[d.incident] || '') + (d.text || '')).slice(-240);
  const cs = $('.cstream[data-cs="' + d.incident + '"]');
  if (cs) { cs.textContent = S.cardStream[d.incident]; cs.scrollTop = cs.scrollHeight; }
  if (S.incId !== d.incident) return;
  const el = $('#inc-detail [data-s="' + d.ref + '"]');
  if (el) { el.textContent = S.stream[k]; el.scrollTop = el.scrollHeight; }
  else if (!onToken.t) onToken.t = setTimeout(() => { onToken.t = 0; refreshIncDetail(true); }, 250);
}
function liveCard(ref, role, text, note) {
  return h('div', { class: 'card agent st-none' },
    h('div', { class: 'rep-h' }, h('b', { text: ref + ' · ' + (role ? (roleTitle[role] || role) + ' agent' : 'Model') }), h('span', { class: 'pill orange' }, h('span', { class: 'spin', style: 'width:12px;height:12px;border-width:2px' }), text ? 'Generating' : 'On the NPU')),
    h('pre', { class: 'stream live', 'data-s': ref, text: text || '' }),
    h('div', { class: 'muted', style: 'font-size:13px;margin-top:6px', text: note }));
}

function renderIncFoot(inc) {
  const f = $('#inc-foot'), sig = inc.id + '|' + inc.approval + '|' + inc.state;
  if (f.dataset.sig === sig) return; f.dataset.sig = sig;
  const running = inc.state === 'running', decided = inc.approval && inc.approval !== 'pending';
  if (decided) { f.replaceChildren(h('div', { class: 'foot-row' }, h('span', { class: 'pill ' + (inc.approval === 'approved' ? 'st-normal' : 'ghost') , text: nice(inc.approval).toUpperCase() }), h('span', { class: 'muted', style: 'font-size:14px', text: inc.approval_note ? 'Note: ' + inc.approval_note : 'Decision recorded. No actuator was triggered.' }))); return; }
  const ta = h('input', { class: 'note-in', type: 'text', placeholder: 'Note (required to dismiss)', 'aria-label': 'Operator note', maxlength: '300', oninput: (e) => { S.draft[inc.id] = e.target.value; ta.classList.remove('need'); } });
  ta.value = S.draft[inc.id] || '';
  const act = async (kind) => {
    const note = ta.value.trim();
    if (kind === 'dismiss' && !note) { ta.classList.add('need'); ta.focus(); toast('Add a short note to dismiss', true); return; }
    try { await post('/api/incidents/' + inc.id + '/' + kind, { note }); toast(kind === 'approve' ? 'Approved. Decision recorded' : 'Dismissed'); delete S.draft[inc.id]; await Promise.all([refreshIncidents(), refreshIncDetail(true), refreshStatus()]); }
    catch (e) { toast(kind + ': ' + e.message, true); }
  };
  f.replaceChildren(h('p', { class: 'foot-hint', text: running ? 'Waiting for the analysis to finish ...' : 'Requires human approval — no automatic actuation.' }), ta,
    h('div', { class: 'foot-row', style: 'margin-top:10px' },
      h('button', { class: 'btn danger', type: 'button', text: 'Dismiss', onclick: () => act('dismiss') }),
      h('button', { class: 'btn primary', type: 'button', disabled: running ? true : null, text: 'Approve', onclick: () => act('approve') })));
}

function renderIncDetail() {
  const inc = S.inc, box = $('#inc-detail'); if (!inc) return;
  const running = inc.state === 'running';
  // finished calls no longer need their stream buffer
  (inc.agents || []).forEach((a) => { delete S.stream[streamKeyOf(inc.id, a.ref)]; });
  if (inc.final) delete S.stream[streamKeyOf(inc.id, 'final')];
  const parts = [];
  setText($('#isheet-t'), inc.id);
  parts.push(h('div', { class: 'ltitle', style: 'padding-top:2px' },
    h('div', { class: 'rep-h', style: 'margin-bottom:8px' }, pill(inc.severity), h('span', { class: 'pill ghost', text: 'Mode ' + inc.mode }),
      running ? h('span', { class: 'livepill', text: 'LIVE' }) : null, multiFlag(inc)),
    h('h1', { class: 'inc-title', style: 'font-size:26px;line-height:1.2', text: inc.title }),
    h('p', { text: 'Sensor time ' + (inc.created_sim ? dhm(inc.created_sim) + ' IST' : '-') + ' · analysed ' + (inc.created_wall ? inc.created_wall.slice(-8) : '-') + ' · ' + (inc.sensors || []).length + ' sensors · ' + inc.npu_calls + ' NPU calls' })));
  parts.push(trackCard(inc));
  // cross-domain report
  const f = inc.final;
  const fast = !!(f && isFastModel(f.model));
  const fc = h('div', { class: 'card' }, h('h3', { style: 'font-size:18px;margin-bottom:10px', text: 'Cross-domain report' }));
  if (f) {
    if (fast) fc.append(h('div', { class: 'banner', style: 'margin-bottom:12px' }, icon('check'), h('span', { text: fastText(f.model) + '. The agent finding became the report instantly.' })));
    fc.append(h('div', { class: 'rep-h', style: 'margin-bottom:12px' }, gate(f.valid, f.errors), fast ? null : modelBadge(f.model || 'model', false)));
    if (!fast) { const sc = statChips(f); if (sc) fc.append(sc); }
    if (f.parsed) {
      if (!f.valid) fc.append(h('div', { class: 'errs', style: 'margin:10px 0;padding:0;list-style:none', text: 'Rejected by the policy gate: do not act on the output below.' }));
      fc.append(h('div', { style: 'margin-top:12px' }, reportBody(inc, f.parsed)));
    } else fc.append(h('div', { class: 'muted', style: 'margin-top:10px', text: 'The model output could not be parsed into a report.' }));
    if (!fast) fc.append(details(inc.id + ':final:raw', 'Raw model output', f.raw), details(inc.id + ':final:prompt', 'Prompt (synthesizer)', f.prompt));
  } else if (inc.mode === 1) fc.append(h('div', { class: 'muted', text: 'Mode 1 (rules) writes no AI report. The rule-based summary is further down.' }));
  else if (running) {
    const tx = S.stream[streamKeyOf(inc.id, 'final')];
    const allAgents = inc.mode === 2 || (inc.agents || []).length >= (inc.sensors || []).length;
    if (tx || (inc.mode === 2) || allAgents) fc.append(h('pre', { class: 'stream live', 'data-s': 'final', text: tx || '' }), h('div', { class: 'muted', style: 'font-size:13px;margin-top:6px', text: 'Synthesizer output is typing live ...' }));
    else fc.append(h('div', { class: 'muted' }, h('span', { class: 'spin' }), ' The report is written after every agent has finished.'));
  } else fc.append(h('div', { class: 'muted', text: 'No cross-domain report was produced.' }));
  parts.push(fc);
  // compare
  const seg = makeSeg([{ v: 1, t: 'Rules' }, { v: 2, t: 'Single' }, { v: 3, t: 'Agents' }], async (m) => {
    try { S.pendingNewest = new Set(S.incs.map((i) => i.id)); await post('/api/incidents/' + inc.id + '/rerun?mode=' + m); toast('Re-running ' + inc.id + ' in mode ' + m); setTimeout(refreshIncidents, 400); setTimeout(refreshIncidents, 1500); }
    catch (e) { S.pendingNewest = null; toast('Rerun: ' + e.message, true); }
  }, 'Re-run in another mode');
  setSeg(seg, inc.mode); $$('button', seg).forEach((b) => b.setAttribute('aria-pressed', 'false'));
  parts.push(h('div', { class: 'card' }, h('h3', { style: 'font-size:17px;margin-bottom:4px', text: 'Compare modes' }), h('p', { class: 'muted', style: 'font-size:14px;margin-bottom:10px', text: 'Re-analyse the same frozen sensor windows in another mode. A new incident is created.' }), seg));
  // agents: NPU agents (streaming + metrics) and compact CPU context agents
  const ag = h('div', { class: 'agents' }), cg = h('div', { class: 'agents' });
  const sensors = inc.sensors || [];
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
      const tx = S.stream[streamKeyOf(inc.id, s.ref)];
      if (tx || !nextShown) { nextShown = true; ag.append(liveCard(s.ref, s.role, tx, s.node + ' ' + s.metric + ' — ' + s.location)); }
      else ag.append(h('div', { class: 'card agent st-none' }, h('div', { class: 'rep-h' }, h('b', { text: s.ref + ' · ' + (roleTitle[s.role] || s.role) + ' agent' }), h('span', { class: 'pill ghost', text: 'Queued' })), h('div', { class: 'muted', style: 'font-size:14px;margin-top:6px', text: 'Waiting for the NPU (one job at a time).' })));
    }
  }
  if (ag.children.length) parts.push(h('div', { class: 'sec-h', text: 'Domain agents (NPU, on-device)' }), ag);
  if (cg.children.length) parts.push(h('div', { class: 'sec-h', text: 'Context agents (rules, CPU, instant)' }), cg);
  // sensors: flagged vs related domains
  const sensorCard = (s) => {
    const mini = h('div', { class: 'mini' });
    const occ = s.role === 'occupancy', n = (s.window || []).length;
    const ptsw = (s.window || []).map((v, i) => [(s.window_end || 0) - (n - 1 - i) * 300, v]);
    const cv = STATUS_VAR[s.rule_finding && s.rule_finding.status] || '--nodata-b';
    mini.innerHTML = `<svg viewBox="0 0 260 58" preserveAspectRatio="none" aria-label="48 point window">${sparkSvg(ptsw, 260, 58, cv, occ)}</svg>`;
    mini.append(h('span', { class: 'muted', style: 'font-size:13px', text: n ? n + ' pts · ' + hm(ptsw[0][0]) + ' → ' + hm(ptsw[n - 1][0]) + ' IST' : 'no window' }));
    return h('div', { class: 'card agent ' + stClass(s.rule_finding && s.rule_finding.status) },
      h('div', { class: 'rep-h' }, h('div', { class: 'dico', style: '--cb:' + (ROLE_COLOR[s.role] || ROLE_COLOR.multi) + ';width:34px;height:34px;border-radius:11px' }, icon(s.role, 18)),
        h('b', { text: s.ref + ' · ' + s.node + ' ' + s.metric }), s.rule_finding ? pill(s.rule_finding.status) : null),
      h('div', { class: 'muted', style: 'font-size:14px;margin-top:4px', text: s.location }),
      s.why ? h('div', { class: 'banner', style: 'margin-top:8px;font-weight:500;font-size:13.5px;padding:8px 12px' }, icon('info', 20), h('span', { text: 'Checked because: ' + s.why })) : null,
      mini,
      h('div', { style: 'margin-top:8px;font-size:14.5px' }, 'Rules: ', h('b', { text: nice(s.rule_finding && s.rule_finding.pattern) }), ' · ' + nice(s.rule_finding && s.rule_finding.likely_cause)),
      h('details', { open: S.open.has(inc.id + ':' + s.ref + ':ev') ? true : null, ontoggle: (e) => { e.target.open ? S.open.add(inc.id + ':' + s.ref + ':ev') : S.open.delete(inc.id + ':' + s.ref + ':ev'); } },
        h('summary', { text: 'Evidence ' + s.ref + '.E1..' }), h('ul', { class: 'evlist', style: 'padding:6px 16px 10px' }, (s.evidence || []).map((e) => h('li', {}, h('b', { text: e.ID }), h('span', { text: e.Text }))))));
  };
  const flagged = sensors.filter((s) => !s.context), related = sensors.filter((s) => s.context);
  parts.push(h('div', { class: 'sec-h', text: 'Flagged (' + flagged.length + ')' }), h('div', { class: 'agents' }, flagged.map(sensorCard)));
  if (related.length) parts.push(h('div', { class: 'sec-h', text: 'Related domains checked (' + related.length + ')' }), h('div', { class: 'agents' }, related.map(sensorCard)));
  const m1 = inc.mode1_report;
  if (m1) parts.push(h('div', { class: 'sec-h', text: 'Mode 1 rules baseline' }),
    h('div', { class: 'card shadowc' }, h('p', { class: 'muted', style: 'margin-bottom:10px;font-size:14px', text: 'Deterministic rule engine, no AI. Always computed for comparison.' }), reportBody(inc, m1)));
  parts.push(h('div', { class: 'sec-h', text: 'Activity log' }), h('div', { class: 'card' }, h('ul', { class: 'tl', id: 'tl' }, (inc.timeline || []).map((t) => h('li', {}, h('time', { text: t.t }), h('span', { text: t.msg }))))));
  const bd = $('#inc-detail'), sc = bd.scrollTop;
  box.replaceChildren(...parts);
  renderIncFoot(inc);
  const tl = $('#tl'); if (tl) tl.scrollTop = tl.scrollHeight;
  bd.scrollTop = sc;
}

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
    `<div class="card"><h3 style="font-size:19px;margin-bottom:6px">Everything runs on this device</h3><p class="muted">You set the sensor values on the Sensors tab (or a real device posts them) and a Qualcomm QIDK board analyses them. Statistics, rules, language-model calls and policy checks are all computed locally on the Hexagon NPU. <b style="color:var(--tx)">No cloud, no laptop, no internet connection is used for inference.</b></p></div>
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
    for (const k of ['last', 'sma_1h', 'ema_1h', 'slope_per_h', 'pattern', 'status', 'injected', 'data_ok', 'updated']) if (k in u) s[k] = u[k];
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
  es.onopen = () => { S.sse = true; };
  es.onerror = () => { S.sse = false; if (es.readyState === 2) setTimeout(connect, 3000); };
  const J = (e) => { try { return JSON.parse(e.data); } catch (x) { return {}; } };
  es.addEventListener('tick', (e) => {
    const d = J(e);
    if (d.sim_time_ist) { setText($('#c-time'), d.sim_time_ist.replace(/^\w+ \d+ \w+( \d+)? /, '') + ' IST'); setText($('#l-sub'), 'Sensor time ' + d.sim_time_ist + ' IST'); }
    if (d.npu && S.status) { S.status.npu = d.npu; updateHero(); }
    const now = Date.now();
    if (now - S.lastLiveEv >= 15000 && now - S.lastLive >= 15000 && S.view !== 'about') refreshLive();
    if (now - S.lastStatus >= 4000) refreshStatus();
    if (S.drawer && now - S.lastDrawer >= 5000) loadDrawer();
  });
  es.addEventListener('incident', (e) => {
    const d = J(e);
    refreshIncidents();
    if (d.id && d.id === S.incId) refreshIncDetail(false);
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
  es.addEventListener('live', (e) => onLive(J(e)));
  es.addEventListener('ingest', () => { snLater(); });
  es.addEventListener('mode', (e) => { const d = J(e); if (S.status && d.mode) { S.status.mode = d.mode; renderMode(); } });
}

/* ============================== boot ============================== */
function boot() {
  tabIcons(); buildAbout(); bindHeader(); bindTheme(); buildHero();
  window.addEventListener('hashchange', () => setView(location.hash.slice(1)));
  $('#scrim').onclick = () => { closeSheet('sheet'); closeSheet('isheet'); };
  $$('[data-close]').forEach((b) => b.onclick = () => closeSheet(b.dataset.close));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { if ($('#isheet').classList.contains('open')) closeSheet('isheet'); else if ($('#sheet').classList.contains('open')) closeSheet('sheet'); else hidePop(true); } });
  document.addEventListener('click', (e) => { if (!e.target.closest || !e.target.closest('.chip.ev')) hidePop(true); });
  $('#sheet-bd').addEventListener('scroll', () => hidePop(true), { passive: true });
  $('#inc-detail').addEventListener('scroll', () => hidePop(true), { passive: true });
  setView(location.hash.slice(1) || 'sensors');
  refreshStatus(); refreshLive(); refreshIncidents();
  connect();
  setInterval(sparkLoop, 1000); // each tick measures every tile (layout); 1 Hz is plenty for 10 s refreshes
  setInterval(() => { if (!document.hidden && Date.now() - SN.lastFetch > 4500) snFetch(); }, 1000);
  post('/api/replay', {}).then((r) => { if (r && r.poll_ms) { SN.pollMs = r.poll_ms; if (SN.pollSeg) setSeg(SN.pollSeg, r.poll_ms); } }).catch(() => {});
  setInterval(updateElapsed, 500);
  setInterval(() => {
    if (!S.sse || Date.now() - S.lastLiveEv > 15000) { refreshStatus(); refreshLive(); }
    if (Date.now() - S.lastIncList > 15000) refreshIncidents();
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
