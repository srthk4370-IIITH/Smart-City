// Browser-free check of app.js domain-health rendering (healthModel + renderHealth + onIncChange).
// Usage: node ui_health_check.js <path to app.js>
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const a = src.indexOf('/* ----- domain health ----- */'), b = src.indexOf('/* ----- end domain health ----- */');
if (a < 0 || b < 0) { console.error('FAIL markers not found'); process.exit(1); }

// minimal DOM
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this._text = ''; this.parent = null; this.listeners = {}; }
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
const doc = { '#dh-grid': new El('div'), '#dh-sub': new El('span'), '#dh-live': new El('p'), '#dh-strip': new El('nav'), '#toasts': new El('div') };
doc['#dh-grid'].append(Object.assign(new El('div'), { attrs: { class: 'empty' } }));
const $ = (s, r) => (r ? r.find((c) => s === '.empty' && c.className === 'empty') : doc[s] || null);
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
const roleTitle = { air_quality: 'Air Quality', water: 'Water', power: 'Power', occupancy: 'Occupancy', weather: 'Weather', hvac: 'HVAC' };
const roleShort = { air_quality: 'Air', water: 'Water', power: 'Power', occupancy: 'Occupancy', weather: 'Weather', hvac: 'HVAC' };
const ROLE_ORDER = ['air_quality', 'water', 'power', 'occupancy', 'weather', 'hvac'];
const ROLE_COLOR = {};
const STATUS_GLYPH = { normal: '●', warning: '▲', critical: '■', sensor_fault: '◆', insufficient_data: '○', none: '○' };
const stClass = (s) => 'st-' + (s || 'none');
const SEV_LABEL = { critical: 'Critical', warning: 'Warning', normal: 'Fine', info: 'Fine', sensor_fault: 'Fault' };
const S = { health: null, simNow: 0, incs: [] };
let opened = [], toasts = [];
const selectIncident = (id) => opened.push(id);
const toast = (m) => toasts.push(m);
const api = async () => S.health;
eval(src.slice(a, b) + ';globalThis.T={healthModel,renderHealth,onIncChange,DH}');

const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exit(1); } };
const T0 = 1700000000;
const dom = (d, o) => Object.assign({ domain: d, headline: 'normal', status: 'normal', live_status: 'normal', sensor_faults: 0, counts: { normal: 2 }, sensors: 2,
  context_sensors: 0, trend: 'steady', since: T0 - 1800, fresh: true, incidents: [], steps: [] }, o || {});
const calm = () => ROLE_ORDER.map((d) => dom(d, d === 'hvac' ? { context_only: true, sensors: 0, context_sensors: 2, counts: {} } : null));

// 1. calm board
S.health = { sim_time: T0, worst: 'normal', domains: calm() };
T.renderHealth();
const grid = doc['#dh-grid'];
ok(grid.children.length === 6, 'six tiles, got ' + grid.children.length);
ok(!grid.find((c) => c.className === 'empty'), 'placeholder removed');
ok(grid.children[0].className.includes('calm') && !grid.children[0].className.includes('wide'), 'normal tile calm + compact: ' + grid.children[0].className);
ok(grid.children[0].textContent.includes('● Normal') && grid.children[0].textContent.includes('for 30 min'), 'glyph+word+time: ' + grid.children[0].textContent);
ok(grid.children[5].textContent.includes('Context only'), 'hvac context only: ' + grid.children[5].textContent);
ok(!grid.find((c) => c.tag === 'ol'), 'no steps when normal');
ok(grid.children.every((c) => c.getAttribute('tabindex') === '0'), 'tiles focusable');
ok(doc['#dh-sub'].textContent === 'All domains normal', 'sub ' + doc['#dh-sub'].textContent);
ok(doc['#dh-strip'].children.length === 6, 'strip chips');

// 2. water elevated to critical by a refinement, with AI steps and an open incident
const water = dom('water', { headline: 'critical', status: 'critical', live_status: 'warning', raised_by_ai: true, counts: { warning: 1, normal: 1 }, trend: 'elevated', trend_from: 'warning', since: T0 - 300,
  incidents: [{ id: 'INC-0007', severity: 'critical', refine_stage: '1.5h', change: 'elevated', title: 'Tank level step decrease', state: 'done' }],
  steps: [{ text: 'Inspect the water system: tank, pumps, valves and pipes for leaks', action: 'inspect_water_system', source: 'report', incident: 'INC-0007' }] });
const power = dom('power', { headline: 'sensor_fault', sensor_faults: 1, counts: { sensor_fault: 1, normal: 1 }, fresh: false, stale: ['P1 power_kw'],
  steps: [{ text: 'Check the faulty sensor on site (power, wiring, mounting)', source: 'playbook' }] });
S.health = { sim_time: T0, worst: 'critical', domains: calm().map((d) => (d.domain === 'water' ? water : d.domain === 'power' ? power : d)) };
T.renderHealth();
const wt = grid.children[1], pt = grid.children[2];
ok(wt.className.includes('st-critical') && wt.className.includes('wide'), 'water tile class ' + wt.className);
const wtxt = wt.textContent;
ok(wtxt.includes('■ Critical') && wtxt.includes('↑ Elevated from Warning') && wtxt.includes('for 5 min'), 'water text: ' + wtxt);
ok(wtxt.includes('Raised to Critical by the AI review (live readings: Warning)'), 'AI raise note');
ok(wtxt.includes('INC-0007 · Critical · refined 1.5 h ↑'), 'incident chip: ' + wtxt);
ok(wtxt.includes('needs operator approval'), 'approval wording');
const btn = wt.find((c) => c.tag === 'button');
btn.listeners.click({ stopPropagation() {} });
ok(opened[0] === 'INC-0007', 'incident link opens it');
ok(/Water: Critical\. Elevated from Warning/.test(wt.getAttribute('aria-label')), 'aria label ' + wt.getAttribute('aria-label'));
ok(doc['#dh-live'].textContent.includes('Water elevated to Critical'), 'aria-live: ' + doc['#dh-live'].textContent);
const ptxt = pt.textContent;
ok(ptxt.includes('◆ Sensor fault') && ptxt.includes('Data stale or warming up: 1 sensor') && ptxt.includes('Standard playbook'), 'power fault: ' + ptxt);
ok(doc['#dh-sub'].textContent === 'Worst: Critical', 'worst');
const chip = doc['#dh-strip'].children[1];
ok(chip.textContent.includes('■') && chip.textContent.includes('↑') && chip.getAttribute('href') === '#live', 'strip chip ' + chip.textContent);

// 3. tick moves time-in-state without rebuilding the tile body
const body = wt.children[2], kidsBefore = body.children.slice();
S.simNow = T0 + 3600; T.renderHealth();
ok(wt.textContent.includes('for 1 h 5 min'), 'time in state advances: ' + wt.textContent);
ok(body.children.every((c, i) => c === kidsBefore[i]), 'body not rebuilt on tick');

// 4. refinement toasts
S.incs = [{ id: 'INC-0007', severity: 'critical', roles: ['water'] }, { id: 'INC-0008', severity: 'normal', roles: ['air_quality'] }];
T.onIncChange({ id: 'INC-0007', change: 'elevated', refined: '1.5h' });
const tt = doc['#toasts'].children[0];
ok(tt && tt.getAttribute('role') === 'alert' && tt.textContent.includes('INC-0007 elevated to Critical at the 1.5 h refinement · Water'), 'elevated toast ' + (tt && tt.textContent));
tt.find((c) => c.tag === 'button').listeners.click();
ok(opened[1] === 'INC-0007' && !doc['#toasts'].children.length, 'toast opens incident');
T.onIncChange({ id: 'INC-0008', change: 'curbed', refined: '3h' });
ok(toasts[0] === '↓ INC-0008 curbed to Fine at the 3 h refinement', 'curbed note ' + toasts[0]);

// 5. curbed domain
S.health.domains[1] = dom('water', { headline: 'warning', status: 'warning', live_status: 'warning', counts: { warning: 1, normal: 1 }, trend: 'curbed', trend_from: 'critical',
  steps: [{ text: 'Check the tank level against the pump schedule', source: 'playbook' }] });
T.renderHealth();
ok(grid.children[1].textContent.includes('↓ Curbed from Critical') && doc['#dh-live'].textContent.includes('Water curbed to Warning'), 'curbed tile');
console.log('ui health check: OK (' + 5 + ' scenarios)');
setTimeout(() => process.exit(0), 0); // pending toast timers
