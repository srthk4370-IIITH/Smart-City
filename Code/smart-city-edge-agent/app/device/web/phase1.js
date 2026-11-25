/* Phase 1 UI (proofs/2026-11-16_phase1/README.md): no-network page, data-health panel, daily summary, export,
   site map (campus x,y from the API) + tree picker (parent, links) + full spec-card editor. Uses app.js helpers
   (h, api, post, toast, icon). Writes go to /api/site*, guarded by the backend like every other write. */
(function () {
  'use strict';
  const { h, api, post, toast } = window.SCE_H || {};
  const P = { site: null, status: null, cards: null, sel: null, dirty: false, nonetHidden: false, timer: 0, view: '' };
  const $id = (x) => document.getElementById(x);
  const nice = (s) => (s == null || s === '' ? '-' : String(s).replace(/_/g, ' '));
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
  function sel(opts, val, on, labels) {
    const lab = (o) => (typeof labels === 'function' ? labels(o) : labels && labels[o]) || o || '(none)';
    const s = h('select', { class: 'sel' }, opts.map((o) => h('option', { value: o, text: lab(o), selected: o === val })));
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
      const t = document.createElementNS(NS, 'title'); t.textContent = nm(n) + ' · ' + SW[normSt(st)]; c.append(t);
      c.addEventListener('click', () => { P.sel = n.id; renderSite(); });
      svg.append(c);
    }
    box.append(h('details', { class: 'card p1-card' }, h('summary', {}, h('b', { text: 'Campus positions' })), svg,
      h('p', { class: 'muted', text: 'Where the buildings sit on the campus. Big dots carry monitored sensors; colour shows the worst status below. Tap a dot to open it.' })));
  }

  /* ---------------- plain words for node kinds ---------------- */
  const KW = { campus: 'campus', building: 'building', wing: 'wing', floor: 'floor', room: 'room', zone: 'area', equipment: 'equipment', sensor: 'sensor' };
  const kindWord = (n) => (n.kind === 'building' && /ground|field|court|stadium|garden|lawn/i.test(n.name || '') ? 'ground' : KW[n.kind] || n.kind);
  const nm = (n) => String(n.name || n.id).replace(/\s*\((?:api|API)\)/g, '');
  const nmShort = (n) => { const m = /\(([A-Z0-9]{1,4})\)\s*$/.exec(nm(n)); return m ? m[1] : (n.code || nm(n).slice(0, 6)); };
  const SW = { normal: 'OK', warning: 'Warning', critical: 'Critical', data_issue: 'Data problem' };
  const SG = { normal: '●', warning: '▲', critical: '■', data_issue: '◆' };
  const normSt = (s) => (s === 'critical' || s === 'warning' || s === 'normal' ? s : 'data_issue');
  const NSV = 'http://www.w3.org/2000/svg';
  const sv = (tag, a, ...kids) => {
    const e = document.createElementNS(NSV, tag);
    for (const k in a || {}) if (a[k] != null && a[k] !== false) e.setAttribute(k, a[k]);
    kids.forEach((c) => { if (c != null) e.append(c.nodeType ? c : document.createTextNode(String(c))); });
    return e;
  };
  const sensorsBelow = (id, memo) => {
    if (memo.has(id)) return memo.get(id);
    const n = byId().get(id); let c = n && n.kind === 'sensor' ? 1 : 0;
    kids(id).forEach((k) => { c += sensorsBelow(k.id, memo); });
    memo.set(id, c); return c;
  };
  const pathOpenSet = () => { const s = new Set(), m = byId(); let x = m.get(P.sel); while (x && x.parent) { s.add(x.parent); x = m.get(x.parent); } return s; };

  /* ---------------- botanical tree graphic (inline SVG, no library) ----------------
     trunk = campus, boughs = buildings, thinner branches = floors then rooms, leaves = sensors.
     Leaf colour + glyph = status. Buildings without sensors fold into one "+N other buildings" twig. */
  const CW = 1600, CH = 1100, CX = 800, CY = 900;
  const pol = (r, a) => [CX + r * Math.sin(a), CY - r * Math.cos(a)];
  const LEGEND = { normal: 'Working fine', warning: 'Needs a look', critical: 'Critical', data_issue: 'Data problem' };
  function buildTreeModel() {
    const memo = new Map(), camp = P.site.nodes.find((n) => n.kind === 'campus');
    if (!camp) return null;
    const stOfS = (s) => normSt((((P.status || {}).sensors) || {})[s.id]);
    const shown = (n) => kids(n.id).filter((k) => k.kind === 'sensor' || n.kind === 'campus' || sensorsBelow(k.id, memo) > 0);
    const wgt = (n) => {
      if (n.fold) return 1.2;
      const c = shown(n), br = c.filter((k) => k.kind !== 'sensor'), sn = c.length - br.length;
      return Math.pow(Math.max(1.2, br.reduce((a, k) => a + wgt(k), 0) + (sn ? 0.8 + sn * 0.35 : 0)), 0.85);
    };
    const out = { camp, br: [], lf: [], total: sensorsBelow(camp.id, memo) };
    const A = 62 * Math.PI / 180;
    const grow = (n, depth, a0, a1, parent, idx) => {
      const a = (a0 + a1) / 2;
      const r = n.fold ? 190 : depth === 1 ? 310 + (idx % 2) * 45 : parent.r + ({ 2: 170, 3: 125 }[depth] || 95) + (idx % 2) * 18;
      const pt = pol(r, a), me = { n, depth, a, r, x: pt[0], y: pt[1], L: n.fold ? 0 : sensorsBelow(n.id, memo), parent, st: n.fold ? 'normal' : normSt(nodeStatus(n.id)) };
      const di = ((P.status || {}).rollup || {})[n.id]; if (me.st === 'normal' && di && di.data_issues > 0) me.st = 'data_issue';
      out.br.push(me);
      if (n.fold) return me;
      const c = shown(n), br = c.filter((k) => k.kind !== 'sensor'), sn = c.filter((k) => k.kind === 'sensor');
      const sw = sn.length ? 0.8 + sn.length * 0.35 : 0, tot = br.reduce((s, k) => s + wgt(k), 0) + sw;
      let cur = a0;
      br.forEach((k, i) => { const w = wgt(k) / (tot || 1) * (a1 - a0); grow(k, depth + 1, cur, cur + w, me, i); cur += w; });
      if (sn.length) {
        const sorted = sn.slice().sort((x, y) => (stOfS(y) === 'normal' ? 0 : 1) - (stOfS(x) === 'normal' ? 0 : 1));
        const MAXL = 6, vis = sorted.slice(0, MAXL);
        vis.forEach((s, i) => {
          const phi = vis.length === 1 ? a : a + (i - (vis.length - 1) / 2) * 0.55, len = 36 + (i % 2) * 12, p2 = [me.x + len * Math.sin(phi), me.y - len * Math.cos(phi)];
          out.lf.push({ n: s, x: p2[0], y: p2[1], par: me, st: stOfS(s), cl: sorted.length > 3 });
        });
        if (sorted.length > MAXL) { const p2 = [me.x + 62 * Math.sin(a), me.y - 62 * Math.cos(a)]; out.lf.push({ more: sorted.length - MAXL, x: p2[0], y: p2[1], par: me, n: sorted[MAXL], st: 'normal' }); }
      }
      return me;
    };
    let roots = shown(camp).filter((k) => k.kind !== 'sensor');
    const empty = roots.filter((k) => sensorsBelow(k.id, memo) === 0);
    roots = roots.filter((k) => sensorsBelow(k.id, memo) > 0);
    if (empty.length) { if (P.otherOpen) roots = roots.concat(empty); else roots.push({ id: 'other', kind: 'fold', fold: true, name: '+' + empty.length + ' other building' + (empty.length === 1 ? '' : 's'), names: empty }); }
    const tot = roots.reduce((s, k) => s + wgt(k), 0);
    let cur = -A;
    roots.forEach((k, i) => { const w = wgt(k) / (tot || 1) * 2 * A; grow(k, 1, cur, cur + w, { n: camp, r: 0, x: CX, y: CY, a: 0, L: out.total }, i); cur += w; });
    let x0 = CX, x1 = CX, y0 = CY, y1 = CY + 150;
    out.br.forEach((b) => { x0 = Math.min(x0, b.x); x1 = Math.max(x1, b.x); y0 = Math.min(y0, b.y); });
    out.lf.forEach((l) => { x0 = Math.min(x0, l.x - 20); x1 = Math.max(x1, l.x + 20); y0 = Math.min(y0, l.y - 20); });
    out.bounds = [x0 - 40, y0 - 40, x1 + 40, y1];
    return out;
  }
  function taper(x0, y0, cx, cy, x1, y1, w0, w1) {
    const N = 12, L = [], R = [];
    for (let i = 0; i <= N; i++) {
      const t = i / N, u = 1 - t;
      const x = u * u * x0 + 2 * u * t * cx + t * t * x1, y = u * u * y0 + 2 * u * t * cy + t * t * y1;
      let dx = 2 * u * (cx - x0) + 2 * t * (x1 - cx), dy = 2 * u * (cy - y0) + 2 * t * (y1 - cy);
      const l = Math.hypot(dx, dy) || 1; dx /= l; dy /= l;
      const w = (w0 + (w1 - w0) * Math.pow(t, 0.8)) / 2;
      L.push([x - dy * w, y + dx * w]); R.push([x + dy * w, y - dx * w]);
    }
    const pts = L.concat(R.reverse());
    return 'M' + pts.map((p) => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('L') + 'Z';
  }
  const bwidth = (L, depth) => Math.max(3.5, Math.min(30, 3 + 4.6 * Math.sqrt(L))) * (depth > 2 ? 0.8 : depth === 2 ? 0.9 : 1);
  const plainLabel = (n) => {
    let t = nm(n).replace(/^room of\s+/i, '').split(/\s+/).filter((w) => !/\d/.test(w) && !/^[A-Z]{2,}(-|$)/.test(w) && !/^\(/.test(w)).join(' ').trim() || nm(n);
    if (/^level\s*$/i.test(t)) t = nm(n);
    return t.charAt(0).toUpperCase() + t.slice(1);
  };
  const hsh = (s) => { let x = 0; for (let i = 0; i < s.length; i++) x = (x * 31 + s.charCodeAt(i)) | 0; return ((x >>> 0) % 1000) / 1000; };
  const LEAFD = 'M0 0C5 -6 15 -6 20 0C15 6 5 6 0 0Z';
  function renderTree(box) {
    const M = buildTreeModel(); if (!M) { box.append(h('div', { class: 'card p1-card' }, h('p', { class: 'muted', text: 'The site has no campus node yet.' }))); return; }
    const svg = sv('svg', { class: 'bt-svg', role: 'img', 'aria-label': 'Campus tree: the trunk is the campus, boughs are buildings, branches are floors and rooms, leaves are sensors. The same tree is listed below.', preserveAspectRatio: 'xMidYMid meet' });
    const gB = sv('g', { class: 'bt-br' }), gL = sv('g', { class: 'bt-lf' }), gT = sv('g', { class: 'bt-tx', 'aria-hidden': 'true' });
    svg.append(sv('ellipse', { class: 'bt-shadow', cx: CX, cy: CY + 150, rx: 520, ry: 26 }), sv('path', { class: 'bt-ground', d: 'M0 ' + (CY + 150) + 'Q' + CX + ' ' + (CY + 120) + ' ' + CW + ' ' + (CY + 150) + 'L' + CW + ' ' + (CH + 400) + 'L0 ' + (CH + 400) + 'Z' }), gB, gL, gT);
    const pick = (id) => (e) => { e.stopPropagation(); if (svg._drag) return; if (id === 'other') { P.otherOpen = !P.otherOpen; renderSite(); return; } selectNode(id); };
    const tw = bwidth(M.total, 1) * 1.7 + 12;
    const trunk = sv('path', { class: 'bt-b bt-normal', d: taper(CX - 4, CY + 150, CX + 10, CY + 70, CX, CY, tw * 1.5, tw * 0.85), 'data-id': M.camp.id });
    trunk.append(sv('title', {}, nm(M.camp) + ' (campus)')); trunk.addEventListener('click', pick(M.camp.id)); gB.append(trunk);
    const labels = [], order = M.br.slice().sort((a, b) => a.depth - b.depth);
    order.forEach((b) => {
      const p = b.parent, j = (hsh(b.n.id) - 0.5) * 36, bend = (b.a < 0 ? -1 : 1) * 0.12;
      const ctl = p.r === 0 ? pol(b.r * 0.55, b.a * 0.4) : pol(p.r + (b.r - p.r) * 0.55 + j, p.a + bend * (hsh(b.n.id + 'x') - 0.3));
      const w1 = bwidth(b.L, b.depth), w0 = p.r === 0 ? w1 * 1.25 : w1, wt = Math.max(3, w1 * 0.5);
      const el = sv('path', { class: 'bt-b bt-' + b.st + (b.n.fold ? ' fold' : ''), d: taper(p.x, p.y, ctl[0], ctl[1], b.x, b.y, w0, wt), 'data-id': b.n.id });
      el.append(sv('title', {}, b.n.fold ? b.n.name + ' (tap to ' + (P.otherOpen ? 'fold' : 'show') + ')' : nm(b.n) + ' (' + kindWord(b.n) + ') - ' + LEGEND[b.st]));
      const hit = sv('path', { class: 'bt-hit', d: 'M' + p.x.toFixed(1) + ' ' + p.y.toFixed(1) + 'Q' + ctl[0].toFixed(1) + ' ' + ctl[1].toFixed(1) + ' ' + b.x.toFixed(1) + ' ' + b.y.toFixed(1), 'data-id': b.n.id });
      el.addEventListener('click', pick(b.n.id)); hit.addEventListener('click', pick(b.n.id));
      gB.append(el, hit, sv('circle', { class: 'bt-b bt-' + b.st, cx: b.x, cy: b.y, r: wt * 0.55, 'data-id': b.n.id }));
      // label geometry: point at 38 % along the curve (near the base, where the branch is thick)
      const t = b.depth === 1 ? 0.4 : 0.55, u = 1 - t;
      const mx = u * u * p.x + 2 * u * t * ctl[0] + t * t * b.x, my = u * u * p.y + 2 * u * t * ctl[1] + t * t * b.y;
      let dx = 2 * u * (ctl[0] - p.x) + 2 * t * (b.x - ctl[0]), dy = 2 * u * (ctl[1] - p.y) + 2 * t * (b.y - ctl[1]);
      if (dx < 0) { dx = -dx; dy = -dy; }
      const ang = Math.atan2(dy, dx) * 180 / Math.PI, steep = Math.abs(ang) > 60;
      const glyph = b.st !== 'normal' ? SG[b.st] + ' ' : '';
      const pn = plainLabel(b.n), full = glyph + (b.depth === 1 ? nm(b.n) : pn), short = glyph + (b.n.fold ? b.n.name : b.depth === 1 ? nmShort(b.n) : pn.split(' ').slice(0, 2).join(' '));
      const text = sv('text', { class: 'bt-t d' + Math.min(b.depth, 3) + (b.st !== 'normal' ? ' bad' : '') + (b.n.fold ? ' fold' : '') }, full);
      gT.append(text);
      labels.push({ text, mx, my, ang: steep ? 0 : ang, steep, off: w1 / 2 + 5, right: b.x >= CX, full, short, pri: (b.n.fold ? 5 : 0) + b.depth * 10 - Math.min(b.L, 9) * 0.1, bold: b.depth === 1, curLen: Math.hypot(b.x - p.x, b.y - p.y) });
    });
    labels.sort((a, b) => a.pri - b.pri);
    M.lf.forEach((l) => {
      const ang = Math.atan2(l.y - l.par.y, l.x - l.par.x) * 180 / Math.PI + (hsh((l.n.id || '') + 'r') - 0.5) * 30;
      const g = sv('g', { class: 'bt-leaf bt-' + l.st + (P.sel === l.n.id ? ' sel' : ''), 'data-id': l.more ? 'more' : l.n.id });
      { const qx = (l.par.x + l.x) / 2 + (l.y - l.par.y) * 0.18, qy = (l.par.y + l.y) / 2 - (l.x - l.par.x) * 0.18; gB.append(sv('path', { class: 'bt-twig', d: 'M' + l.par.x.toFixed(1) + ' ' + l.par.y.toFixed(1) + 'Q' + qx.toFixed(1) + ' ' + qy.toFixed(1) + ' ' + l.x.toFixed(1) + ' ' + l.y.toFixed(1) })); }
      if (l.more) {
        g.append(sv('circle', { class: 'bt-more', r: 13 }), sv('text', { class: 'bt-cnt', 'text-anchor': 'middle', dy: '.35em' }, '+' + l.more), sv('title', {}, l.more + ' more sensors here'));
      } else {
        const sway = sv('g', { class: 'bt-sway', style: 'animation-delay:' + (hsh(l.n.id) * -4).toFixed(2) + 's' });
        const rot = sv('g', { transform: 'rotate(' + ang.toFixed(0) + ')' }, sv('path', { class: 'bt-shape', d: LEAFD }));
        sway.append(rot);
        if (l.st !== 'normal') { const c = 10 * Math.cos(ang * Math.PI / 180), s = 10 * Math.sin(ang * Math.PI / 180); sway.append(sv('text', { class: 'bt-gl', x: c.toFixed(1), y: s.toFixed(1), 'text-anchor': 'middle', dy: '.35em' }, SG[l.st])); }
        g.append(sway, sv('title', {}, (l.n.name || nice(l.n.metric)) + ' - ' + LEGEND[l.st]));
        const lt = sv('text', { class: 'bt-lt', x: 24, dy: '.35em' }, nice(l.n.metric)); g.append(lt); l.lt = lt;
      }
      g.addEventListener('click', pick(l.n.id));
      gL.append(g); l.g = g;
    });
    P.treePos = new Map(); M.br.forEach((b) => P.treePos.set(b.n.id, [b.x, b.y])); M.lf.forEach((l) => { if (!l.more) P.treePos.set(l.n.id, [l.x, l.y]); });
    P.treeLinks = sv('g', { class: 'bt-links', 'aria-hidden': 'true' }); svg.insertBefore(P.treeLinks, gL);
    const view = { cx: CX, cy: 600, w: CW };
    const wrap = h('div', { class: 'bt-wrap' }, svg);
    const dims = () => { const r = wrap.getBoundingClientRect(); return { w: r.width || 360, h: r.height || 420 }; };
    const apply = () => {
      const d = dims(), vh = view.w * d.h / d.w, sc = d.w / view.w, fs = 12 / sc, k = Math.min(3.2, Math.max(0.9, 6 / (9 * sc)));
      svg.setAttribute('viewBox', (view.cx - view.w / 2).toFixed(1) + ' ' + (view.cy - vh / 2).toFixed(1) + ' ' + view.w.toFixed(1) + ' ' + vh.toFixed(1));
      P.vb = { cx: view.cx, cy: view.cy, w: view.w };
      // label collision pass: highest priority first, a label is hidden if its box overlaps one already placed
      const placed = [];
      labels.forEach((L) => {
        const size = L.bold ? fs * 1.08 : fs, fit = (txt) => txt.length * size * 0.6 <= Math.max(L.curLen * 1.1, 1);
        let txt = fit(L.full) ? L.full : fit(L.short) ? L.short : (L.pri < 12 ? L.short : '');
        if (L.pri >= 12 && !fit(L.full) && !fit(L.short)) txt = '';
        let box = null;
        if (txt) {
          const w = txt.length * size * 0.6, hgt = size * 1.2, a = L.ang * Math.PI / 180, ox = L.steep ? (L.right ? L.off + w / 2 : -(L.off + w / 2)) : 0, oy = L.steep ? 0 : -L.off - size * 0.2;
          const cx = L.mx + ox - Math.sin(a) * 0, cy = L.my + oy, ex = Math.abs(Math.cos(a)) * w / 2 + Math.abs(Math.sin(a)) * hgt / 2, ey = Math.abs(Math.sin(a)) * w / 2 + Math.abs(Math.cos(a)) * hgt / 2;
          box = [cx - ex, cy - ey, cx + ex, cy + ey, cx, cy];
          if (placed.some((q) => box[0] < q[2] && box[2] > q[0] && box[1] < q[3] && box[3] > q[1])) txt = '';
        }
        if (!txt) { L.text.style.display = 'none'; return; }
        placed.push(box); L.text.style.display = ''; if (L.text.textContent !== txt) L.text.textContent = txt;
        L.text.setAttribute('font-size', size.toFixed(2));
        L.text.setAttribute('text-anchor', L.steep ? (L.right ? 'start' : 'end') : 'middle');
        const px = L.steep ? L.mx + (L.right ? L.off : -L.off) : L.mx, py = L.steep ? L.my : L.my - L.off - size * 0.2;
        L.text.setAttribute('transform', 'translate(' + px.toFixed(1) + ' ' + py.toFixed(1) + ') rotate(' + L.ang.toFixed(1) + ')');
        L.text.setAttribute('dy', L.steep ? '.35em' : '0');
      });
      M.lf.forEach((l) => { l.g.setAttribute('transform', 'translate(' + l.x.toFixed(1) + ' ' + l.y.toFixed(1) + ') scale(' + k.toFixed(2) + ')'); if (l.lt) l.lt.style.display = sc * k >= 0.8 ? '' : 'none'; if (l.lt) l.lt.setAttribute('font-size', (12 / (sc * k)).toFixed(2)); });
    };
    const fit = () => {
      const d = dims(), b = M.bounds, bw = (b[2] - b[0]) * 1.06, bh = (b[3] - b[1]) * 1.06;
      view.w = Math.max(bw, bh * d.w / d.h); view.cx = (b[0] + b[2]) / 2; view.cy = (b[1] + b[3]) / 2; apply();
    };
    const zoom = (f, px, py) => {
      const d = dims(), vh = view.w * d.h / d.w, nw = Math.max(260, Math.min(CW * 1.6, view.w / f)), fx = px == null ? 0.5 : px, fy = py == null ? 0.5 : py;
      const ox = view.cx - view.w / 2 + fx * view.w, oy = view.cy - vh / 2 + fy * vh, nh = nw * d.h / d.w;
      view.cx = ox - fx * nw + nw / 2; view.cy = oy - fy * nh + nh / 2; view.w = nw; apply();
    };
    const ptrs = new Map(); let last = null, startPt = null;
    svg.addEventListener('pointerdown', (e) => { ptrs.set(e.pointerId, [e.clientX, e.clientY]); startPt = [e.clientX, e.clientY]; svg._drag = false; last = null; });
    svg.addEventListener('pointermove', (e) => {
      if (!ptrs.has(e.pointerId)) return;
      const d = dims(), prev = ptrs.get(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]);
      if (ptrs.size === 1) {
        if (!svg._drag && Math.hypot(e.clientX - startPt[0], e.clientY - startPt[1]) < 6) return;
        if (!svg._drag) { svg._drag = true; try { svg.setPointerCapture(e.pointerId); } catch (x) { /* ignore */ } }
        view.cx -= (e.clientX - prev[0]) * view.w / d.w; view.cy -= (e.clientY - prev[1]) * view.w / d.w; apply();
      } else if (ptrs.size === 2) {
        svg._drag = true; const [a, b] = [...ptrs.values()], dist = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (last) { const r = svg.getBoundingClientRect(); zoom(dist / last, ((a[0] + b[0]) / 2 - r.left) / r.width, ((a[1] + b[1]) / 2 - r.top) / r.height); } last = dist;
      }
    });
    const up = (e) => { ptrs.delete(e.pointerId); last = null; setTimeout(() => { if (!ptrs.size) svg._drag = false; }, 0); };
    svg.addEventListener('pointerup', up); svg.addEventListener('pointercancel', up);
    svg.addEventListener('wheel', (e) => { e.preventDefault(); const r = svg.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.2 : 1 / 1.2, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height); }, { passive: false });
    const tb = (label, txt, fn) => h('button', { type: 'button', class: 'btn sm bt-btn', 'aria-label': label, title: label, onclick: fn }, txt);
    const legend = h('div', { class: 'bt-legend', 'aria-label': 'What the leaves mean' }, h('span', { text: 'Each leaf is a sensor:' }),
      ['normal', 'warning', 'critical', 'data_issue'].map((s) => h('span', { class: 'bt-key bt-' + s }, h('i', { 'aria-hidden': 'true', text: s === 'normal' ? '●' : SG[s] }), LEGEND[s])));
    box.append(h('div', { class: 'card p1-card bt-card' },
      h('div', { class: 'bt-hd' }, h('h3', { text: 'Campus tree' }), h('div', { class: 'bt-tools' }, tb('Zoom in', '+', () => zoom(1.35)), tb('Zoom out', '-', () => zoom(1 / 1.35)), tb('Fit the whole tree', 'Fit', fit))), legend, wrap,
      h('p', { class: 'muted', text: 'Trunk = campus, boughs = buildings, branches = floors and rooms. Tap a branch or leaf to open it; drag to move, pinch or scroll to zoom.' })));
    P.treeApply = { fit, apply, view };
    requestAnimationFrame(() => { if (P.vb) { view.cx = P.vb.cx; view.cy = P.vb.cy; view.w = P.vb.w; apply(); } else fit(); markSel(); });
    if (typeof ResizeObserver !== 'undefined') { const ro = new ResizeObserver(() => apply()); ro.observe(wrap); }
    P.treeEl = svg;
  }
  function markSel() {
    if (!P.treeEl) return;
    P.treeEl.querySelectorAll('.sel,.onpath').forEach((e) => e.classList.remove('sel', 'onpath'));
    const esc = (v) => (window.CSS && CSS.escape ? CSS.escape(v) : v), m = byId();
    P.treeEl.querySelectorAll('[data-id="' + esc(P.sel || '') + '"]').forEach((e) => { if (!e.classList.contains('bt-hit')) e.classList.add('sel'); });
    let x = m.get(P.sel); while (x && x.parent) { P.treeEl.querySelectorAll('.bt-b[data-id="' + esc(x.parent) + '"]').forEach((e) => e.classList.add('onpath')); x = m.get(x.parent); }
    if (P.treeLinks) {
      P.treeLinks.replaceChildren();
      (P.site.links || []).filter((l) => l.from === P.sel || l.to === P.sel).forEach((l) => {
        const a = P.treePos.get(l.from), b = P.treePos.get(l.to); if (!a || !b) return;
        P.treeLinks.append(sv('path', { class: 'bt-link', d: 'M' + a[0].toFixed(1) + ' ' + a[1].toFixed(1) + 'Q' + ((a[0] + b[0]) / 2).toFixed(1) + ' ' + (Math.min(a[1], b[1]) - 90).toFixed(1) + ' ' + b[0].toFixed(1) + ' ' + b[1].toFixed(1) }));
      });
    }
    const sn = m.get(P.sel); if (sn && sn.kind === 'sensor') P.treeEl.querySelectorAll('.bt-b[data-id="' + esc(sn.parent) + '"]').forEach((e) => e.classList.add('onpath'));
  }
  function selectNode(id) {
    P.sel = id; markSel();
    const m = byId(); let x = m.get(id); while (x && x.parent) { P.open.add(x.parent); x = m.get(x.parent); }
    const tw = $id('p1-twin'), had = tw && tw.contains(document.activeElement); if (tw) { renderTwin(tw); if (had) { const r = tw.querySelector('[data-id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]'); if (r) r.focus(); } }
    const ed = $id('p1-edit'); if (ed) { ed.replaceChildren(); editor(ed); try { ed.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (e) { /* ignore */ } }
  }

  /* keyboard-accessible twin of the graphic: role=tree */
  function renderTwin(host) {
    const camp = P.site.nodes.find((n) => n.kind === 'campus'); if (!camp) return;
    const memo = new Map(), focusId = P.focus && byId().has(P.focus) ? P.focus : (P.sel && byId().has(P.sel) ? P.sel : camp.id);
    const build = (n, level) => {
      const ch = kids(n.id), st = normSt(nodeStatus(n.id)), isOpen = P.open.has(n.id) && ch.length;
      const ns = sensorsBelow(n.id, memo), stt = n.kind === 'sensor' ? normSt(((P.status || {}).sensors || {})[n.id]) : st;
      const row = h('button', { type: 'button', class: 'p1-tn' + (P.sel === n.id ? ' on' : ''), tabindex: n.id === focusId ? '0' : '-1', 'data-id': n.id,
        onclick: () => { P.focus = n.id; if (ch.length) { if (P.open.has(n.id) && P.sel === n.id) P.open.delete(n.id); else P.open.add(n.id); } selectNode(n.id); } },
      h('span', { class: 'p1-tw', 'aria-hidden': 'true', text: ch.length ? (isOpen ? '▾' : '▸') : '' }),
      h('span', { class: 'bt-key bt-' + stt }, h('i', { 'aria-hidden': 'true', text: SG[stt] }), h('span', { class: 'sr-only', text: SW[stt] })),
      h('span', { class: 'p1-nm', text: n.kind === 'sensor' ? (n.name || nice(n.metric)) : nm(n) + (n.inferred ? ' *' : '') }),
      h('span', { class: 'p1-kw', text: kindWord(n) }),
      ns && n.kind !== 'sensor' ? h('span', { class: 'p1-cnt', text: ns + (ns === 1 ? ' sensor' : ' sensors') }) : null);
      const li = h('li', { role: 'treeitem', 'aria-level': level, 'aria-selected': P.sel === n.id ? 'true' : 'false', 'aria-expanded': ch.length ? (isOpen ? 'true' : 'false') : null }, row);
      if (isOpen) li.append(h('ul', { role: 'group', class: 'p1-kids' }, ch.map((c) => build(c, level + 1))));
      return li;
    };
    const ul = h('ul', { role: 'tree', class: 'p1-treelist', 'aria-label': 'Site tree' }, build(camp, 1));
    ul.addEventListener('keydown', (e) => {
      const rows = [...ul.querySelectorAll('.p1-tn')], i = rows.indexOf(document.activeElement); if (i < 0) return;
      const go = (j) => { const r = rows[Math.max(0, Math.min(rows.length - 1, j))]; rows.forEach((x) => x.tabIndex = -1); r.tabIndex = 0; r.focus(); P.focus = r.dataset.id; };
      const id = rows[i].dataset.id, n = byId().get(id), has = kids(id).length;
      if (e.key === 'ArrowDown') { e.preventDefault(); go(i + 1); } else if (e.key === 'ArrowUp') { e.preventDefault(); go(i - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); if (has && !P.open.has(id)) { P.open.add(id); P.focus = id; renderTwin(host); const r = host.querySelector('[data-id="' + id + '"]'); if (r) r.focus(); } else if (has) go(i + 1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); if (has && P.open.has(id)) { P.open.delete(id); P.focus = id; renderTwin(host); const r = host.querySelector('[data-id="' + id + '"]'); if (r) r.focus(); } else if (n && n.parent) { const r = rows.find((x) => x.dataset.id === n.parent); if (r) { rows.forEach((x) => x.tabIndex = -1); r.tabIndex = 0; r.focus(); P.focus = n.parent; } } }
      else if (e.key === 'Home') { e.preventDefault(); go(0); } else if (e.key === 'End') { e.preventDefault(); go(rows.length - 1); }
    });
    host.replaceChildren(h('h3', { text: 'Site tree' }), ul);
  }

  function editor(box) {
    const m = byId(), n = m.get(P.sel);
    if (!n) { box.append(h('div', { class: 'card p1-card' }, h('p', { class: 'muted', text: 'Tap a branch or leaf on the tree, or pick it in the list, to edit it. * = relation inferred by a rule (check it).' }))); return; }
    const mark = () => { P.dirty = true; $id('p1-save').disabled = false; };
    const set = (k) => (v) => { n[k] = v; if (k === 'parent' || k === 'name') renderSite(); mark(); };
    const ids = P.site.nodes.filter((x) => x.kind !== 'sensor' && x.id !== n.id).map((x) => x.id);
    const links = (P.site.links || []).filter((l) => l.from === n.id || l.to === n.id);
    const lt = sel(LINKS, 'serves', () => {}), to = sel(P.site.nodes.filter((x) => x.kind !== 'sensor' && x.id !== n.id).map((x) => x.id), '', () => {}, (id) => { const x = m.get(id); return x ? nm(x) : id; });
    const lbl = (id) => { const x = m.get(id); return x ? nm(x) : id; }, plain = (o) => String(o).replace(/_/g, ' ');
    const card = h('div', { class: 'card p1-card' }, h('h3', { text: nm(n) }),
      h('p', { class: 'muted', text: kindWord(n).charAt(0).toUpperCase() + kindWord(n).slice(1) + ' · ' + SW[normSt(n.kind === 'sensor' ? ((P.status || {}).sensors || {})[n.id] : nodeStatus(n.id))] }),
      h('details', { class: 'tech' }, h('summary', { text: 'Technical details' }), h('div', { class: 'tech-bd' }, h('p', { class: 'muted', text: n.id + ' · ' + n.kind + (n.etype ? ' · ' + n.etype : '') + (n.api_type ? ' · API type ' + n.api_type : '') + (n.why ? ' · ' + n.why : '') }))),
      h('div', { class: 'p1-grid' },
        field('Name', inp(n.name, set('name'))),
        n.kind === 'campus' ? null : field('Parent', sel(ids, n.parent, set('parent'), (id) => { const x = m.get(id); return x ? nm(x) : id; })),
        field('Kind', sel(KINDS, n.kind, set('kind'), KW)),
        n.kind === 'equipment' ? field('Equipment type', sel(ETYPES, n.etype, set('etype'), plain)) : null,
        n.kind === 'room' || n.kind === 'zone' ? field('Use', sel(['', 'lecture_hall', 'office', 'lab', 'hostel_room', 'corridor', 'plant_room', 'library', 'canteen', 'server_room', 'meeting_room', 'outdoor_area'], n.use || '', set('use'), plain)) : null,
        n.kind === 'room' || n.kind === 'zone' ? field('Capacity', inp(n.capacity, set('capacity'), 'number')) : null,
        n.kind === 'sensor' ? null : field('Agent place text (optional)', inp(n.place, set('place'))),
        n.kind === 'sensor' ? field('Card', sel(Object.keys(Object.assign({}, P.cards.existing, P.site.cards || {})).sort(), n.card, set('card'))) : null),
      h('h4', { text: 'Typed links' }),
      h('ul', { class: 'p1-links' }, links.map((l) => h('li', {}, h('span', { text: lbl(l.from) + '  ' + plain(l.type) + '  ' + lbl(l.to) + (l.inferred ? '  *' : '') + (l.why ? ' (' + l.why + ')' : '') }),
        h('button', { class: 'btn plain', type: 'button', onclick: () => { P.site.links = P.site.links.filter((x) => x !== l); mark(); renderSite(); } }, 'Remove')))),
      n.kind === 'sensor' ? null : h('div', { class: 'p1-addlink' }, h('span', { text: nm(n) + ' ' }), lt, to,
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
  const SEVW = { critical: 'Critical', warning: 'Warning', normal: 'Fine', info: 'Fine', sensor_fault: 'Fault' };
  function renderSite0(box) {
    const camp = P.site.nodes.find((n) => n.kind === 'campus');
    const st = P.status || {}, by = byId();
    if (!P.open) P.open = new Set();
    if (camp) P.open.add(camp.id);
    pathOpenSet().forEach((x) => P.open.add(x));
    const groups = Object.entries(st.open || {}).map(([s, o]) => h('li', { text: (SEVW[o.severity] || o.severity) + ' · ' + (o.title || '') + ' (' + o.id + ')' }));
    const sus = (st.suspects || []).map((x) => { const nd = by.get(x.node); return h('li', { text: (nd ? nm(nd) : x.node) + ' may be the cause: ' + x.why }); });
    const save = h('button', { class: 'btn', id: 'p1-save', type: 'button', disabled: !P.dirty, title: P.dirty ? null : 'Nothing to save yet: no changes made', onclick: async () => {
      try { const r = await put('/api/site', P.site); toast('Site saved as version ' + r.version); await loadSite(); renderSite(); } catch (e) { toast('Not saved: ' + e.message, true); }
    } }, 'Save site (new version)');
    const confirmBox = h('div', { class: 'p1-confirm', role: 'alertdialog', 'aria-label': 'Confirm rebuild', hidden: true },
      h('p', { text: 'Rebuild the tree from the API registry? Your node and link edits are replaced (spec cards are kept).' }),
      h('div', { class: 'sn-btns' },
        h('button', { class: 'btn danger', type: 'button', onclick: async () => {
          try { await post('/api/site/rebuild'); await loadSite(); renderSite(); toast('Rebuilt from the API'); } catch (e) { toast(e.message, true); }
        } }, 'Yes, rebuild'),
        h('button', { class: 'btn plain', type: 'button', onclick: () => { confirmBox.hidden = true; } }, 'Cancel')));
    const rebuild = h('button', { class: 'btn plain', type: 'button', onclick: () => { confirmBox.hidden = false; } }, 'Rebuild from API');
    const admin = h('details', { class: 'card p1-card', id: 'p1-admin', open: P.adminOpen ? true : null, ontoggle: (e) => { P.adminOpen = e.target.open; } },
      h('summary', {}, h('b', { text: 'Site admin' }), P.dirty ? h('span', { class: 'p1-dirty', text: ' - unsaved changes' }) : null),
      h('p', { class: 'muted', text: 'Site version ' + P.site.version + ' (' + (P.site.source || '?') + (P.site.saved ? ', saved ' + new Date(P.site.saved).toLocaleString() : '') + ') · ' + P.site.nodes.length + ' nodes · ' + (P.site.links || []).length + ' links' }),
      h('div', { class: 'sn-btns' }, save, rebuild), confirmBox);
    const edit = h('div', { id: 'p1-edit' }), twin = h('div', { class: 'card p1-card p1-tree', id: 'p1-twin' });
    const det = $id('map-det');
    box.replaceChildren();
    P.treeEl = null;
    renderTree(box);
    box.append(h('div', { class: 'p1-cols' }, twin, edit));
    renderTwin(twin);
    editor(edit);
    renderMap(box);
    if (det) box.append(det);
    box.append(h('div', { class: 'card p1-card' }, h('h3', { text: 'Open incidents and suspect parents' }),
      groups.length ? h('ul', {}, groups) : h('p', { class: 'muted', text: 'No open incidents.' }), sus.length ? h('ul', {}, sus) : null));
    box.append(admin);
  }

  /* ---------------- cards & rules: AI trigger rules + sensor thresholds ---------------- */
  const TRIG = [
    ['persist_readings', 'Reading window the AI check looks at', 'Each reading = 5 min; the AI check counts abnormal readings among the last this many.'],
    ['abnormal_of_window', 'Abnormal readings out of the last 8 before the AI is called', 'The AI is called when this many of the window readings are beyond the threshold, not necessarily in a row.'],
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
    if (vals.fast_readings >= vals.persist_readings) pr.push('Critical readings for the fast path must be fewer than the reading window');
    if (vals.abnormal_of_window > vals.persist_readings) pr.push('Abnormal readings before the AI is called must not exceed the reading window');
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
      P.timer = setInterval(async () => { if (P.view !== 'site' || P.dirty || document.hidden) return; try { const ns = await api('/api/site/status'); const ch = JSON.stringify(ns) !== JSON.stringify(P.status); P.status = ns; if (ch && P.view === 'site') renderSite(); } catch (e) { return; } }, 15000);
    }
  }
  window.P1 = { show };
  addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v !== 'map' && v !== 'sensors' && v !== 'site' && v !== 'health' && v !== 'cards') { P.view = ''; clearInterval(P.timer); } });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', netInit); else netInit();
  const v0 = location.hash.slice(1); if (v0 === 'site' || v0 === 'map') setTimeout(() => show('site'), 300); else if (v0 === 'cards') setTimeout(() => show('cards'), 300); else if (v0 === 'health' || v0 === 'sensors') setTimeout(() => show('health'), 300);
})();
