/* Smart City Edge - History page. Plain JS, no external dependencies, works offline.
   Reads GET /api/history?days=N (backend/history.go) and draws: range chips, filters, KPI tiles with a
   previous-period comparison, a one-line story, four modes (Timeline, Heatmap, Breakdown, List) and the
   top recurring sensors. Every chart is hand-written SVG/HTML. Times are IST (Asia/Kolkata) from the
   backend's corrected clock, never the device RTC.
   API: window.SCE_history = { mount(rootEl), refresh() }. Opening an incident calls window.SCE_openIncident(id). */
'use strict';
(() => {

/* ============================== helpers ============================== */
const NS = 'http://www.w3.org/2000/svg';
function h(tag, a, ...kids) {
  const e = document.createElement(tag);
  return dress(e, a, kids);
}
function s(tag, a, ...kids) {
  const e = document.createElementNS(NS, tag);
  return dress(e, a, kids);
}
function dress(e, a, kids) {
  if (a) for (const k in a) {
    const v = a[k];
    if (v == null || v === false) continue;
    if (k === 'class') e.setAttribute('class', v);
    else if (k === 'text') e.textContent = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(3)) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}
const fill = (el, ...kids) => el.replaceChildren(...kids.flat(3).filter((k) => k != null && k !== false));
const pad = (n) => String(n).padStart(2, '0');
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const WD_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const IST_OFF = 19800; // Asia/Kolkata, no DST
const ist = (t) => new Date((t + IST_OFF) * 1000); // read with getUTC*
const istDayStart = (t) => Math.floor((t + IST_OFF) / 86400) * 86400 - IST_OFF;
const istHourStart = (t) => Math.floor((t + IST_OFF) / 3600) * 3600 - IST_OFF;
const wdOf = (t) => (ist(t).getUTCDay() + 6) % 7; // Mon = 0
const hm = (t) => { const d = ist(t); return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); };
const dmy = (t) => { const d = ist(t); return d.getUTCDate() + ' ' + MON[d.getUTCMonth()]; };
const dmyhm = (t) => dmy(t) + ', ' + hm(t) + ' IST';
const nice = (x) => (x == null || x === '' ? '-' : String(x).replace(/_/g, ' '));
function dur(sec) {
  if (!sec || sec < 0) return '-';
  if (sec < 60) return Math.round(sec) + ' s';
  if (sec < 3600) return Math.round(sec / 60) + ' min';
  if (sec < 86400) { const x = sec / 3600; return (x < 10 ? x.toFixed(1) : Math.round(x)) + ' h'; }
  return (sec / 86400).toFixed(1) + ' d';
}
function msTxt(ms) {
  if (!ms || ms <= 0) return '-';
  if (ms < 1000) return Math.round(ms) + ' ms';
  if (ms < 60000) { const x = ms / 1000; return (x < 10 ? x.toFixed(1) : Math.round(x)) + ' s'; }
  return (ms / 60000).toFixed(1) + ' min';
}
function median(v) {
  if (!v.length) return 0;
  const a = v.slice().sort((x, y) => x - y), m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
function niceMax(v) {
  if (v <= 4) return Math.max(1, v);
  const p = Math.pow(10, Math.floor(Math.log10(v))), f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}
const reduceMotion = () => { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; } };

/* ============================== vocabulary ============================== */
const SEVS = ['critical', 'warning', 'sensor_fault', 'normal'];
const SEV_LABEL = { critical: 'Critical', warning: 'Warning', sensor_fault: 'Sensor fault', normal: 'Normal' };
const SEV_GLYPH = { critical: '■', warning: '▲', sensor_fault: '◆', normal: '●' };
const SEV_RANK = { critical: 3, sensor_fault: 2, warning: 1, normal: 0 };
const ROLE = { air_quality: 'Air quality', water: 'Water', power: 'Power', occupancy: 'Occupancy', weather: 'Weather', hvac: 'HVAC', unknown: 'Unknown' };
const OUTCOME = {
  fixed_by_action: 'Fixed by action', sensor_replaced: 'Sensor replaced', sensor_repaired: 'Sensor repaired',
  resolved_on_its_own: 'Resolved on its own', false_alarm: 'False alarm', no_action_needed: 'No action needed',
  normal_operation: 'Normal operation', open: 'Still open', unrecorded: 'Closed, no outcome',
};
const WF = { analysing: 'Analysing', needs_decision: 'Needs decision', in_progress: 'In progress', resolved: 'Back to normal', closed: 'Closed', interrupted: 'Interrupted' };
const roleName = (r) => ROLE[r] || nice(r);
const outName = (o) => OUTCOME[o] || nice(o);
const RANGES = [{ d: 1, t: '24 h' }, { d: 7, t: '7 days' }, { d: 30, t: '30 days' }, { d: 90, t: '90 days' }];
const MODES = [{ k: 'timeline', t: 'Timeline' }, { k: 'heatmap', t: 'Heatmap' }, { k: 'breakdown', t: 'Breakdown' }, { k: 'list', t: 'List' }];
const PAGE = 60;

/* ============================== state ============================== */
const LS = 'sce-history-v1';
const DEF = () => ({ days: 7, mode: 'timeline', sev: [], dom: '', bld: '', st: 'all', out: '', faults: false, q: '', sortK: 't', sortD: -1 });
const S = { p: DEF(), drill: null, data: null, prev: null, loading: false, err: '', root: null, el: {}, shown: PAGE, seq: 0, fetchedAt: 0 };
function load() {
  try {
    const v = JSON.parse(localStorage.getItem(LS) || 'null');
    if (v && typeof v === 'object') {
      const d = DEF();
      for (const k in d) if (k in v && typeof v[k] === typeof d[k]) d[k] = v[k];
      if (!RANGES.some((r) => r.d === d.days)) d.days = 7;
      if (!MODES.some((m) => m.k === d.mode)) d.mode = 'timeline';
      d.sev = Array.isArray(v.sev) ? v.sev.filter((x) => SEVS.includes(x)) : [];
      S.p = d;
    }
  } catch (e) { /* private mode or blocked storage: defaults */ }
}
function save() { try { localStorage.setItem(LS, JSON.stringify(S.p)); } catch (e) { /* ignore */ } }

/* ============================== data ============================== */
async function fetchData() {
  const days = S.p.days, want = Math.min(days * 2, 90); // twice the range: the previous period for the deltas
  const my = ++S.seq;
  S.loading = true; S.err = ''; renderStatus();
  try {
    const r = await fetch('/api/history?days=' + want, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const j = await r.json();
    if (my !== S.seq) return; // a newer request won
    const now = j.now || Math.floor(Date.now() / 1000), cut = now - days * 86400, pcut = now - 2 * days * 86400;
    const all = Array.isArray(j.incidents) ? j.incidents : [];
    S.data = { now, from: cut, days, truncated: !!j.truncated, rows: all.filter((x) => x.t >= cut) };
    S.prev = want >= days * 2 ? all.filter((x) => x.t >= pcut && x.t < cut) : null;
    S.fetchedAt = now; S.shown = PAGE;
  } catch (e) {
    if (my !== S.seq) return;
    S.err = 'Could not load the history (' + (e && e.message ? e.message : 'network') + ').';
  } finally {
    if (my === S.seq) { S.loading = false; render(); }
  }
}

function match(x, p, drill, skip) {
  if (skip !== 'sev' && p.sev.length && !p.sev.includes(x.sev)) return false;
  if (p.dom && !(x.domains || []).includes(p.dom) && !(p.dom === 'unknown' && !(x.domains || []).length)) return false;
  if (p.bld && (x.building || 'unknown') !== p.bld) return false;
  if (p.st === 'open' && !x.open) return false;
  if (p.st === 'closed' && x.open) return false;
  if (p.out && outcomeKey(x) !== p.out) return false;
  if (p.faults && !x.sensor_fault) return false;
  if (p.q) {
    const hay = (x.id + ' ' + x.title + ' ' + (x.sensors || []).join(' ') + ' ' + (x.domains || []).map(roleName).join(' ') + ' ' +
      (x.building || '') + ' ' + (x.site || '') + ' ' + (x.owner || '') + ' ' + outName(outcomeKey(x))).toLowerCase();
    for (const w of p.q.toLowerCase().split(/\s+/)) if (w && !hay.includes(w)) return false;
  }
  if (drill) {
    if (drill.kind === 'span' && (x.t < drill.a || x.t >= drill.b)) return false;
    if (drill.kind === 'wh' && (wdOf(x.t) !== drill.wd || ist(x.t).getUTCHours() !== drill.hr)) return false;
  }
  return true;
}
const outcomeKey = (x) => x.outcome || (x.open ? 'open' : 'unrecorded');
const rows = () => (S.data ? S.data.rows.filter((x) => match(x, S.p, S.drill)) : []);
const prevRows = () => (S.prev ? S.prev.filter((x) => match(x, S.p, null)) : null);
const activeFilters = () => (S.p.sev.length ? 1 : 0) + (S.p.dom ? 1 : 0) + (S.p.bld ? 1 : 0) + (S.p.st !== 'all' ? 1 : 0) + (S.p.out ? 1 : 0) + (S.p.faults ? 1 : 0) + (S.p.q ? 1 : 0);

function stats(list) {
  const acks = [], closes = [], ais = [];
  let crit = 0, faults = 0, open = 0, rec = 0;
  for (const x of list) {
    if (x.sev === 'critical') crit++;
    if (x.sensor_fault) faults++;
    if (x.open) open++;
    if (x.recurred) rec++;
    if (x.ack_s > 0) acks.push(x.ack_s);
    if (x.close_s > 0) closes.push(x.close_s);
    if (x.ai_ms > 0) ais.push(x.ai_ms);
  }
  return { n: list.length, crit, faults, open, rec, faultPct: list.length ? (faults * 100) / list.length : 0,
    ack: median(acks), close: median(closes), ai: median(ais), nAck: acks.length, nClose: closes.length, nAi: ais.length };
}
function countBy(list, fn) {
  const m = new Map();
  for (const x of list) for (const k of [].concat(fn(x))) m.set(k, (m.get(k) || 0) + 1);
  return m;
}

/* ============================== tooltip ============================== */
function tipShow(el) {
  const t = S.el.tip; if (!t || !el || !el.dataset || !el.dataset.tip) return;
  t.textContent = el.dataset.tip; t.hidden = false;
  const rr = S.root.getBoundingClientRect(), r = el.getBoundingClientRect();
  const tw = t.offsetWidth, th = t.offsetHeight;
  let x = r.left - rr.left + r.width / 2 - tw / 2, y = r.top - rr.top - th - 8;
  x = Math.max(4, Math.min(x, rr.width - tw - 4));
  if (y < 0) y = r.bottom - rr.top + 8;
  t.style.transform = 'translate(' + Math.round(x) + 'px,' + Math.round(y) + 'px)';
}
function tipHide() { if (S.el.tip) S.el.tip.hidden = true; }
function bindTips(box) {
  box.addEventListener('pointerover', (e) => { const el = e.target.closest && e.target.closest('[data-tip]'); if (el) tipShow(el); });
  box.addEventListener('pointerout', (e) => { const el = e.target.closest && e.target.closest('[data-tip]'); if (el && !el.contains(e.relatedTarget)) tipHide(); });
  box.addEventListener('focusin', (e) => { const el = e.target.closest && e.target.closest('[data-tip]'); if (el) tipShow(el); });
  box.addEventListener('focusout', tipHide);
}
/* clickable SVG mark: focusable, Enter/Space activates, label for screen readers + tooltip */
function act(el, label, fn) {
  el.setAttribute('tabindex', '0'); el.setAttribute('role', 'button'); el.setAttribute('aria-label', label);
  el.dataset.tip = label; el.classList.add('hx-act');
  el.addEventListener('click', fn);
  el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); } });
  return el;
}

/* ============================== skeleton ============================== */
function build(root) {
  root.classList.add('hx');
  const E = S.el;
  E.range = h('div', { class: 'hx-range', role: 'radiogroup', 'aria-label': 'Time range' });
  E.refresh = h('button', { type: 'button', class: 'hx-ibtn', 'aria-label': 'Reload the history', title: 'Reload', onclick: () => fetchData() },
    s('svg', { viewBox: '0 0 24 24', width: 20, height: 20, 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
      s('path', { d: 'M4 4v6h6' }), s('path', { d: 'M5.5 15a8 8 0 1 0 1.5-8.5L4 10' })));
  E.status = h('span', { class: 'hx-status', role: 'status', 'aria-live': 'polite' });
  E.sevs = h('div', { class: 'hx-sevs', role: 'group', 'aria-label': 'Filter by severity' });
  E.ftoggle = h('button', { type: 'button', class: 'hx-ftog', 'aria-expanded': 'false', 'aria-controls': 'hx-fbody', onclick: () => {
    const on = E.ftoggle.getAttribute('aria-expanded') !== 'true';
    E.ftoggle.setAttribute('aria-expanded', String(on)); E.fbody.classList.toggle('open', on);
  } });
  E.q = h('input', { type: 'search', class: 'hx-in', placeholder: 'Search title, sensor, ID, person', 'aria-label': 'Search incidents', autocomplete: 'off' });
  let qt = 0;
  E.q.addEventListener('input', () => { clearTimeout(qt); qt = setTimeout(() => { S.p.q = E.q.value.trim(); changed(); }, 180); });
  E.dom = sel('Domain', (v) => { S.p.dom = v; changed(); });
  E.bld = sel('Building', (v) => { S.p.bld = v; changed(); });
  E.out = sel('Outcome', (v) => { S.p.out = v; changed(); });
  E.st = h('div', { class: 'hx-seg', role: 'radiogroup', 'aria-label': 'Open or closed' });
  E.faults = h('input', { type: 'checkbox', id: 'hx-faults', onchange: () => { S.p.faults = E.faults.checked; changed(); } });
  E.reset = h('button', { type: 'button', class: 'hx-link', text: 'Reset filters', onclick: () => {
    const keep = { days: S.p.days, mode: S.p.mode, sortK: S.p.sortK, sortD: S.p.sortD };
    S.p = Object.assign(DEF(), keep); S.drill = null; E.q.value = ''; changed();
  } });
  E.fbody = h('div', { class: 'hx-fbody', id: 'hx-fbody' },
    h('label', { class: 'hx-f hx-fq' }, h('span', { text: 'Search' }), E.q),
    h('label', { class: 'hx-f' }, h('span', { text: 'Domain' }), E.dom),
    h('label', { class: 'hx-f' }, h('span', { text: 'Building' }), E.bld),
    h('label', { class: 'hx-f' }, h('span', { text: 'Outcome' }), E.out),
    h('div', { class: 'hx-f' }, h('span', { text: 'State' }), E.st),
    h('label', { class: 'hx-chk', for: 'hx-faults' }, E.faults, h('span', { text: 'Sensor faults only' })),
    E.reset);
  E.drill = h('div', { class: 'hx-drill', 'aria-live': 'polite' });
  E.story = h('p', { class: 'hx-story' });
  E.kpis = h('div', { class: 'hx-kpis', role: 'list', 'aria-label': 'Key numbers' });
  E.modes = h('div', { class: 'hx-modes', role: 'tablist', 'aria-label': 'View mode' });
  E.panel = h('div', { class: 'hx-panel card', role: 'tabpanel', id: 'hx-panel', tabindex: '-1' });
  E.side = h('aside', { class: 'hx-side card', 'aria-labelledby': 'hx-top-h' });
  E.tip = h('div', { class: 'hx-tip', role: 'tooltip', hidden: true });
  E.note = h('p', { class: 'hx-note' });
  fill(root,
    h('div', { class: 'hx-topbar' }, E.range, h('div', { class: 'hx-bar-r' }, E.status, E.refresh)),
    h('div', { class: 'hx-filters' }, h('div', { class: 'hx-frow' }, E.sevs, E.ftoggle), E.fbody),
    E.drill, E.story, E.kpis,
    E.modes,
    h('div', { class: 'hx-main' }, E.panel, E.side),
    E.note, E.tip);
  bindTips(root);
  let rt = 0;
  const onResize = () => { clearTimeout(rt); rt = setTimeout(() => { if (S.root && S.root.offsetParent !== null && (S.p.mode === 'timeline' || S.p.mode === 'heatmap')) renderPanel(); }, 150); };
  if (window.ResizeObserver) { let lw = 0; new ResizeObserver((en) => { const w = Math.round(en[0].contentRect.width); if (w !== lw) { lw = w; onResize(); } }).observe(E.panel); }
  else window.addEventListener('resize', onResize);
  E.panel.addEventListener('scroll', tipHide, { passive: true });
  window.addEventListener('scroll', tipHide, { passive: true });
}
function sel(label, on) {
  const e = h('select', { class: 'hx-sel', 'aria-label': 'Filter by ' + label.toLowerCase() });
  e.addEventListener('change', () => on(e.value));
  return e;
}
function setOpts(selEl, label, entries, cur) {
  const want = [['', 'All ' + label]].concat(entries);
  if (cur && !entries.some((x) => x[0] === cur)) want.push([cur, nice(cur) + ' (0)']); // a saved filter with nothing in this range
  const sig = JSON.stringify(want);
  if (selEl._sig !== sig) { fill(selEl, want.map(([v, t]) => h('option', { value: v, text: t }))); selEl._sig = sig; }
  selEl.value = cur || '';
}
function changed() { save(); S.shown = PAGE; render(); }

/* ============================== render ============================== */
function renderStatus() {
  const E = S.el; if (!E.status) return;
  E.status.textContent = S.loading ? 'Loading ...' : S.err ? '' : S.fetchedAt ? 'Updated ' + hm(S.fetchedAt) + ' IST' : '';
  E.refresh.disabled = S.loading;
  E.refresh.classList.toggle('spin', S.loading && !reduceMotion());
  if (S.root) S.root.setAttribute('aria-busy', String(S.loading));
}
function render() {
  if (!S.root) return;
  renderStatus(); renderControls();
  const E = S.el;
  if (S.err && !S.data) {
    fill(E.panel, h('div', { class: 'hx-empty' }, h('p', { text: S.err }), h('button', { type: 'button', class: 'btn sm', text: 'Try again', onclick: () => fetchData() })));
    fill(E.kpis); fill(E.side); E.story.textContent = ''; return;
  }
  if (!S.data) { fill(E.panel, h('div', { class: 'hx-empty', text: 'Loading the stored history ...' })); return; }
  renderKpis(); renderStory(); renderModes(); renderPanel(); renderSide();
  E.note.textContent = (S.err ? S.err + ' Showing the last data. ' : '') + (S.data.truncated ? 'Very busy period: only the newest 5000 incidents are listed. ' : '') +
    'All times IST (Asia/Kolkata), from the edge device\'s corrected clock.';
}

function renderControls() {
  const E = S.el, p = S.p, base = S.data ? S.data.rows : [];
  fill(E.range, RANGES.map((r) => {
    const on = r.d === p.days;
    return h('button', { type: 'button', role: 'radio', 'aria-checked': String(on), class: 'hx-chip' + (on ? ' on' : ''), tabindex: on ? '0' : '-1', text: r.t,
      onclick: () => { if (p.days !== r.d) { p.days = r.d; S.drill = null; save(); fetchData(); } },
      onkeydown: radioKeys });
  }));
  // severity chips show counts under the other filters
  const sevBase = base.filter((x) => match(x, p, S.drill, 'sev'));
  const sc = countBy(sevBase, (x) => x.sev);
  fill(E.sevs, SEVS.map((k) => {
    const on = p.sev.includes(k);
    return h('button', { type: 'button', class: 'hx-sev hx-s-' + k + (on ? ' on' : ''), 'aria-pressed': String(on),
      'aria-label': SEV_LABEL[k] + ', ' + (sc.get(k) || 0) + ' incidents',
      onclick: () => { p.sev = on ? p.sev.filter((x) => x !== k) : p.sev.concat(k); changed(); } },
    h('span', { class: 'hx-glyph', 'aria-hidden': 'true', text: SEV_GLYPH[k] }), SEV_LABEL[k], h('span', { class: 'hx-n', text: sc.get(k) || 0 }));
  }));
  const n = activeFilters() - (p.sev.length ? 1 : 0);
  fill(E.ftoggle, 'Filters', n ? h('span', { class: 'hx-n', text: n }) : null);
  const doms = [...countBy(base, (x) => (x.domains && x.domains.length ? x.domains : ['unknown'])).entries()].sort((a, b) => b[1] - a[1]);
  setOpts(E.dom, 'domains', doms.map(([k, c]) => [k, roleName(k) + ' (' + c + ')']), p.dom);
  const blds = [...countBy(base, (x) => x.building || 'unknown').entries()].sort((a, b) => b[1] - a[1]);
  setOpts(E.bld, 'buildings', blds.map(([k, c]) => [k, (k === 'unknown' ? 'Unknown' : k) + ' (' + c + ')']), p.bld);
  const outs = [...countBy(base, outcomeKey).entries()].sort((a, b) => b[1] - a[1]);
  setOpts(E.out, 'outcomes', outs.map(([k, c]) => [k, outName(k) + ' (' + c + ')']), p.out);
  fill(E.st, [['all', 'All'], ['open', 'Open'], ['closed', 'Closed']].map(([k, t]) => {
    const on = p.st === k;
    return h('button', { type: 'button', role: 'radio', 'aria-checked': String(on), tabindex: on ? '0' : '-1', class: on ? 'on' : '', text: t,
      onclick: () => { p.st = k; changed(); }, onkeydown: radioKeys });
  }));
  E.faults.checked = p.faults;
  if (document.activeElement !== E.q) E.q.value = p.q;
  E.reset.hidden = !activeFilters() && !S.drill;
  if (S.drill) {
    fill(E.drill, h('span', { class: 'hx-dchip' }, h('span', { text: S.drill.label }),
      h('button', { type: 'button', class: 'hx-x', 'aria-label': 'Clear ' + S.drill.label, text: '×', onclick: () => { S.drill = null; changed(); } })));
  } else fill(E.drill);
}
function radioKeys(e) {
  const k = e.key; if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(k)) return;
  const box = e.currentTarget.parentElement; if (!box) return;
  const list = [...box.children]; const i = list.indexOf(e.currentTarget);
  const j = k === 'Home' ? 0 : k === 'End' ? list.length - 1 : (i + (k === 'ArrowLeft' || k === 'ArrowUp' ? -1 : 1) + list.length) % list.length;
  e.preventDefault(); list[j].click();
  const t = box.children[j]; if (t) t.focus(); // the group re-renders in place: focus the new button
}

function rangeWord() { const r = RANGES.find((x) => x.d === S.p.days); return r.d === 1 ? 'last 24 h' : 'last ' + r.t; }

function renderKpis() {
  const cur = stats(rows()), pr = S.drill ? null : prevRows(), ps = pr ? stats(pr) : null; // no deltas on a drilled slice
  const tile = (label, val, sub, delta) => h('div', { class: 'hx-kpi', role: 'listitem' },
    h('div', { class: 'hx-kl', text: label }), h('div', { class: 'hx-kv', text: val }),
    h('div', { class: 'hx-ks' }, delta, sub ? h('span', { text: sub }) : null));
  // lower is better for every tile here
  const dlt = (a, b, unit) => {
    if (!ps || b == null || (!a && !b)) return null;
    if (!b) return h('span', { class: 'hx-d up', text: 'new', title: 'none in the previous period' });
    const d = ((a - b) / b) * 100; if (Math.abs(d) < 1) return h('span', { class: 'hx-d', text: '= prev' });
    const up = d > 0;
    return h('span', { class: 'hx-d ' + (up ? 'up' : 'down'), 'aria-label': (up ? 'up ' : 'down ') + Math.abs(Math.round(d)) + '% on the previous period' + (unit || ''),
      text: (up ? '▲ ' : '▼ ') + Math.abs(Math.round(d)) + '%' });
  };
  fill(S.el.kpis,
    tile('Incidents', String(cur.n), cur.open ? cur.open + ' open' : 'none open', dlt(cur.n, ps && ps.n)),
    tile('Critical', String(cur.crit), cur.n ? Math.round((cur.crit * 100) / cur.n) + '% of all' : '', dlt(cur.crit, ps && ps.crit)),
    tile('Time to acknowledge', dur(cur.ack), cur.nAck ? 'median of ' + cur.nAck : 'none acknowledged', ps && ps.nAck ? dlt(cur.ack, ps.ack) : null),
    tile('Time to close', dur(cur.close), cur.nClose ? 'median of ' + cur.nClose : 'none closed', ps && ps.nClose ? dlt(cur.close, ps.close) : null),
    tile('Sensor faults', Math.round(cur.faultPct) + '%', cur.faults + ' incident' + (cur.faults === 1 ? '' : 's'), ps && ps.n ? dlt(cur.faultPct, ps.faultPct) : null),
    tile('AI report latency', msTxt(cur.ai), cur.nAi ? 'median of ' + cur.nAi : 'no finished report', ps && ps.nAi ? dlt(cur.ai, ps.ai) : null));
}

function renderStory() {
  const list = rows(), n = list.length;
  if (!n) { S.el.story.textContent = (activeFilters() || S.drill ? 'Nothing matches these filters in the ' : 'No incidents in the ') + rangeWord() + '.'; return; }
  const parts = [n + ' incident' + (n === 1 ? '' : 's') + ' in the ' + rangeWord()];
  const crit = list.filter((x) => x.sev === 'critical').length;
  if (crit) parts[0] += ', ' + crit + ' critical';
  const dm = [...countBy(list, (x) => x.domains || []).entries()].sort((a, b) => b[1] - a[1])[0];
  if (dm) parts.push('most in ' + roleName(dm[0]) + ' (' + dm[1] + ')');
  if (n >= 3) {
    const hc = new Map(); for (const x of list) { const k = wdOf(x.t) * 24 + ist(x.t).getUTCHours(); hc.set(k, (hc.get(k) || 0) + 1); }
    const b = [...hc.entries()].sort((a, c) => c[1] - a[1])[0];
    if (b && b[1] > 1) parts.push('busiest slot ' + WD[Math.floor(b[0] / 24)] + ' ' + pad(b[0] % 24) + ':00');
  }
  const rec = list.filter((x) => x.recurred).length;
  if (rec) parts.push(rec + ' came back after closing');
  S.el.story.textContent = parts.join(' · ') + '.';
}

function renderModes() {
  fill(S.el.modes, MODES.map((m) => {
    const on = S.p.mode === m.k;
    return h('button', { type: 'button', role: 'tab', id: 'hx-tab-' + m.k, 'aria-selected': String(on), 'aria-controls': 'hx-panel', tabindex: on ? '0' : '-1',
      class: 'hx-mode' + (on ? ' on' : ''), text: m.t, onclick: () => { if (S.p.mode !== m.k) { S.p.mode = m.k; save(); renderModes(); renderPanel(); } },
      onkeydown: radioKeys });
  }));
  S.el.panel.setAttribute('aria-labelledby', 'hx-tab-' + S.p.mode);
}

function renderPanel() {
  tipHide();
  const list = rows(), P = S.el.panel;
  if (!list.length) {
    fill(P, h('div', { class: 'hx-empty' }, h('p', { text: activeFilters() || S.drill ? 'Nothing matches these filters.' : 'No incidents were stored in the ' + rangeWord() + '. A quiet campus.' }),
      activeFilters() || S.drill ? h('button', { type: 'button', class: 'btn sm', text: 'Reset filters', onclick: () => S.el.reset.click() }) : null));
    return;
  }
  const m = S.p.mode;
  if (m === 'timeline') renderTimeline(P, list);
  else if (m === 'heatmap') renderHeat(P, list);
  else if (m === 'breakdown') renderBreakdown(P, list);
  else renderList(P, list);
}
function drillTo(d) { S.drill = d; S.p.mode = 'list'; save(); S.shown = PAGE; render(); try { S.el.panel.focus({ preventScroll: true }); } catch (e) { /* ignore */ } }
function legend() {
  return h('div', { class: 'hx-legend', 'aria-hidden': 'true' }, SEVS.map((k) => h('span', null, h('i', { class: 'hx-sw hx-f-' + k }), SEV_LABEL[k])));
}

/* ---------- Timeline: stacked bars per day (per hour on 24 h) ---------- */
function renderTimeline(P, list) {
  const D = S.data, hourly = D.days === 1;
  const step = hourly ? 3600 : 86400;
  const end = hourly ? istHourStart(D.now) : istDayStart(D.now);
  const start = hourly ? end - 23 * 3600 : istDayStart(D.from);
  const nb = Math.round((end - start) / step) + 1;
  const B = Array.from({ length: nb }, (_, i) => ({ a: start + i * step, c: { critical: 0, warning: 0, sensor_fault: 0, normal: 0 }, n: 0 }));
  for (const x of list) {
    const i = Math.floor(((hourly ? istHourStart(x.t) : istDayStart(x.t)) - start) / step);
    if (i >= 0 && i < nb) { B[i].c[x.sev in B[i].c ? x.sev : 'warning']++; B[i].n++; }
  }
  const W = Math.max(280, Math.floor(P.clientWidth - 32) || 600), Hh = W < 500 ? 190 : 240;
  const ml = 30, mr = 6, mt = 10, mb = 24, cw = W - ml - mr, ch = Hh - mt - mb;
  const mx = niceMax(Math.max(1, ...B.map((b) => b.n)));
  const bw = cw / nb, gap = Math.min(4, bw * 0.22);
  const svg = s('svg', { class: 'hx-svg', viewBox: '0 0 ' + W + ' ' + Hh, width: W, height: Hh, role: 'group',
    'aria-label': 'Incidents per ' + (hourly ? 'hour' : 'day') + ', stacked by severity. Select a bar to list its incidents.' });
  for (let g = 0; g <= 2; g++) {
    const v = (mx * g) / 2, y = mt + ch - (v / mx) * ch;
    svg.append(s('line', { class: 'hx-grid', x1: ml, x2: W - mr, y1: y, y2: y }),
      s('text', { class: 'hx-ax', x: ml - 6, y: y + 4, 'text-anchor': 'end', text: Number.isInteger(v) ? v : v.toFixed(1) }));
  }
  const anim = !reduceMotion();
  B.forEach((b, i) => {
    const x = ml + i * bw + gap / 2, w = Math.max(1, bw - gap);
    const lbl = (hourly ? hm(b.a) + ' to ' + hm(b.a + 3600) + ' IST' : WD[wdOf(b.a)] + ' ' + dmy(b.a)) + ': ' + b.n + ' incident' + (b.n === 1 ? '' : 's') +
      (b.n ? ' (' + SEVS.filter((k) => b.c[k]).map((k) => b.c[k] + ' ' + SEV_LABEL[k].toLowerCase()).join(', ') + ')' : '');
    const g = s('g', { class: 'hx-bar' + (anim ? ' grow' : ''), style: anim ? { animationDelay: Math.min(i * 12, 400) + 'ms' } : null });
    g.append(s('rect', { class: 'hx-hit', x: ml + i * bw, y: mt, width: bw, height: ch }));
    let y = mt + ch;
    for (const k of ['normal', 'sensor_fault', 'warning', 'critical']) {
      const n = b.c[k]; if (!n) continue;
      const hh = (n / mx) * ch; y -= hh;
      g.append(s('rect', { class: 'hx-f-' + k, x, y, width: w, height: Math.max(1, hh - (y > mt ? 0.75 : 0)), rx: Math.min(2, w / 3) }));
    }
    if (b.n) act(g, lbl, () => drillTo({ kind: 'span', a: b.a, b: b.a + step, label: hourly ? hm(b.a) + ' to ' + hm(b.a + 3600) + ' IST' : WD[wdOf(b.a)] + ' ' + dmy(b.a) }));
    svg.append(g);
  });
  // x labels: ~6 evenly spaced, always the last
  const every = Math.max(1, Math.ceil(nb / (W < 500 ? 5 : 8)));
  B.forEach((b, i) => {
    if ((nb - 1 - i) % every) return;
    svg.append(s('text', { class: 'hx-ax', x: ml + i * bw + bw / 2, y: Hh - 6, 'text-anchor': 'middle', text: hourly ? hm(b.a) : dmy(b.a) }));
  });
  const peak = B.reduce((a, b) => (b.n > a.n ? b : a), B[0]);
  fill(P, h('div', { class: 'hx-ph' }, h('h2', { class: 'hx-h', text: hourly ? 'Incidents per hour' : 'Incidents per day' }),
    peak.n ? h('span', { class: 'hx-sub', text: 'Peak ' + peak.n + ' on ' + (hourly ? hm(peak.a) : dmy(peak.a)) }) : null),
  h('div', { class: 'hx-chart' }, svg), legend(), sevTable(B, hourly));
}
/* screen-reader table of the same numbers */
function sevTable(B, hourly) {
  return h('table', { class: 'sr-only hx-sr' }, h('caption', { text: 'Incidents per ' + (hourly ? 'hour' : 'day') }),
    h('thead', null, h('tr', null, h('th', { scope: 'col', text: hourly ? 'Hour' : 'Day' }), SEVS.map((k) => h('th', { scope: 'col', text: SEV_LABEL[k] })))),
    h('tbody', null, B.filter((b) => b.n).map((b) => h('tr', null, h('th', { scope: 'row', text: hourly ? hm(b.a) : dmy(b.a) }), SEVS.map((k) => h('td', { text: b.c[k] }))))));
}

/* ---------- Heatmap: weekday x hour of day ---------- */
function renderHeat(P, list) {
  const M = Array.from({ length: 7 }, () => new Array(24).fill(0));
  const C = Array.from({ length: 7 }, () => new Array(24).fill(0));
  for (const x of list) { const w = wdOf(x.t), hr = ist(x.t).getUTCHours(); M[w][hr]++; if (x.sev === 'critical') C[w][hr]++; }
  const mx = Math.max(1, ...M.flat());
  const W = Math.max(300, Math.floor(P.clientWidth - 32) || 600);
  const ml = 34, mt = 4, mb = 22, cell = Math.max(9, Math.floor((W - ml - 4) / 24)), rowH = Math.max(18, Math.min(30, cell + 4));
  const Hh = mt + rowH * 7 + mb, gw = ml + cell * 24;
  const svg = s('svg', { class: 'hx-svg', viewBox: '0 0 ' + gw + ' ' + Hh, width: gw, height: Hh, role: 'group',
    'aria-label': 'Incidents by weekday and hour of day (IST). Darker means more. Select a cell to list its incidents.' });
  for (let w = 0; w < 7; w++) {
    svg.append(s('text', { class: 'hx-ax', x: ml - 6, y: mt + w * rowH + rowH / 2 + 4, 'text-anchor': 'end', text: WD[w] }));
    for (let hr = 0; hr < 24; hr++) {
      const n = M[w][hr], x = ml + hr * cell + 1, y = mt + w * rowH + 1;
      const r = s('rect', { class: n ? 'hx-cell' : 'hx-cell0', x, y, width: cell - 2, height: rowH - 2, rx: 3,
        style: n ? { fillOpacity: (0.18 + 0.82 * (n / mx)).toFixed(2) } : null });
      const g = s('g', null, r);
      if (C[w][hr]) g.append(s('circle', { class: 'hx-critdot', cx: x + cell - 5, cy: y + 4, r: 2 }));
      if (n) act(g, WD_LONG[w] + ' ' + pad(hr) + ':00 to ' + pad((hr + 1) % 24) + ':00 IST: ' + n + ' incident' + (n === 1 ? '' : 's') + (C[w][hr] ? ', ' + C[w][hr] + ' critical' : ''),
        () => drillTo({ kind: 'wh', wd: w, hr, label: WD[w] + ' ' + pad(hr) + ':00-' + pad((hr + 1) % 24) + ':00 IST' }));
      svg.append(g);
    }
  }
  for (let hr = 0; hr < 24; hr += 3) svg.append(s('text', { class: 'hx-ax', x: ml + hr * cell + cell / 2, y: Hh - 6, 'text-anchor': 'middle', text: pad(hr) }));
  // hour totals + busiest slot
  const byHr = new Array(24).fill(0); for (let w = 0; w < 7; w++) for (let hr = 0; hr < 24; hr++) byHr[hr] += M[w][hr];
  const day = byHr.slice(8, 20).reduce((a, b) => a + b, 0), night = list.length - day;
  fill(P, h('div', { class: 'hx-ph' }, h('h2', { class: 'hx-h', text: 'When incidents happen' }),
    h('span', { class: 'hx-sub', text: Math.round((night * 100) / list.length) + '% outside 08:00-20:00 IST' })),
  h('div', { class: 'hx-chart hx-scrollx' }, svg),
  h('div', { class: 'hx-legend', 'aria-hidden': 'true' }, h('span', null, 'Fewer'), h('i', { class: 'hx-ramp' }), h('span', null, 'More'),
    h('span', null, h('i', { class: 'hx-critdot-l' }), 'has critical')),
  h('table', { class: 'sr-only hx-sr' }, h('caption', { text: 'Incidents by weekday and hour (non-zero only)' }),
    h('tbody', null, M.flatMap((row, w) => row.map((n, hr) => (n ? h('tr', null, h('th', { scope: 'row', text: WD_LONG[w] + ' ' + pad(hr) + ':00' }), h('td', { text: n })) : null))))));
}

/* ---------- Breakdown: domain / building / outcome / response times ---------- */
function renderBreakdown(P, list) {
  const sevSplit = (fn) => {
    const m = new Map();
    for (const x of list) for (const k of [].concat(fn(x))) {
      if (!m.has(k)) m.set(k, { k, n: 0, c: { critical: 0, warning: 0, sensor_fault: 0, normal: 0 } });
      const e = m.get(k); e.n++; e.c[x.sev in e.c ? x.sev : 'warning']++;
    }
    return [...m.values()].sort((a, b) => b.n - a.n);
  };
  const group = (title, data, name, onPick, cur) => {
    const mx = Math.max(1, ...data.map((d) => d.n));
    return h('section', { class: 'hx-bk' }, h('h2', { class: 'hx-h', text: title }),
      h('ul', { class: 'hx-bars' }, data.slice(0, 12).map((d) => {
        const on = cur === d.k;
        const lbl = name(d.k) + ': ' + d.n + (d.c ? ' (' + SEVS.filter((k) => d.c[k]).map((k) => d.c[k] + ' ' + SEV_LABEL[k].toLowerCase()).join(', ') + ')' : '');
        return h('li', null, h('button', { type: 'button', class: 'hx-brow' + (on ? ' on' : ''), 'aria-pressed': String(on), 'aria-label': lbl + (on ? '. Selected, select again to clear' : '. Select to filter'),
          onclick: () => onPick(on ? '' : d.k) },
        h('span', { class: 'hx-bn', text: name(d.k) }),
        h('span', { class: 'hx-btrack' }, h('span', { class: 'hx-bfill', style: { width: ((d.n / mx) * 100).toFixed(1) + '%' } },
          d.c ? SEVS.filter((k) => d.c[k]).map((k) => h('i', { class: 'hx-f-' + k, style: { flexGrow: d.c[k] } })) : h('i', { class: 'hx-f-out', style: { flexGrow: 1 } }))),
        h('span', { class: 'hx-bv', text: d.n })));
      })));
  };
  const hist = (title, vals, edges) => {
    const lab = ['< 5 min', '5-15 min', '15-60 min', '1-4 h', '4-24 h', '> 1 day'];
    const c = new Array(lab.length).fill(0);
    for (const v of vals) { let i = edges.findIndex((e) => v < e); if (i < 0) i = lab.length - 1; c[i]++; }
    const mx = Math.max(1, ...c);
    return h('section', { class: 'hx-bk' }, h('h2', { class: 'hx-h' }, title, h('span', { class: 'hx-sub', text: vals.length ? ' median ' + dur(median(vals)) + ' of ' + vals.length : ' none yet' })),
      h('ul', { class: 'hx-bars' }, lab.map((l, i) => h('li', { class: 'hx-brow ro', 'aria-label': title + ' ' + l + ': ' + c[i] },
        h('span', { class: 'hx-bn', text: l }),
        h('span', { class: 'hx-btrack' }, h('span', { class: 'hx-bfill', style: { width: ((c[i] / mx) * 100).toFixed(1) + '%' } }, h('i', { class: 'hx-f-time', style: { flexGrow: 1 } }))),
        h('span', { class: 'hx-bv', text: c[i] })))));
  };
  const edges = [300, 900, 3600, 4 * 3600, 86400];
  fill(P, h('div', { class: 'hx-bkgrid' },
    group('By domain', sevSplit((x) => (x.domains && x.domains.length ? x.domains : ['unknown'])), roleName, (v) => { S.p.dom = v; changed(); }, S.p.dom),
    group('By building', sevSplit((x) => x.building || 'unknown'), (k) => (k === 'unknown' ? 'Unknown' : k), (v) => { S.p.bld = v; changed(); }, S.p.bld),
    group('By outcome', [...countBy(list, outcomeKey).entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ k, n })), outName, (v) => { S.p.out = v; changed(); }, S.p.out),
    hist('Time to acknowledge', list.filter((x) => x.ack_s > 0).map((x) => x.ack_s), edges),
    hist('Time to close', list.filter((x) => x.close_s > 0).map((x) => x.close_s), edges)), legend());
}

/* ---------- List: sortable table (cards on phones) ---------- */
const COLS = [
  { k: 't', t: 'Opened', v: (x) => x.t },
  { k: 'sev', t: 'Severity', v: (x) => SEV_RANK[x.sev] || 0 },
  { k: 'title', t: 'Incident', v: (x) => (x.title || '').toLowerCase() },
  { k: 'dom', t: 'Domain', v: (x) => (x.domains || []).map(roleName).join(',') },
  { k: 'bld', t: 'Where', v: (x) => (x.building || '~') + (x.floor || '') },
  { k: 'wf', t: 'State', v: (x) => (x.open ? 0 : 1) + (x.workflow || '') },
  { k: 'ack', t: 'Ack', v: (x) => x.ack_s || Infinity },
  { k: 'close', t: 'Close', v: (x) => x.close_s || Infinity },
  { k: 'ai', t: 'AI', v: (x) => x.ai_ms || Infinity },
];
function renderList(P, list) {
  const col = COLS.find((c) => c.k === S.p.sortK) || COLS[0], d = S.p.sortD === 1 ? 1 : -1;
  const sorted = list.slice().sort((a, b) => { const x = col.v(a), y = col.v(b); return (x < y ? -1 : x > y ? 1 : 0) * d || b.t - a.t; });
  const show = sorted.slice(0, S.shown);
  const open = (id) => { if (window.SCE_openIncident) window.SCE_openIncident(id); };
  const th = (c) => {
    const on = c.k === col.k;
    return h('th', { scope: 'col', class: 'hx-c-' + c.k, 'aria-sort': on ? (d === 1 ? 'ascending' : 'descending') : 'none' },
      h('button', { type: 'button', class: 'hx-sort' + (on ? ' on' : ''), onclick: () => {
        if (S.p.sortK === c.k) S.p.sortD = -S.p.sortD; else { S.p.sortK = c.k; S.p.sortD = c.k === 'title' || c.k === 'dom' || c.k === 'bld' ? 1 : -1; }
        save(); renderPanel();
      } }, c.t, h('span', { class: 'hx-arr', 'aria-hidden': 'true', text: on ? (d === 1 ? '↑' : '↓') : '' })));
  };
  const tr = (x) => h('tr', { class: 'hx-row', tabindex: '0', 'aria-label': 'Open incident ' + x.id + ': ' + x.title,
    onclick: () => open(x.id), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(x.id); } } },
  h('td', { class: 'hx-c-t' }, h('span', { class: 'hx-when', text: dmy(x.t) + ' ' + hm(x.t) }), x.clock_guess ? h('span', { class: 'hx-tag', title: 'Time from the sensor clock; the device clock was unknown', text: '~' }) : null),
  h('td', { class: 'hx-c-sev' }, h('span', { class: 'hx-pill hx-s-' + x.sev }, h('span', { 'aria-hidden': 'true', text: SEV_GLYPH[x.sev] || '▲' }), ' ', SEV_LABEL[x.sev] || nice(x.sev))),
  h('td', { class: 'hx-c-title' }, h('span', { class: 'hx-tt', text: x.title || x.id }),
    h('span', { class: 'hx-meta' }, h('span', { class: 'mono', text: x.id }),
      x.sensors && x.sensors.length ? h('span', { class: 'mono', text: x.sensors.slice(0, 2).join(', ') + (x.sensors.length > 2 ? ' +' + (x.sensors.length - 2) : '') }) : null,
      x.recurred ? h('span', { class: 'hx-tag warn', title: 'Closed, then the same sensor alarmed again within 7 days' + (x.recurred_by ? ' (' + x.recurred_by + ')' : ''), text: 'came back' }) : null,
      x.sensor_fault && x.sev !== 'sensor_fault' ? h('span', { class: 'hx-tag', text: 'sensor fault' }) : null,
      x.injected ? h('span', { class: 'hx-tag', title: 'Values were injected for a test', text: 'injected' }) : null,
      x.demo ? h('span', { class: 'hx-tag', text: 'demo' }) : null)),
  h('td', { class: 'hx-c-dom', text: (x.domains || []).map(roleName).join(', ') || '-' }),
  h('td', { class: 'hx-c-bld', text: x.building ? x.building + (x.floor ? ' · L' + x.floor : '') : '-', title: x.site || null }),
  h('td', { class: 'hx-c-wf' }, h('span', { class: 'hx-wf' + (x.open ? ' open' : ''), text: WF[x.workflow] || nice(x.workflow) }),
    x.outcome ? h('span', { class: 'hx-meta', text: outName(x.outcome) }) : null),
  h('td', { class: 'hx-c-ack', 'data-l': 'Ack', text: dur(x.ack_s) }),
  h('td', { class: 'hx-c-close', 'data-l': 'Close', text: dur(x.close_s) }),
  h('td', { class: 'hx-c-ai', 'data-l': 'AI', text: msTxt(x.ai_ms) }));
  fill(P, h('div', { class: 'hx-ph' }, h('h2', { class: 'hx-h', text: 'Incidents' }), h('span', { class: 'hx-sub', text: list.length + ' matching · select one to open it' })),
    h('div', { class: 'hx-tablewrap' }, h('table', { class: 'hx-table' },
      h('caption', { class: 'sr-only', text: 'Incidents in the ' + rangeWord() + ', sorted by ' + col.t + (d === 1 ? ' ascending' : ' descending') }),
      h('thead', null, h('tr', null, COLS.map(th))), h('tbody', null, show.map(tr)))),
    sorted.length > show.length ? h('div', { class: 'hx-more' }, h('button', { type: 'button', class: 'btn sm', text: 'Show ' + Math.min(PAGE, sorted.length - show.length) + ' more (' + (sorted.length - show.length) + ' left)',
      onclick: () => { S.shown += PAGE; renderPanel(); } })) : null);
}

/* ---------- side: top recurring sensors ---------- */
function renderSide() {
  const list = rows(), m = new Map();
  for (const x of list) for (const k of x.sensors || []) {
    if (!m.has(k)) m.set(k, { k, n: 0, rec: 0, last: 0, lastId: '', crit: 0 });
    const e = m.get(k); e.n++; if (x.recurred) e.rec++; if (x.sev === 'critical') e.crit++; if (x.t > e.last) { e.last = x.t; e.lastId = x.id; }
  }
  const top = [...m.values()].filter((e) => e.n >= 2 || e.rec).sort((a, b) => b.n - a.n || b.rec - a.rec || (a.k < b.k ? -1 : 1)).slice(0, 8);
  const mx = Math.max(1, ...top.map((e) => e.n));
  fill(S.el.side, h('h2', { class: 'hx-h', id: 'hx-top-h', text: 'Top recurring sensors' }),
    top.length ? h('ol', { class: 'hx-top' }, top.map((e) => h('li', null,
      h('button', { type: 'button', class: 'hx-topb', 'aria-label': e.k + ': ' + e.n + ' incidents' + (e.rec ? ', came back ' + e.rec + ' times after closing' : '') + ', last ' + dmyhm(e.last) + '. Select to search for it',
        onclick: () => { S.p.q = e.k; changed(); } },
      h('span', { class: 'hx-tn mono', text: e.k }),
      h('span', { class: 'hx-tbar' }, h('i', { class: e.crit ? 'hx-f-critical' : 'hx-f-warning', style: { width: ((e.n / mx) * 100).toFixed(1) + '%' } })),
      h('span', { class: 'hx-ts' }, h('b', { text: e.n + '×' }), e.rec ? h('span', { class: 'hx-tag warn', text: 'back ' + e.rec + '×' }) : null, h('span', { class: 'muted', text: 'last ' + dmy(e.last) }))),
      h('button', { type: 'button', class: 'hx-link', text: 'Open last (' + e.lastId + ')', onclick: () => { if (window.SCE_openIncident) window.SCE_openIncident(e.lastId); } }))))
      : h('p', { class: 'muted hx-pad', text: 'No sensor alarmed more than once in this view.' }));
}

/* ============================== public ============================== */
function mount(root) {
  if (!root) return;
  if (S.root !== root || !root.classList.contains('hx')) { load(); S.root = root; S.el = {}; build(root); }
  render();
  if (!S.data && !S.loading) fetchData();
}
function refresh() {
  if (!S.root || S.loading) return Promise.resolve(); // mount() is already fetching
  return fetchData();
}
window.SCE_history = { mount, refresh };
})();
