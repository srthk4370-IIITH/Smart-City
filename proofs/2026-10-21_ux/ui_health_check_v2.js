// Browser-free check of the redesigned campus-health panel + plain-language helpers in app.js
// (healthModel, renderHealth, renderDomainSheet, onIncChange, plainTitle, placeShort, stripRefs, confWord).
// Usage: node ui_health_check_v2.js <path to app.js>
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const a = src.indexOf('/* ----- plain language ----- */'), b = src.indexOf('/* ----- end domain health ----- */');
if (a < 0 || b < 0) { console.error('FAIL markers not found'); process.exit(1); }

// minimal DOM
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this._text = ''; this.parent = null; this.listeners = {}; this.scrollTop = 0; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(s) { this.children = []; this._text = String(s); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  append(...k) { for (const c of k) { const e = typeof c === 'string' ? Object.assign(new El('#text'), { _text: c }) : c; if (e.parent) e.remove(); e.parent = this; this.children.push(e); } }
  replaceChildren(...k) { this.children.forEach((c) => { c.parent = null; }); this.children = []; this._text = ''; this.append(...k); }
  insertBefore(n, ref) { if (n.parent) n.remove(); const i = ref ? this.children.indexOf(ref) : -1; n.parent = this; if (i < 0) this.children.push(n); else this.children.splice(i, 0, n); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; } }
  addEventListener(t, f) { this.listeners[t] = f; }
  get className() { return this.attrs.class || ''; }
  find(pred) { for (const c of this.children) { if (pred(c)) return c; const r = c.find(pred); if (r) return r; } return null; }
  all(pred, out = []) { for (const c of this.children) { if (pred(c)) out.push(c); c.all(pred, out); } return out; }
}
const ids = ['#dh-grid', '#dh-sub', '#dh-live', '#dh-strip', '#toasts', '#dh-conn', '#dh-dec', '#dsheet-t', '#dsheet-bd'];
const doc = {}; ids.forEach((k) => { doc[k] = new El(k); });
doc['#dh-grid'].append(Object.assign(new El('div'), { attrs: { class: 'empty' } }));
const hasCls = (c, k) => (' ' + c.className + ' ').includes(' ' + k + ' ');
const $ = (s, r) => { if (doc[s]) return doc[s]; if (s[0] === '.' && r) return r.find((c) => hasCls(c, s.slice(1))); if (s[0] === '.' && s === '.empty') return null; return null; };
const $$ = () => [];
function h(tag, at, ...kids) {
  const e = new El(tag);
  if (at) for (const k in at) { const v = at[k]; if (v == null || v === false) continue; if (k === 'text') e._text = String(v); else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v); }
  for (const c of kids.flat(3)) { if (c == null || c === false) continue; e.append(typeof c === 'object' ? c : String(c)); }
  return e;
}
const fill = (el, ...k) => el.replaceChildren(...k.flat(3).filter((x) => x != null && x !== false));
const setText = (e, s) => { s = String(s); if (e.textContent !== s) e.textContent = s; };
const setCls = (e, c) => e.setAttribute('class', c);
const setAttr = (e, k, v) => e.setAttribute(k, v);
const icon = (n) => h('svg', { 'data-i': n });
const nice = (s) => (s == null || s === '' ? '-' : String(s).replace(/_/g, ' '));
const pad = (n) => String(n).padStart(2, '0');
const hm = (e) => { const d = new Date((e + 19800) * 1000); return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); };
const dhm = (e) => hm(e);
const fmt = (v) => (typeof v === 'number' ? v.toFixed(1) : '-');
const roleTitle = { air_quality: 'Air Quality', water: 'Water', power: 'Power', occupancy: 'Occupancy', weather: 'Weather', hvac: 'HVAC' };
const roleShort = { air_quality: 'Air', water: 'Water', power: 'Power', occupancy: 'Occupancy', weather: 'Weather', hvac: 'HVAC' };
const ROLE_ORDER = ['air_quality', 'water', 'power', 'occupancy', 'weather', 'hvac'];
const STATUS_GLYPH = { normal: '●', warning: '▲', critical: '■', sensor_fault: '◆', insufficient_data: '○', none: '○' };
const STATUS_LABEL = { normal: 'Normal', warning: 'Warning', critical: 'Critical', sensor_fault: 'Sensor fault', insufficient_data: 'Not enough data' };
const stClass = (s) => 'st-' + (s || 'none');
const SEV_LABEL = { critical: 'Critical', warning: 'Warning', normal: 'Fine', info: 'Fine', sensor_fault: 'Fault' };
const S = { health: null, simNow: 0, incs: [], live: null, eng: false, sse: true, lastStatus: Date.now(), lastLiveEv: 0, lastHealth: 0 };
let opened = [], toasts = [], sheets = [], sensorsOpened = [];
const selectIncident = (id) => opened.push(id);
const openSheet = (id) => sheets.push(id);
const openSensor = (n, m) => sensorsOpened.push(n + ' ' + m);
const toast = (m) => toasts.push(m);
const api = async () => S.health;
eval(src.slice(a, b) + ';globalThis.T={healthModel,renderHealth,onIncChange,DH,openDomain,plainTitle,placeShort,stripRefs,confWord,sensorLabel}');

const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exit(1); } };
let n = 0; const scen = (f) => { f(); n++; };

// 0. plain-language helpers
scen(() => {
  ok(T.placeShort('KH building, level 98, water tank level sensor 00') === 'KH-98 tank', 'place tank ' + T.placeShort('KH building, level 98, water tank level sensor 00'));
  ok(T.placeShort('KN building, outdoor air station') === 'KN outdoor', 'place outdoor');
  ok(T.placeShort('SB00 substation, 11 kV feeder meter') === 'SB00 substation', 'place substation');
  ok(T.placeShort('KH building, room occupancy sensor 01 (gateway KH95)') === 'KH room 01', 'place room');
  ok(T.placeShort('KH building, level 03, AC indoor unit 15') === 'KH-03 AC unit 15', 'place AC unit');
  ok(T.plainTitle('Tank level gradual decrease: KH building, level 98, water tank level sensor 00') === 'Tank level falling steadily · KH-98 tank', 'title ' + T.plainTitle('Tank level gradual decrease: KH building, level 98, water tank level sensor 00'));
  ok(T.plainTitle('Power throttling: KH building, level 04, room energy meter 01') === 'Power flattened at a cap · KH-04 room 01', 'title power');
  ok(T.plainTitle(' judged normal: KH building, level 02, AC indoor unit 24') === 'Sensor checked: normal · KH-02 AC unit 24', 'title empty metric');
  ok(T.plainTitle('3 sensors alarming: CO2, Power, Occupancy') === '3 sensors need attention: CO2, Power, Occupancy', 'multi');
  ok(T.plainTitle('Model wrote its own headline') === 'Model wrote its own headline', 'passthrough');
  ok(T.stripRefs('Level 305 past the high mark [E2] (from domain agent finding). Flow stable (S2), ok [S1.E9, S2.E1]') === 'Level 305 past the high mark. Flow stable, ok', 'strip ' + T.stripRefs('Level 305 past the high mark [E2] (from domain agent finding). Flow stable (S2), ok [S1.E9, S2.E1]'));
  ok(T.confWord(0.84).w === 'High' && T.confWord(0.66).w === 'Medium' && T.confWord(0.3).w === 'Low' && T.confWord(null).w === 'Unknown', 'confidence words');
});

const T0 = 1700000000;
const dom = (d, o) => Object.assign({ domain: d, headline: 'normal', status: 'normal', live_status: 'normal', sensor_faults: 0, counts: { normal: 2 }, sensors: 2,
  context_sensors: 0, trend: 'steady', since: T0 - 1800, fresh: true, incidents: [], steps: [] }, o || {});
const calm = () => ROLE_ORDER.map((d) => dom(d, d === 'hvac' ? { context_only: true, sensors: 0, context_sensors: 2, counts: {} } : null));
const grid = doc['#dh-grid'];
const tileOf = (d) => T.DH.tiles[d].root;

// 1. calm board: six grey tiles, fixed order, plain words, no steps
scen(() => {
  S.health = { sim_time: T0, worst: 'normal', domains: calm() };
  T.renderHealth();
  ok(grid.children.length === 6, 'six tiles, got ' + grid.children.length);
  ok(!grid.find((c) => c.className === 'empty'), 'placeholder removed');
  ok(grid.children[0] === tileOf('air_quality') && grid.children[5] === tileOf('hvac'), 'calm order = domain order');
  const t0 = tileOf('air_quality');
  ok(t0.tag === 'button' && t0.className.includes('calm') && !t0.className.includes('wide'), 'calm tile is a compact button: ' + t0.className);
  ok(t0.textContent.includes('●Normal') && t0.textContent.includes('All 2 sensors normal') && !t0.textContent.includes('Do now'), 'calm text: ' + t0.textContent);
  ok(tileOf('hvac').textContent.includes('Info only'), 'hvac context only: ' + tileOf('hvac').textContent);
  ok(doc['#dh-sub'].textContent === 'All 6 areas normal', 'sub ' + doc['#dh-sub'].textContent);
  ok(doc['#dh-strip'].children.length === 6 && doc['#dh-strip'].children[0].tag === 'button', 'strip chips are buttons');
  ok(doc['#dh-conn'].textContent === '● Live', 'connection: ' + doc['#dh-conn'].textContent);
});

// 2. water elevated to critical (AI raise, open incident, AI steps) + power sensor fault: worst first
const water = dom('water', { headline: 'critical', status: 'critical', live_status: 'warning', raised_by_ai: true, counts: { warning: 1, normal: 1 }, trend: 'elevated', trend_from: 'warning', since: T0 - 300,
  incidents: [{ id: 'INC-0007', severity: 'critical', refine_stage: '1.5h', change: 'elevated', title: 'Tank level gradual decrease: KH building, level 98, water tank level sensor 00', state: 'done' }],
  steps: [{ text: 'Inspect the water system: tank, pumps, valves and pipes for leaks', action: 'inspect_water_system', source: 'report', incident: 'INC-0007' }] });
const power = dom('power', { headline: 'sensor_fault', sensor_faults: 1, counts: { sensor_fault: 1, normal: 1 }, fresh: false, stale: ['P1 power_kw'],
  steps: [{ text: 'Check the faulty sensor on site (power, wiring, mounting)', source: 'playbook' }] });
scen(() => {
  S.incs = [{ id: 'INC-0007', approval: 'pending', state: 'done' }, { id: 'INC-0001', approval: 'pending', state: 'done' }, { id: 'INC-0002', approval: 'approved', state: 'done' }];
  S.health = { sim_time: T0, worst: 'critical', domains: calm().map((d) => (d.domain === 'water' ? water : d.domain === 'power' ? power : d)) };
  T.renderHealth();
  const wt = tileOf('water'), pt = tileOf('power');
  ok(grid.children[0] === wt && grid.children[1] === pt && grid.children[2] === tileOf('air_quality'), 'worst first: ' + grid.children.map((c) => c.getAttribute('aria-label').split(':')[0]).join(','));
  ok(wt.className.includes('st-critical') && wt.className.includes('wide') && !wt.className.includes('calm'), 'water tile class ' + wt.className);
  const w = wt.textContent;
  ok(w.includes('■Critical') && w.includes('↑ Got worse (was Warning)') && w.includes('since ') && w.includes('(5 min)'), 'water text: ' + w);
  ok(w.includes('Do now: Inspect the water system') && w.includes('1 open incident'), 'do now + incident count: ' + w);
  ok(/^Water: Critical, act now\. Got worse \(was Warning\)/.test(wt.getAttribute('aria-label')), 'aria ' + wt.getAttribute('aria-label'));
  ok(doc['#dh-live'].textContent.includes('Water got worse: Critical'), 'aria-live: ' + doc['#dh-live'].textContent);
  const p = pt.textContent;
  ok(p.includes('◆Sensor problem') && p.includes('1 sensor is not reporting fresh readings') && p.includes('Do now: Check the faulty sensor'), 'power fault: ' + p);
  ok(doc['#dh-sub'].textContent === '2 of 6 areas need attention: Water (critical), Power (sensor problem)', 'sub ' + doc['#dh-sub'].textContent);
  ok(doc['#dh-dec'].textContent === '2 decisions waiting ›' && doc['#dh-dec'].hidden === false, 'decisions link ' + doc['#dh-dec'].textContent);
  const chip = doc['#dh-strip'].children[0];
  ok(chip.textContent.includes('■') && chip.textContent.includes('↑'), 'strip chip worst first ' + chip.textContent);
  // tap -> domain sheet (Level 2)
  wt.listeners.click();
  ok(sheets[0] === 'dsheet' && T.DH.open === 'water', 'tile opens the domain sheet');
  const bd = doc['#dsheet-bd'].textContent;
  ok(doc['#dsheet-t'].textContent === 'Water' && bd.includes('What to do now') && bd.includes('Open incidents (1)') && bd.includes('Tank level falling steadily · KH-98 tank') && bd.includes('Technical details'), 'domain sheet: ' + bd.slice(0, 400));
  const ib = doc['#dsheet-bd'].find((c) => c.tag === 'button' && /Open incident INC-0007/.test(c.getAttribute('aria-label') || ''));
  ib.listeners.click();
  ok(opened[0] === 'INC-0007', 'incident link in the domain sheet opens it');
});

// 3. tick moves time-in-state without rebuilding the tile body
scen(() => {
  const wt = tileOf('water'), kids = wt.children.slice();
  S.simNow = T0 + 3600; T.renderHealth();
  ok(wt.textContent.includes('(1 h 5 min)'), 'time in state advances: ' + wt.textContent);
  ok(wt.children.every((c, i) => c === kids[i]), 'tile body not rebuilt on tick');
});

// 4. refinement toasts in plain words
scen(() => {
  S.incs = [{ id: 'INC-0007', severity: 'critical', roles: ['water'] }, { id: 'INC-0008', severity: 'normal', roles: ['air_quality'] }];
  T.onIncChange({ id: 'INC-0007', change: 'elevated', refined: '1.5h' });
  const tt = doc['#toasts'].children[0];
  ok(tt && tt.getAttribute('role') === 'alert' && tt.textContent.includes('INC-0007 got worse: now Critical at the 1.5 h re-check · Water'), 'elevated toast ' + (tt && tt.textContent));
  tt.find((c) => c.tag === 'button').listeners.click();
  ok(opened[1] === 'INC-0007' && !doc['#toasts'].children.length, 'toast opens incident');
  T.onIncChange({ id: 'INC-0008', change: 'curbed', refined: '3h' });
  ok(toasts[0] === '↓ INC-0008 improved: now Fine at the 3 h re-check', 'curbed note ' + toasts[0]);
});

// 5. curbed domain, and back to normal (resolved)
scen(() => {
  S.health.domains[1] = dom('water', { headline: 'warning', status: 'warning', live_status: 'warning', counts: { warning: 1, normal: 1 }, trend: 'curbed', trend_from: 'critical',
    steps: [{ text: 'Check the tank level against the pump schedule', source: 'playbook' }] });
  T.renderHealth();
  ok(tileOf('water').textContent.includes('↓ Improving (was Critical)') && doc['#dh-live'].textContent.includes('Water improved to Warning'), 'curbed tile: ' + tileOf('water').textContent);
  S.health.domains[1] = dom('water', { trend: 'curbed', trend_from: 'warning' });
  T.renderHealth();
  ok(tileOf('water').textContent.includes('✓ Back to normal (was Warning)') && tileOf('water').className.includes('calm'), 'resolved tile: ' + tileOf('water').textContent);
});

// 5b. an abnormal domain whose incident is older than the open window still shows the decision owed
scen(() => {
  S.incs = [{ id: 'INC-0053', approval: 'pending', state: 'done', roles: ['air_quality'], severity: 'critical', title: 'CO2 throttling: KH building, level 03, indoor air sensor 03', created_sim_ist: 'Tue 15:50' }];
  S.health.domains[0] = dom('air_quality', { headline: 'critical', status: 'critical', live_status: 'critical', counts: { critical: 1, normal: 4 }, sensors: 5,
    steps: [{ text: 'Ask facilities to ventilate the room now (dampers, AHU, windows)', source: 'playbook' }] });
  T.renderHealth();
  ok(tileOf('air_quality').textContent.includes('1 awaiting decision'), 'older pending on tile: ' + tileOf('air_quality').textContent);
  T.openDomain('air_quality');
  const bd = doc['#dsheet-bd'].textContent;
  ok(bd.includes('Earlier, still awaiting your decision (1)') && bd.includes('CO2 flattened at a cap · KH-03') && !bd.includes('No incident yet'), 'domain sheet older: ' + bd.slice(0, 500));
});
// 6. disconnected: the panel says it is not updating
scen(() => {
  S.sse = false; T.renderHealth();
  ok(doc['#dh-conn'].textContent === '○ Not updating' && doc['#dh-conn'].className.includes('off'), 'offline indicator ' + doc['#dh-conn'].textContent);
});
console.log('ui health check v2: OK (' + n + ' scenarios)');
setTimeout(() => process.exit(0), 0); // pending toast timers
