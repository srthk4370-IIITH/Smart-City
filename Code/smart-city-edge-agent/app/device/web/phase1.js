/* Phase 1 UI (proofs/2026-11-16_phase1/README.md): no-network page, data-health panel, daily summary, export,
   site map (campus x,y from the API) + tree picker (parent, links) + full spec-card editor. Uses app.js helpers
   (h, api, post, toast, icon). Writes go to /api/site*, guarded by the backend like every other write. */
(function () {
  'use strict';
  const { h, api, post, toast } = window.SCE_H || {};
  const P = { site: null, status: null, cards: null, sel: null, dirty: false, nonetHidden: false, timer: 0, view: '' };
  const $id = (x) => document.getElementById(x);
  const put = (path, body) => api(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const ageTxt = (s) => (s == null ? '-' : s < 90 ? s + ' s' : s < 5400 ? Math.round(s / 60) + ' min' : (s / 3600).toFixed(1) + ' h');
  const STC = { normal: 'var(--green,#34c759)', warning: 'var(--orange,#ff9500)', critical: 'var(--red,#ff3b30)', data_issue: 'var(--tx2)' };

  /* ---------------- no-network page ---------------- */
  async function netTick() {
    let st;
    try { st = await api('/api/campus/status'); } catch (e) { return; } // backend itself down: app.js shows that
    const box = $id('nonet'); if (!box || !st.campus_enabled) { if (box) box.hidden = true; return; }
    if (!st.offline) { P.nonetHidden = false; box.hidden = true; document.body.classList.remove('p1-offline'); return; }
    document.body.classList.add('p1-offline');
    const c = st.campus || {};
    $id('nonet-age').textContent = c.last_data_age_s != null ? 'Last data ' + ageTxt(c.last_data_age_s) + ' ago' + (c.last_data_utc ? ' (' + new Date(c.last_data_utc).toLocaleString() + ')' : '') : 'No data received yet.';
    const tt = $id('nonet-t'); if (tt) tt.textContent = 'No data available';
    $id('nonet-why').textContent = 'The campus sensor API' + (st.mqtt ? ' and the MQTT broker' : '') + ' cannot be reached, so no new readings are arriving. Option 1: Wi-Fi - connect this device to the campus Wi-Fi (direct link, preferred). Option 2: USB cable - plug the data cable into the laptop that relays the API (adb reverse); the app switches over by itself, and back to Wi-Fi when it returns.' + (c.last_error ? ' (' + c.last_error.slice(0, 90) + ')' : '');
    box.hidden = P.nonetHidden;
  }
  function netInit() {
    const w = $id('nonet-wifi'), x = $id('nonet-hide');
    if (w) w.onclick = () => { if (window.SCE && window.SCE.wifi) window.SCE.wifi(); else toast('Open Settings > Network > Wi-Fi on the device', true); };
    if (x) x.onclick = () => { P.nonetHidden = true; $id('nonet').hidden = true; };
    netTick(); setInterval(netTick, 10000);
  }

  /* ---------------- data health ---------------- */
  async function renderHealth() {
    const box = $id('health'); if (!box) return;
    try { await renderHealth0(box); } catch (e) { box.replaceChildren(h('div', { class: 'empty', text: 'Health view error: ' + (e && e.message || e) })); }
  }
  async function renderHealth0(box) {
    let d, daily;
    try { [d, daily] = await Promise.all([api('/api/health/data'), api('/api/daily').catch(() => null)]); } catch (e) { box.replaceChildren(h('div', { class: 'empty', text: 'Health data unavailable: ' + e.message })); return; }
    const c = d.campus || {}, m = d.mqtt || {};
    const link = (name, on, en, extra) => h('div', { class: 'p1-link' }, h('span', { class: 'p1-dot', style: 'background:' + (!en ? 'var(--tx2)' : on ? STC.normal : STC.critical) }),
      h('b', { text: name }), h('span', { class: 'muted', text: !en ? 'off' : (on ? 'connected' : 'unreachable') + (extra ? ' · ' + extra : '') }));
    const cn = d.counts || {};
    const rows = (d.sensors || []).map((s) => h('tr', { class: 'p1-' + s.state },
      h('td', {}, h('b', { text: s.node }), h('div', { class: 'muted', text: s.metric + ' · ' + s.role })),
      h('td', {}, h('span', { class: 'p1-badge p1-' + s.state, text: s.state })),
      h('td', { text: ageTxt(s.age_s) }),
      h('td', { class: 'muted', text: (s.quality || '') + (s.quality_reason ? ' - ' + s.quality_reason : '') })));
    const dl = (fmt) => h('a', { class: 'btn', href: '/api/incidents/export?format=' + fmt, download: '' }, 'Export ' + fmt.toUpperCase());
    const days = (daily && daily.days) || [];
    const mk = h('button', { class: 'btn', type: 'button', onclick: async (ev) => {
      ev.target.disabled = true; toast('Writing yesterday\'s summary on the NPU ...');
      try { await post('/api/daily/run'); renderHealth(); } catch (e) { toast('Daily summary: ' + e.message, true); } finally { ev.target.disabled = false; }
    } }, 'Summarise yesterday');
    box.replaceChildren(
      h('div', { class: 'card p1-card' }, h('h3', { text: 'Input links' }),
        link('Campus API', c.online, c.enabled, c.enabled ? 'via ' + (c.link_label || 'none') + ' · ' + (c.last_data_age_s != null ? 'newest reading ' + ageTxt(c.last_data_age_s) + ' old' : 'no data yet') + (c.backfill ? ' · backfill ' + c.backfill : '') : ''),
        link('MQTT broker', m.connected, m.enabled !== false, m.last_message_age_s != null ? 'last message ' + ageTxt(m.last_message_age_s) + ' ago' : ''),
        h('p', { class: 'muted', text: (cn.fresh || 0) + ' fresh · ' + (cn.stale || 0) + ' stale (no reading for ' + Math.round((d.stale_after_s || 0) / 60) + ' min) · ' + (cn.missing || 0) + ' missing' })),
      h('div', { class: 'card p1-card' }, h('h3', { text: 'Sensors' }), h('div', { class: 'p1-scroll' }, h('table', { class: 'p1-tab' },
        h('thead', {}, h('tr', {}, h('th', { text: 'Sensor' }), h('th', { text: 'State' }), h('th', { text: 'Last seen' }), h('th', { text: 'Quality' }))), h('tbody', {}, rows)))),
      h('div', { class: 'card p1-card' }, h('h3', { text: 'Daily summary' }),
        h('p', { class: 'muted', text: daily ? (daily.enabled ? 'Made every morning from the stored incidents.' : 'Automatic summary off (daily_summary=1 turns it on).') + ' Today so far: ' + (daily.today_digest || '') : '' }),
        ...days.slice(0, 7).map((x) => h('details', { class: 'p1-day' }, h('summary', { text: x.date + ' · ' + x.incidents + ' incidents' }),
          h('p', { text: x.ai || x.ai_error || '(no AI text)' }), h('p', { class: 'muted', text: x.digest }))),
        h('div', { class: 'sn-btns' }, mk)),
      h('div', { class: 'card p1-card' }, h('h3', { text: 'Incident export' }), h('p', { class: 'muted', text: 'Every stored incident with severity, title, sensors, site scope, group, label and root cause.' }),
        h('div', { class: 'sn-btns' }, dl('csv'), dl('json'))));
  }

  /* ---------------- site: map + tree + editor ---------------- */
  const KINDS = ['campus', 'building', 'wing', 'floor', 'room', 'zone', 'equipment', 'sensor'];
  const LINKS = ['serves', 'supplies', 'feeds', 'outdoor-for', 'upstream-of', 'downstream-of'];
  const ETYPES = ['ac_unit', 'ahu', 'chiller', 'panel', 'feeder', 'pump', 'tank', 'valve', 'meter', 'weather_station', 'generator', 'gateway', 'camera'];
  const byId = () => { const m = new Map(); (P.site.nodes || []).forEach((n) => m.set(n.id, n)); return m; };
  const kids = (id) => P.site.nodes.filter((n) => n.parent === id);
  function nodeStatus(id) {
    const st = P.status || {}; const n = byId().get(id);
    if (n && n.kind === 'sensor') return (st.sensors || {})[id] || 'normal';
    return ((st.rollup || {})[id] || {}).status || 'normal';
  }
  async function loadSite() {
    let [site, status, cards] = await Promise.all([api('/api/site'), api('/api/site/status').catch(() => null), P.cards ? Promise.resolve(P.cards) : api('/api/cards')]);
    if (!site || typeof site !== 'object') throw new Error('empty site');
    site.nodes = Array.isArray(site.nodes) ? site.nodes : []; site.links = Array.isArray(site.links) ? site.links : []; site.cards = site.cards || {};
    cards = cards || {}; cards.existing = cards.existing || {}; cards.faults = cards.faults || []; cards.actions = cards.actions || []; cards.kinds = cards.kinds || []; cards.domains = cards.domains || {};
    P.site = site; P.status = status; P.cards = cards; P.dirty = false;
  }
  function sel(opts, val, on) {
    const s = h('select', { class: 'sel' }, opts.map((o) => h('option', { value: o, text: o || '(none)', selected: o === val })));
    s.onchange = () => on(s.value); return s;
  }
  function inp(val, on, type) {
    const i = h('input', { class: 'note-in', type: type || 'text', value: val == null ? '' : val });
    i.onchange = () => on(type === 'number' ? (i.value === '' ? null : +i.value) : i.value); return i;
  }
  function field(label, el) { return h('label', { class: 'p1-f' }, h('span', { text: label }), el); }

  function renderMap(box) {
    const pts = P.site.nodes.filter((n) => n.xy && n.xy.length === 2 && n.kind !== 'sensor');
    if (!pts.length) { box.append(h('p', { class: 'muted', text: 'No x,y positions in the API registry yet.' })); return; }
    const xs = pts.map((n) => n.xy[0]), ys = pts.map((n) => n.xy[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const W = 1000, H = 640, pad = 30, sx = (x) => pad + (x - x0) / Math.max(1, x1 - x0) * (W - 2 * pad), sy = (y) => pad + (y - y0) / Math.max(1, y1 - y0) * (H - 2 * pad);
    const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('class', 'p1-map'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Campus map');
    const seen = new Map();
    for (const n of pts) {
      const k = Math.round(n.xy[0]) + ',' + Math.round(n.xy[1]); const j = seen.get(k) || 0; seen.set(k, j + 1);
      const c = document.createElementNS(NS, 'circle');
      const ang = j * 2.4, r0 = j ? 6 + j * 1.5 : 0;
      c.setAttribute('cx', sx(n.xy[0]) + r0 * Math.cos(ang)); c.setAttribute('cy', sy(n.xy[1]) + r0 * Math.sin(ang));
      const st = nodeStatus(n.id), mon = P.site.nodes.some((s) => s.parent === n.id && s.kind === 'sensor');
      c.setAttribute('r', mon ? 9 : 5); c.setAttribute('fill', STC[st] || STC.normal); c.setAttribute('opacity', mon ? '1' : '.45');
      c.setAttribute('stroke', P.sel === n.id ? 'var(--accent)' : 'none'); c.setAttribute('stroke-width', '4'); c.style.cursor = 'pointer';
      const t = document.createElementNS(NS, 'title'); t.textContent = (n.name || n.id) + ' · ' + st; c.append(t);
      c.addEventListener('click', () => { P.sel = n.id; renderSite(); });
      svg.append(c);
    }
    box.append(h('div', { class: 'card p1-card' }, h('h3', { text: 'Campus map' }), svg,
      h('p', { class: 'muted', text: 'Positions from the campus API (xcor, ycor). Big dots carry monitored sensors; colour = worst status below. Tap a dot to edit it.' })));
  }

  function treeNode(n, depth) {
    const ch = kids(n.id), st = nodeStatus(n.id);
    const lab = h('span', { class: 'p1-tn' + (P.sel === n.id ? ' on' : '') }, h('i', { class: 'p1-dot', style: 'background:' + (STC[st] || STC.normal) }),
      h('span', { text: (n.name || n.id) + (n.kind === 'sensor' ? '' : ' (' + (n.etype || n.kind) + ')') + (n.inferred ? ' *' : '') }));
    lab.onclick = (e) => { e.preventDefault(); P.sel = n.id; renderSite(); };
    if (!ch.length) return h('div', { class: 'p1-leaf' }, lab);
    lab.append(h('span', { class: 'p1-cnt', text: String(ch.length) }));
    const d = h('details', { open: depth < 1 || openPath().has(n.id) }, h('summary', {}, lab), h('div', { class: 'p1-kids' }, ch.map((c) => treeNode(c, depth + 1))));
    return d;
  }
  function openPath() { const s = new Set(), m = byId(); let x = m.get(P.sel); while (x && x.parent) { s.add(x.parent); x = m.get(x.parent); } return s; }

  function editor(box) {
    const m = byId(), n = m.get(P.sel);
    if (!n) { box.append(h('div', { class: 'card p1-card' }, h('p', { class: 'muted', text: 'Pick a node on the map or in the tree to edit it. * = relation inferred by a rule (check it).' }))); return; }
    const mark = () => { P.dirty = true; $id('p1-save').disabled = false; };
    const set = (k) => (v) => { n[k] = v; if (k === 'parent' || k === 'name') renderSite(); mark(); };
    const ids = P.site.nodes.filter((x) => x.kind !== 'sensor' && x.id !== n.id).map((x) => x.id);
    const links = (P.site.links || []).filter((l) => l.from === n.id || l.to === n.id);
    const lt = sel(LINKS, 'serves', () => {}), to = sel(P.site.nodes.filter((x) => x.kind !== 'sensor' && x.id !== n.id).map((x) => x.id), '', () => {});
    const card = h('div', { class: 'card p1-card' }, h('h3', { text: (n.name || n.id) }),
      h('p', { class: 'muted', text: n.id + ' · ' + n.kind + (n.api_type ? ' · API type ' + n.api_type : '') + (n.why ? ' · ' + n.why : '') + ' · status ' + nodeStatus(n.id) }),
      h('div', { class: 'p1-grid' },
        field('Name', inp(n.name, set('name'))),
        n.kind === 'campus' ? null : field('Parent', sel(ids, n.parent, set('parent'))),
        field('Kind', sel(KINDS, n.kind, set('kind'))),
        n.kind === 'equipment' ? field('Equipment type', sel(ETYPES, n.etype, set('etype'))) : null,
        n.kind === 'room' || n.kind === 'zone' ? field('Use', sel(['', 'lecture_hall', 'office', 'lab', 'hostel_room', 'corridor', 'plant_room', 'library', 'canteen', 'server_room', 'meeting_room', 'outdoor_area'], n.use || '', set('use'))) : null,
        n.kind === 'room' || n.kind === 'zone' ? field('Capacity', inp(n.capacity, set('capacity'), 'number')) : null,
        n.kind === 'sensor' ? null : field('Agent place text (optional)', inp(n.place, set('place'))),
        n.kind === 'sensor' ? field('Card', sel(Object.keys(Object.assign({}, P.cards.existing, P.site.cards || {})).sort(), n.card, set('card'))) : null),
      h('h4', { text: 'Typed links' }),
      h('ul', { class: 'p1-links' }, links.map((l) => h('li', {}, h('span', { text: l.from + '  ' + l.type + '  ' + l.to + (l.inferred ? '  *' : '') + (l.why ? ' (' + l.why + ')' : '') }),
        h('button', { class: 'btn plain', type: 'button', onclick: () => { P.site.links = P.site.links.filter((x) => x !== l); mark(); renderSite(); } }, 'Remove')))),
      n.kind === 'sensor' ? null : h('div', { class: 'p1-addlink' }, h('span', { text: n.id + ' ' }), lt, to,
        h('button', { class: 'btn', type: 'button', onclick: () => { if (!to.value) return; P.site.links.push({ from: n.id, to: to.value, type: lt.value }); mark(); renderSite(); } }, 'Add link')),
      n.kind === 'sensor' ? h('div', { class: 'sn-btns' }, h('button', { class: 'btn', type: 'button', onclick: () => cardEditor(n, false) }, 'Edit card'),
        h('button', { class: 'btn plain', type: 'button', onclick: () => cardEditor(n, true) }, 'New sensor type')) : null);
    box.append(card);
  }

  /* full spec-card editor: every card field, validated by the backend (same rules as the training cards) */
  function cardEditor(sensorNode, blank) {
    const all = Object.assign({}, P.cards.existing, P.site.cards || {});
    const base = blank ? { card_id: 'new_type', quantity: '', unit: '', kind: 'continuous', domain: 'environment', decimals: 1, context: '', normal: [0, 1],
      warning: { dir: 'high', at: 1 }, critical: { dir: 'high', at: 2 }, impossible: { below: null, above: null }, noise: 1, floor: 1, max_step: null, rate_rules: null,
      dynamics: '', cycle: '', causes: ['normal_conditions', 'sensor_fault'], actions: ['none', 'monitor', 'check_sensor', 'request_facility_review'], faults: P.cards.faults.slice(),
      tank: null, rules: { legacy_key: null, cause_action: {}, routines: [] } } : JSON.parse(JSON.stringify(all[sensorNode.card] || {}));
    if (!blank && P.cards.existing[base.card_id] && !(P.site.cards || {})[base.card_id]) base.card_id = base.card_id + '_' + sensorNode.device.toLowerCase().replace(/[^a-z0-9]+/g, '_');
    const c = base; c.rules = c.rules || {}; c.rules.cause_action = c.rules.cause_action || {};
    const num = (v) => (v === '' || v == null ? null : +v);
    const lim = (k) => {
      const l = c[k]; const on = !!l;
      const dir = sel(['high', 'low', 'both'], on ? l.dir : 'high', (v) => { c[k] = c[k] || {}; c[k].dir = v; draw(); });
      const parts = [h('label', { class: 'p1-chk' }, h('input', { type: 'checkbox', checked: on, onchange: (e) => { c[k] = e.target.checked ? { dir: 'high', at: 0 } : null; draw(); } }), k)];
      if (on) {
        parts.push(dir);
        if (l.dir === 'both') parts.push(inp(l.low, (v) => { l.low = num(v); delete l.at; }, 'number'), inp(l.high, (v) => { l.high = num(v); delete l.at; }, 'number'));
        else parts.push(inp(l.at, (v) => { l.at = num(v); delete l.low; delete l.high; }, 'number'));
      }
      return h('div', { class: 'p1-lim' }, parts);
    };
    const panel = h('div', { class: 'card p1-card p1-cardedit' });
    const out = h('pre', { class: 'sn-pre p1-out' });
    function draw() {
      for (const cs of c.causes) if (!c.rules.cause_action[cs]) c.rules.cause_action[cs] = cs === 'sensor_fault' ? 'check_sensor' : 'monitor';
      for (const k of Object.keys(c.rules.cause_action)) if (!c.causes.includes(k)) delete c.rules.cause_action[k];
      const rr = c.rate_rules;
      panel.replaceChildren(h('h3', { text: (blank ? 'New sensor type' : 'Spec card') + ' for ' + sensorNode.id }),
        h('div', { class: 'p1-grid' },
          field('card_id', inp(c.card_id, (v) => { c.card_id = v; })), field('quantity', inp(c.quantity, (v) => { c.quantity = v; })),
          field('unit', inp(c.unit, (v) => { c.unit = v; })), field('short name (reasoner line)', inp(c.short, (v) => { c.short = v; })),
          field('kind', sel(P.cards.kinds, c.kind, (v) => { c.kind = v; })), field('domain', sel(Object.keys(P.cards.domains), c.domain, (v) => { c.domain = v; })),
          field('decimals', inp(c.decimals, (v) => { c.decimals = num(v) || 0; }, 'number')), field('context', inp(c.context, (v) => { c.context = v; })),
          field('normal low', inp(c.normal ? c.normal[0] : null, (v) => { c.normal = [num(v), c.normal ? c.normal[1] : null]; }, 'number')),
          field('normal high', inp(c.normal ? c.normal[1] : null, (v) => { c.normal = [c.normal ? c.normal[0] : null, num(v)]; }, 'number')),
          field('impossible below', inp((c.impossible || {}).below, (v) => { c.impossible = Object.assign({}, c.impossible, { below: num(v) }); }, 'number')),
          field('impossible above', inp((c.impossible || {}).above, (v) => { c.impossible = Object.assign({}, c.impossible, { above: num(v) }); }, 'number')),
          field('noise', inp(c.noise, (v) => { c.noise = num(v); }, 'number')), field('floor (min. meaningful change)', inp(c.floor, (v) => { c.floor = num(v); }, 'number')),
          field('max 5-min change', inp(c.max_step, (v) => { c.max_step = num(v); }, 'number')),
          field('reasoner hint', inp(c.line_hint, (v) => { c.line_hint = v; }))),
        lim('warning'), lim('critical'),
        h('label', { class: 'p1-chk' }, h('input', { type: 'checkbox', checked: !!rr, onchange: (e) => { c.rate_rules = e.target.checked ? { abrupt_warn: 0, abrupt_crit: 1.5, gradual_warn: 0.3, gradual_crit: null, osc: 'normal' } : null; draw(); } }), 'rate rule (no fixed limits)'),
        rr ? h('div', { class: 'p1-grid' }, ['abrupt_warn', 'abrupt_crit', 'gradual_warn', 'gradual_crit'].map((k) => field(k, inp(rr[k], (v) => { rr[k] = num(v); }, 'number'))),
          field('cycling', sel(['normal', 'warning'], rr.osc, (v) => { rr.osc = v; }))) : null,
        h('label', { class: 'p1-chk' }, h('input', { type: 'checkbox', checked: !!c.tank, onchange: (e) => { c.tank = e.target.checked ? { high: 0, overflow: 0, fill_min: 60 } : null; draw(); } }), 'tank'),
        c.tank ? h('div', { class: 'p1-grid' }, ['high', 'overflow', 'fill_min'].map((k) => field(k, inp(c.tank[k], (v) => { c.tank[k] = num(v); }, 'number')))) : null,
        field('dynamics (normal behaviour)', inp(c.dynamics, (v) => { c.dynamics = v; })), field('cycle (daily routine)', inp(c.cycle, (v) => { c.cycle = v; })),
        field('causes (comma separated; must include sensor_fault)', inp((c.causes || []).join(', '), (v) => { c.causes = v.split(',').map((x) => x.trim()).filter(Boolean); draw(); })),
        h('div', { class: 'p1-grid' }, (c.causes || []).map((cs) => field('action for ' + cs, sel(P.cards.actions, c.rules.cause_action[cs], (v) => { c.rules.cause_action[cs] = v; })))),
        h('div', { class: 'p1-chks' }, h('b', { text: 'actions ' }), P.cards.actions.map((a) => h('label', { class: 'p1-chk' }, h('input', { type: 'checkbox', checked: (c.actions || []).includes(a), onchange: (e) => { c.actions = P.cards.actions.filter((x) => x === a ? e.target.checked : (c.actions || []).includes(x)); } }), a))),
        h('div', { class: 'p1-chks' }, h('b', { text: 'faults ' }), P.cards.faults.map((a) => h('label', { class: 'p1-chk' }, h('input', { type: 'checkbox', checked: (c.faults || []).includes(a), onchange: (e) => { c.faults = P.cards.faults.filter((x) => x === a ? e.target.checked : (c.faults || []).includes(x)); } }), a))),
        h('div', { class: 'sn-btns' },
          h('button', { class: 'btn', type: 'button', onclick: async () => { try { const r = await post('/api/cards/validate', c); out.textContent = r.problems && r.problems.length ? 'Problems:\n- ' + r.problems.join('\n- ') : 'Card is valid.'; } catch (e) { out.textContent = e.message; } } }, 'Validate'),
          h('button', { class: 'btn', type: 'button', onclick: async () => {
            try { await put('/api/site/card', { card: c, sensors: [sensorNode.id] }); toast('Card saved; the agent uses it from the next analysis'); P.cards = null; await loadSite(); P.sel = sensorNode.id; renderSite(); }
            catch (e) { out.textContent = 'Not saved: ' + e.message; }
          } }, 'Save card for this sensor'),
          h('button', { class: 'btn plain', type: 'button', onclick: () => panel.remove() }, 'Close')),
        out);
    }
    draw();
    const host = $id('p1-edit'); host.append(panel); panel.scrollIntoView({ behavior: 'smooth' });
  }

  function renderSite() {
    const box = $id('site'); if (!box || !P.site) return;
    try { renderSite0(box); } catch (e) { box.replaceChildren(h('div', { class: 'empty', text: 'Site view error: ' + (e && e.message || e) })); }
  }
  function renderSite0(box) {
    const camp = P.site.nodes.find((n) => n.kind === 'campus');
    const st = P.status || {};
    const groups = Object.entries(st.open || {}).map(([s, o]) => h('li', { text: o.id + ' ' + o.severity + ' · ' + s + ' · ' + (o.title || '') }));
    const sus = (st.suspects || []).map((x) => h('li', { text: x.node + ' SUSPECT: ' + x.why }));
    const save = h('button', { class: 'btn', id: 'p1-save', type: 'button', disabled: !P.dirty, onclick: async () => {
      try { const r = await put('/api/site', P.site); toast('Site saved as version ' + r.version); await loadSite(); renderSite(); } catch (e) { toast('Not saved: ' + e.message, true); }
    } }, 'Save site (new version)');
    const rebuild = h('button', { class: 'btn plain', type: 'button', onclick: async () => {
      if (!confirm('Rebuild the tree from the API registry? Your node / link edits are replaced (cards are kept).')) return;
      try { await post('/api/site/rebuild'); await loadSite(); renderSite(); toast('Rebuilt from the API'); } catch (e) { toast(e.message, true); }
    } }, 'Rebuild from API');
    const edit = h('div', { id: 'p1-edit' });
    const det = $id('map-det');
    box.replaceChildren(
      h('div', { class: 'card p1-card' }, h('p', { class: 'muted', text: 'Site version ' + P.site.version + ' (' + (P.site.source || '?') + (P.site.saved ? ', saved ' + new Date(P.site.saved).toLocaleString() : '') + ') · ' + P.site.nodes.length + ' nodes · ' + (P.site.links || []).length + ' links' }),
        h('div', { class: 'sn-btns' }, save, rebuild)));
    box.append(h('div', { class: 'p1-cols' },
      h('div', { class: 'card p1-card p1-tree' }, h('h3', { text: 'Site tree' }), camp ? treeNode(camp, 0) : h('p', { text: 'no campus node' })),
      edit));
    editor(edit);
    renderMap(box);
    if (det) box.append(det);
    box.append(h('div', { class: 'card p1-card' }, h('h3', { text: 'Open incidents and suspect parents' }),
      groups.length ? h('ul', {}, groups) : h('p', { class: 'muted', text: 'No open incidents.' }), sus.length ? h('ul', {}, sus) : null));
  }

  /* ---------------- cards & rules: AI trigger rules + sensor thresholds ---------------- */
  const TRIG = [
    ['persist_readings', 'Abnormal readings before the AI is called', 'Each reading = 5 min; a sensor must stay abnormal this long.'],
    ['fast_readings', 'Critical readings for the instant rules alert (fast path)', 'Critical for this many readings raises the rules alert at once.'],
    ['batch_readings', 'Readings to group related sensors into one incident', 'Wait this long so related sensors become one incident.'],
    ['batch_max_readings', 'Longest wait to group (readings)', 'Upper limit of the grouping wait.'],
    ['fast_cooldown', 'Readings before another fast alert on the same sensor', 'Stops repeated instant alerts for one sensor.'],
    ['transient_max', 'Readings a blip may last and still be ignored', 'Shorter excursions are treated as noise.']];
  const fmtN = (v) => (v == null ? '-' : String(v));
  const problemsOf = (e) => {
    const m = /\{[\s\S]*\}/.exec((e && e.message) || ''); if (m) { try { const p = JSON.parse(m[0]).problems; if (p && p.length) return p; } catch (x) { /* not json */ } }
    return [(e && e.message) || 'error'];
  };
  function trigProblems(vals, R) {
    const pr = [], rg = R.ranges || {};
    for (const t of TRIG) {
      const k = t[0], v = vals[k], r = rg[k];
      if (v == null || !Number.isInteger(v)) pr.push(t[1] + ': enter a whole number');
      else if (r && (v < r.min || v > r.max)) pr.push(t[1] + ': must be between ' + r.min + ' and ' + r.max);
    }
    if (vals.fast_readings >= vals.persist_readings) pr.push('Critical readings for the fast path must be fewer than the abnormal readings before the AI is called');
    if (vals.batch_readings > vals.batch_max_readings) pr.push('Readings to group must not exceed the longest wait to group');
    return pr;
  }
  async function renderCards() {
    const box = $id('cards'); if (!box) return;
    try { await renderCards0(box); } catch (e) { box.replaceChildren(h('div', { class: 'empty', text: 'Cards view error: ' + (e && e.message || e) })); }
  }
  async function renderCards0(box) {
    let R;
    try { R = await api('/api/rules'); } catch (e) { box.replaceChildren(h('div', { class: 'empty', text: 'Rules unavailable: ' + e.message })); return; }
    if (!P.site || !P.cards) { try { P.cards = null; await loadSite(); } catch (e) { P.site = null; } }
    const vals = Object.assign({}, R.trigger), def = R.defaults || {}, rg = R.ranges || {};
    const msg = h('div', { class: 'muted p1-msg' });
    const ins = {};
    const fields = TRIG.map((t) => {
      const k = t[0];
      const i = h('input', { class: 'note-in', type: 'number', step: '1', min: rg[k] ? rg[k].min : null, max: rg[k] ? rg[k].max : null, value: vals[k] });
      i.oninput = () => { vals[k] = i.value === '' ? null : +i.value; };
      ins[k] = i;
      return h('label', { class: 'p1-f' }, h('span', { text: t[1] }), i,
        h('small', { class: 'muted', text: t[2] + ' Default ' + fmtN(def[k]) + (rg[k] ? ' (allowed ' + rg[k].min + '-' + rg[k].max + ')' : '') + '.' }));
    });
    const showProblems = (pr) => { msg.textContent = pr.length ? 'Not saved:\n- ' + pr.join('\n- ') : ''; msg.style.whiteSpace = 'pre-wrap'; };
    const save = h('button', { class: 'btn', type: 'button', onclick: async () => {
      const pr = trigProblems(vals, R); showProblems(pr); if (pr.length) { toast(pr[0], true); return; }
      save.disabled = true;
      try { await put('/api/rules', { trigger: vals }); toast('Trigger rules saved'); renderCards(); }
      catch (e) { const p = problemsOf(e); showProblems(p); toast(p[0], true); }
      finally { save.disabled = false; }
    } }, 'Save');
    const reset = h('button', { class: 'btn plain', type: 'button', onclick: () => { for (const t of TRIG) { vals[t[0]] = def[t[0]]; ins[t[0]].value = def[t[0]]; } showProblems([]); toast('Defaults filled in - press Save to apply'); } }, 'Reset to defaults');
    const trig = h('div', { class: 'card p1-card' }, h('h3', { text: 'AI trigger rules' }),
      h('p', { class: 'muted', text: 'When the AI agents are called. One reading = 5 minutes of sensor time.' }),
      h('div', { class: 'p1-grid' }, fields), msg, h('div', { class: 'sn-btns' }, save, reset));

    const sensors = R.sensors || [], roles = new Map();
    sensors.forEach((s) => { const k = s.role || '(none)'; if (!roles.has(k)) roles.set(k, []); roles.get(k).push(s); });
    const SRC = { site_card: 'site card', default_card: 'default card', metrics: 'built-in' };
    const nodeOf = (s) => ((P.site && P.site.nodes) || []).find((n) => n.kind === 'sensor' && n.device === s.node && n.metric === s.metric);
    const sections = [...roles.entries()].sort((a, b) => a[0].localeCompare(b[0])).map((en) => {
      const rows = en[1].map((s) => sensorRow(s, nodeOf(s), SRC));
      return h('details', { class: 'p1-day' }, h('summary', { text: en[0] + ' · ' + en[1].length + ' sensor' + (en[1].length === 1 ? '' : 's') }),
        h('div', { class: 'p1-scroll' }, h('table', { class: 'p1-tab p1-thr' },
          h('thead', {}, h('tr', {}, ['Sensor', 'Card', 'Warn low', 'Warn high', 'Crit low', 'Crit high', 'Impossible below', 'Impossible above', 'Deadband', 'Source', ''].map((t) => h('th', { text: t })))),
          h('tbody', {}, rows))));
    });
    box.replaceChildren(trig, h('div', { class: 'card p1-card' }, h('h3', { text: 'Sensor thresholds' }),
      h('p', { class: 'muted', text: 'These limits are what both the rules (alerts, fast path, when the AI is called) and the AI agents use. Quick edit changes the warning / critical numbers; Edit card opens the full spec card.' }),
      sections.length ? sections : h('p', { class: 'muted', text: 'No sensors reported by the backend yet.' })));
  }
  function sensorRow(s, node, SRC) {
    const tr = h('tr', {});
    const draw = (editing, ed) => {
      const cell = (side, k) => {
        const v = s[side] ? s[side][k] : null;
        if (!editing) return h('td', { text: fmtN(v) });
        const i = h('input', { class: 'note-in p1-num', type: 'number', step: 'any', value: v == null ? '' : v });
        i.oninput = () => { ed[side + '.' + k] = i.value === '' ? null : +i.value; };
        return h('td', {}, i);
      };
      const imp = (k) => h('td', { text: fmtN(s.impossible ? s.impossible[k] : null) });
      const btns = editing
        ? h('td', { class: 'p1-act' }, h('button', { class: 'btn', type: 'button', onclick: () => quickSave(s, node, ed) }, 'Save'), h('button', { class: 'btn plain', type: 'button', onclick: () => draw(false) }, 'Cancel'))
        : h('td', { class: 'p1-act' }, h('button', { class: 'btn plain', type: 'button', disabled: !node || s.source === 'metrics', title: node ? '' : 'Sensor not in the site tree', onclick: () => draw(true, {}) }, 'Quick edit'),
          h('button', { class: 'btn plain', type: 'button', disabled: !node, onclick: () => { P.sel = node.id; P.pendingEdit = node.id; location.hash = '#map'; } }, 'Edit card'));
      tr.replaceChildren(h('td', {}, h('b', { text: s.node }), h('div', { class: 'muted', text: s.metric + (s.unit ? ' (' + s.unit + ')' : '') })),
        h('td', { class: 'muted', text: s.card_id || '-' }),
        cell('warning', 'low'), cell('warning', 'high'), cell('critical', 'low'), cell('critical', 'high'), imp('below'), imp('above'),
        h('td', { text: fmtN(s.floor) }), h('td', {}, h('span', { class: 'p1-badge', text: SRC[s.source] || s.source || '-' })), btns);
    };
    draw(false);
    return tr;
  }
  async function quickSave(s, node, ed) {
    try {
      if (!P.site || !P.cards) await loadSite();
      const all = Object.assign({}, P.cards.existing, P.site.cards || {});
      const src = all[node.card] || all[s.card_id];
      if (!src) throw new Error('no card found for this sensor');
      const c = JSON.parse(JSON.stringify(src));
      if (P.cards.existing[c.card_id] && !(P.site.cards || {})[c.card_id]) c.card_id = c.card_id + '_' + String(node.device || s.node).toLowerCase().replace(/[^a-z0-9]+/g, '_');
      for (const side of ['warning', 'critical']) {
        const l = c[side]; if (!l) continue;
        const lo = ed[side + '.low'], hi = ed[side + '.high'];
        if (l.dir === 'both') { if (lo !== undefined) l.low = lo; if (hi !== undefined) l.high = hi; delete l.at; }
        else if (l.dir === 'low') { const v = lo !== undefined ? lo : hi; if (v !== undefined) l.at = v; }
        else { const v = hi !== undefined ? hi : lo; if (v !== undefined) l.at = v; }
      }
      await put('/api/site/card', { card: c, sensors: [node.id] });
      toast('Limits saved; the rules and agents use them from the next analysis');
      P.cards = null; P.site = null; renderCards();
    } catch (e) { toast('Not saved: ' + problemsOf(e).join('; '), true); }
  }

  async function show(v) {
    P.view = v; clearInterval(P.timer);
    const need = (x) => { if (!window.SCE_H) { const b = $id(x); if (b) b.textContent = 'The app script did not load - reload the page.'; return false; } return true; };
    if (v === 'health' && need('health')) { renderHealth(); P.timer = setInterval(() => { if (P.view === 'health' && !document.hidden) renderHealth(); }, 10000); }
    if (v === 'cards' && need('cards')) renderCards();
    if (v === 'site' && need('site')) {
      try { await loadSite(); renderSite(); if (P.pendingEdit) { const pe = P.site.nodes.find((x) => x.id === P.pendingEdit); P.pendingEdit = null; if (pe) cardEditor(pe, false); } } catch (e) { $id('site').replaceChildren(h('div', { class: 'empty', text: 'Site unavailable: ' + e.message })); }
      P.timer = setInterval(async () => { if (P.view !== 'site' || P.dirty || document.hidden) return; try { P.status = await api('/api/site/status'); } catch (e) { return; } }, 15000);
    }
  }
  window.P1 = { show };
  addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v !== 'map' && v !== 'sensors' && v !== 'site' && v !== 'health' && v !== 'cards') { P.view = ''; clearInterval(P.timer); } });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', netInit); else netInit();
  const v0 = location.hash.slice(1); if (v0 === 'site' || v0 === 'map') setTimeout(() => show('site'), 300); else if (v0 === 'cards') setTimeout(() => show('cards'), 300); else if (v0 === 'health' || v0 === 'sensors') setTimeout(() => show('health'), 300);
})();
