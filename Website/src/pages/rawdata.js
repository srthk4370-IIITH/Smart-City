// Raw data explorer: year view (hourly band + mean), thresholds, breaches with reasons, split months,
// held-out badge, 5-min zoom from monthly chunks, "used for training" lane, per-sensor analysis, sankey.
export default async function mount(ctx) {
  const { root, h, ui } = ctx;
  const $ = (s) => root.querySelector(`[data-slot="${s}"]`);
  const cs = getComputedStyle(document.documentElement);
  const tok = (n, d) => cs.getPropertyValue(n).trim() || d;
  const C = {
    accent: tok('--accent', '#4c7dff'), accentSoft: 'rgba(76,125,255,0.22)', text: tok('--text', '#e9e9ea'), silver: tok('--silver', '#c4c6cc'),
    muted: tok('--muted', '#9a9ca3'), line: tok('--line', '#2a2c31'), panel: tok('--panel', '#1c1d21'), alt: tok('--alt', '#6b6e76'),
    warn: tok('--sev-warning', '#f2b83d'), bad: tok('--sev-critical', '#f05a52'), good: tok('--sev-normal', '#46c98a'),
    v1: tok('--win-v1', '#2fc9b4'), v2: tok('--win-v2', '#f27bbd'),
    splitTrain: tok('--split-train', 'rgba(108,180,245,0.10)'), splitDev: tok('--split-dev', 'rgba(242,184,61,0.12)'), splitTest: tok('--split-test', 'rgba(169,139,245,0.14)'),
    mono: tok('--font-mono', 'monospace'), sans: tok('--font-sans', 'sans-serif'),
  };
  // domain colours (tokens.css --dom-*): the domain chips and the sensor's mean line use them
  const DOMC = { air_quality: tok('--dom-air', '#7cc4f5'), outdoor_air: tok('--dom-air', '#7cc4f5'), water: tok('--dom-water', '#2fc4d8'),
    power: tok('--dom-power', '#f0d24b'), weather: tok('--dom-weather', '#f0903e'), occupancy: tok('--dom-occupancy', '#f27bbd'),
    hvac: tok('--dom-hvac', '#7ee8b8'), hvac_units: tok('--dom-hvac', '#7ee8b8') };
  const domColor = (d) => DOMC[d] || C.accent;
  const PAL = ['#7fa2ff', '#3fbf7f', '#e0a33a', '#c678dd', '#56b6c2', '#e5534b', '#d19a66', '#98c379', '#61afef', '#be5046',
    '#a9abb1', '#e06c9f', '#8fbcbb', '#ebcb8b', '#b48ead', '#88c0d0'];
  const MS = 1000, DAY = 86400;
  const small = () => root.clientWidth < 600;
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmtN = (v) => (v >= 1e6 ? (v / 1e6).toFixed(1) + ' M' : v.toLocaleString('en-US'));
  const fmtT = (t) => new Date(t).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' });

  function unpack(s, dec) {
    const out = [];
    if (!s) return out;
    const sc = 10 ** dec;
    let prev = 0;
    for (const t of s.split(',')) {
      if (t[0] === '~') { for (let k = +t.slice(1); k > 0; k--) out.push(null); continue; }
      const i = t.indexOf('*');
      if (i > 0) { const d = +t.slice(0, i); for (let k = +t.slice(i + 1); k > 0; k--) { prev += d; out.push(prev / sc); } }
      else { prev += +t; out.push(prev / sc); }
    }
    return out;
  }

  const echarts = await ctx.charts.ensureEcharts();
  const idx = await ctx.data.json('raw/index.json');
  const T = idx.totals;
  const Y0 = idx.year_t0, MT = idx.month_t0;

  // ------------------------------------------------------------ anchors
  $('anchors').append(ui.anchors([
    { after: String(T.sensors), label: 'sensors, every one browsable', meta: idx.domains.length + ' domains' },
    { after: fmtN(T.readings), label: '5-min readings in 2025', meta: T.months + ' months' },
    { after: fmtN(T.breaches), label: 'limit breaches, each with its reason', meta: fmtN(T.breaches_crit) + ' critical', ours: false },
    { after: fmtN(T.windows_used), label: 'real windows used as training bases', meta: `v1 ${fmtN(T.examples_v1)} · v2 ${fmtN(T.examples_v2)}` },
  ]));

  $('legend').append(ui.legend([['Critical breach', 'var(--sev-critical)'], ['Warning breach', 'var(--sev-warning)'],
    ['Train months', 'var(--t-app_ux)'], ['Dev months', 'var(--sev-warning)'], ['Test months', 'var(--o-pending)'],
    ['v1 windows', 'var(--win-v1)'], ['v2 windows', 'var(--win-v2)']], 'Chart colours'));

  // ------------------------------------------------------------ picker
  const state = { domain: null, sid: null, metric: null, sensor: null, doc: null, ana: null, five: false, focus: null };
  const byId = Object.fromEntries(idx.sensors.map((s) => [s.id, s]));
  const doms = idx.domains;
  function domainButtons() {
    $('domains').replaceChildren(...doms.map((d) => h('button', {
      text: `${d.label} ${d.n}`, role: 'tab', 'aria-selected': String(d.id === state.domain), style: `--c:${domColor(d.id)}`, class: 'rd-dom',
      onclick: () => { state.domain = d.id; domainButtons(); list(); },
    })));
  }
  function list() {
    const q = $('search').value.trim().toLowerCase();
    const items = idx.sensors.filter((s) => (q ? (s.id + ' ' + s.label).toLowerCase().includes(q) : s.domain === state.domain));
    $('list').replaceChildren(...items.slice(0, 120).map((s) => {
      const b = h('button', {
        text: s.id, title: s.label, role: 'option', 'aria-selected': String(s.id === state.sid),
        onclick: () => select(s.id),
      });
      if (s.heldout) b.append(h('span.rd-dot', { title: 'held out', 'aria-label': 'held out' }));
      return b;
    }));
  }
  $('search').addEventListener('input', list);

  // ------------------------------------------------------------ main chart
  const chartEl = $('chart');
  const chart = echarts.init(chartEl, null, { renderer: 'canvas' });
  chartEl.style.position = 'relative';
  ctx.charts.addExpandButton(chartEl, () => chart, () => ({ title: `${$('title').textContent} · ${state.metric || ''}`, text: $('note').textContent }));
  const ro = new ResizeObserver(() => chart.resize());
  ro.observe(chartEl);
  ctx.onCleanup(() => { ro.disconnect(); chart.dispose(); });

  let hourly = null; // {x:[], mean, min, max}
  let lanePatterns = [];

  function build() {
    const s = state.sensor, mm = s.metrics.find((m) => m.m === state.metric);
    const H = state.doc.hourly[state.metric];
    const mean = unpack(H.mean, H.dec), mn = unpack(H.min, mm.dec), mx = unpack(H.max, mm.dec);
    const xs = mean.map((_, i) => (Y0 + i * 3600) * MS);
    hourly = { xs, mean, mn, mx, mm };
    const sm = small();
    // breaches
    const br = state.doc.breaches.map((b, i) => ({ b, i })).filter((o) => o.b[0] === state.metric);
    const brPts = br.map(({ b, i }) => ({
      value: [(Y0 + ((b[1] + b[2]) / 2) * 300) * MS, b[3], i],
      itemStyle: { color: b[4] === 'crit' ? C.bad : C.warn },
    }));
    // usage lane
    const use = state.doc.usage.filter((u) => u[0] === state.metric);
    const cnt = {};
    use.forEach((u) => { cnt[u[3]] = (cnt[u[3]] || 0) + 1; });
    lanePatterns = Object.entries(cnt).sort((a, b) => b[1] - a[1]);
    const pcol = {};
    lanePatterns.forEach(([p], i) => { pcol[p] = i < PAL.length ? PAL[i] : C.alt; });
    const laneData = use.map((u) => ({
      value: [(u[1] - (u[2] - 1) * 300) * MS, u[1] * MS, u[6] === 'v1' ? 0 : 1, u[3], u[4], u[5], u[6], u[2]],
      itemStyle: { color: pcol[u[3]] },
    }));
    $('patterns').replaceChildren(...(lanePatterns.length
      ? [h('span.label', { text: `Used for training · ${use.length} windows` }), ...lanePatterns.map(([p, n]) => {
        const e = h('span'); e.append(h('i', { style: `background:${pcol[p]}` }), document.createTextNode(`${String(p).replace(/_/g, ' ')} ${n}`)); return e;
      })]
      : [h('span.muted', { text: s.heldout ? 'Held out: never used for training, only for testing.' : 'No training window was cut from this metric.' })]));

    const ml = [];
    if (mm.warn != null) ml.push({ yAxis: mm.warn, name: 'warn', lineStyle: { color: C.warn, type: 'dashed' }, label: { formatter: `warn ${mm.warn}`, color: C.warn } });
    if (mm.crit != null) ml.push({ yAxis: mm.crit, name: 'crit', lineStyle: { color: C.bad, type: 'dashed' }, label: { formatter: `crit ${mm.crit}`, color: C.bad } });
    if (mm.lo_warn != null) ml.push({ yAxis: mm.lo_warn, name: 'warn low', lineStyle: { color: C.warn, type: 'dashed' }, label: { formatter: `warn < ${mm.lo_warn}`, color: C.warn } });
    if (mm.lo_crit != null) ml.push({ yAxis: mm.lo_crit, name: 'crit low', lineStyle: { color: C.bad, type: 'dashed' }, label: { formatter: `crit < ${mm.lo_crit}`, color: C.bad } });
    const mon = (k) => MT[k] * MS;
    const areas = [
      [{ name: 'train', xAxis: mon(0), itemStyle: { color: C.splitTrain }, label: { color: tok('--t-app_ux', '#6cb4f5') } }, { xAxis: mon(8) }],
      [{ name: 'dev', xAxis: mon(8), itemStyle: { color: C.splitDev }, label: { color: C.warn } }, { xAxis: mon(10) }],
      [{ name: 'test', xAxis: mon(10), itemStyle: { color: C.splitTest }, label: { color: tok('--o-pending', '#a98bf5') } }, { xAxis: MT[12] * MS }],
    ];
    const axisCommon = { axisLine: { lineStyle: { color: C.line } }, axisLabel: { color: C.muted, fontFamily: C.mono, fontSize: 10 }, splitLine: { show: false } };
    const opt = {
      animation: false, backgroundColor: 'transparent',
      textStyle: { fontFamily: C.sans, color: C.silver },
      grid: [{ left: sm ? 44 : 64, right: sm ? 12 : 28, top: 28, bottom: sm ? 150 : 140 },
        { left: sm ? 44 : 64, right: sm ? 12 : 28, height: 38, bottom: 66 }],
      xAxis: [{ type: 'time', gridIndex: 0, min: Y0 * MS, max: MT[12] * MS, ...axisCommon, splitNumber: sm ? 4 : 10 },
        { type: 'time', gridIndex: 1, min: Y0 * MS, max: MT[12] * MS, ...axisCommon, axisLabel: { show: false } }],
      yAxis: [{ type: 'value', gridIndex: 0, scale: true, name: mm.unit, nameTextStyle: { color: C.muted, fontFamily: C.mono, fontSize: 10 },
        ...axisCommon, splitLine: { lineStyle: { color: C.line } } },
      { type: 'category', gridIndex: 1, data: ['v1', 'v2'], ...axisCommon,
        axisLabel: { fontFamily: C.mono, fontSize: 10, color: (v) => (v === 'v1' ? C.v1 : C.v2) } }],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], filterMode: 'weakFilter' },
        { type: 'slider', xAxisIndex: [0, 1], bottom: 14, height: 26, filterMode: 'weakFilter', borderColor: C.line,
          fillerColor: C.accentSoft, textStyle: { color: C.muted, fontSize: 10 }, labelFormatter: (v) => fmtT(v).slice(0, 6),
          dataBackground: { lineStyle: { color: C.alt }, areaStyle: { color: 'rgba(107,110,118,0.25)' } } }],
      tooltip: {
        trigger: 'axis', confine: true, axisPointer: { type: 'line', lineStyle: { color: C.alt } },
        backgroundColor: C.panel, borderColor: C.line, textStyle: { color: C.text, fontSize: 12 },
        formatter: (ps) => {
          const p0 = ps.find((p) => p.seriesId === 'mean');
          if (!p0) return '';
          const i = p0.dataIndex;
          const d = state.five ? `5-min reading <b>${p0.value[1] ?? '–'}</b> ${esc(mm.unit)}` :
            `hour mean <b>${fmtV(hourly.mean[i])}</b> · min ${fmtV(hourly.mn[i])} · max ${fmtV(hourly.mx[i])} ${esc(mm.unit)}`;
          return `${fmtT(p0.value[0])} IST<br>${d}`;
        },
      },
      series: [
        { id: 'lo', type: 'line', xAxisIndex: 0, yAxisIndex: 0, stack: 'band', symbol: 'none', lineStyle: { opacity: 0 }, data: xs.map((x, i) => [x, mn[i]]), silent: true, tooltip: { show: false } },
        { id: 'hi', type: 'line', xAxisIndex: 0, yAxisIndex: 0, stack: 'band', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(196,198,204,0.16)' },
          data: xs.map((x, i) => [x, mx[i] == null || mn[i] == null ? null : mx[i] - mn[i]]), silent: true, tooltip: { show: false } },
        { id: 'mean', name: 'mean', type: 'line', xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', sampling: 'lttb', large: true,
          lineStyle: { color: domColor(s.domain), width: 1.2 }, itemStyle: { color: domColor(s.domain) }, data: xs.map((x, i) => [x, mean[i]]),
          markLine: { silent: true, symbol: 'none', data: ml, label: { fontFamily: C.mono, fontSize: 10, position: 'insideEndTop' } },
          markArea: { silent: true, data: areas, label: { color: C.muted, fontFamily: C.mono, fontSize: 10, position: 'insideTop' } } },
        { id: 'breach', name: 'breach', type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, symbolSize: sm ? 6 : 7, data: brPts, large: brPts.length > 2000,
          tooltip: { trigger: 'item' }, z: 5 },
        { id: 'lane', type: 'custom', xAxisIndex: 1, yAxisIndex: 1, data: laneData, encode: { x: [0, 1], y: 2 },
          renderItem: (params, api) => {
            const a = api.coord([api.value(0), api.value(2)]), b = api.coord([api.value(1), api.value(2)]);
            const hgt = api.size([0, 1])[1] * 0.7;
            return { type: 'rect', shape: { x: a[0], y: a[1] - hgt / 2, width: Math.max(b[0] - a[0], 1.5), height: hgt }, style: api.style() };
          },
          tooltip: { trigger: 'item', formatter: (p) => {
            const v = p.value;
            return `<b>${esc(String(v[3]).replace(/_/g, ' '))}</b> · ${esc(v[4])} · ${esc(v[5])} split (${esc(v[6])})<br>${fmtT(v[0])} → ${fmtT(v[1])} · ${v[7]} × 5 min`;
          } } },
      ],
    };
    chart.setOption(opt, true);
    state.five = false;
    const nb = br.length;
    $('note').textContent = nb
      ? `${nb} breaches (dots). Click one for its reason; zoom below a week for 5-min readings.`
      : 'No breach of a limit for this metric. Zoom below a week for 5-min readings.';
    chart.off('click');
    chart.on('click', (p) => { if (p.seriesId === 'breach') showBreach(p.value[2]); });
  }
  function fmtV(v) { return v == null ? '–' : +v.toFixed(hourly.mm.dec + 1); }

  function showBreach(i) {
    const b = state.doc.breaches[i];
    const t0 = (Y0 + b[1] * 300) * MS, t1 = (Y0 + (b[2] + 1) * 300) * MS;
    const body = h('div.rd-reason');
    body.append(h('p', null, ui.chip(b[4] === 'crit' ? 'critical' : 'warning', b[4] === 'crit' ? 'critical' : 'warning')),
      h('p', { text: b[5] }), h('p.muted', { text: `${fmtT(t0)} → ${fmtT(t1)} IST · peak ${b[3]} ${hourly.mm.unit}` }));
    const btn = h('button.btn.btn--solid', { text: 'Zoom to it (5-min)' });
    body.append(btn);
    const dlg = ui.modal('Breach', body);
    btn.onclick = () => {
      const pad = Math.max(DAY * MS / 2 - (t1 - t0) / 2, 3 * 3600 * MS);
      zoomTo(t0 - pad, t1 + pad);
      try { dlg && dlg.close ? dlg.close() : document.querySelector('dialog[open]')?.close(); } catch (e) { /* ignore */ }
      chartEl.scrollIntoView({ block: 'center' });
    };
  }

  function zoomTo(a, b) {
    a = Math.max(a, Y0 * MS); b = Math.min(b, MT[12] * MS);
    chart.dispatchAction({ type: 'dataZoom', startValue: a, endValue: b });
  }
  function curRange() {
    const o = chart.getOption().dataZoom[0];
    const full = [Y0 * MS, MT[12] * MS];
    const a = o.startValue ?? full[0] + (full[1] - full[0]) * (o.start ?? 0) / 100;
    const b = o.endValue ?? full[0] + (full[1] - full[0]) * (o.end ?? 100) / 100;
    return [a, b];
  }
  root.querySelectorAll('[data-zoom]').forEach((btn) => btn.addEventListener('click', () => {
    const z = btn.dataset.zoom;
    if (z === 'year') return zoomTo(Y0 * MS, MT[12] * MS);
    const [a, b] = curRange();
    let c = (a + b) / 2;
    if (b - a > 40 * DAY * MS) { // from the year view: centre on the latest breach, else the last data day
      const br = state.doc.breaches.filter((x) => x[0] === state.metric);
      c = br.length ? (Y0 + br[br.length - 1][1] * 300) * MS : c;
    }
    const w = (z === 'week' ? 7 : 1) * DAY * MS;
    zoomTo(c - w / 2, c + w / 2);
  }));

  let zt = null;
  chart.on('datazoom', () => { clearTimeout(zt); zt = setTimeout(onZoom, 180); });
  async function onZoom() {
    if (!state.sensor) return;
    const [a, b] = curRange();
    const want = b - a <= 8.5 * DAY * MS;
    if (!want) {
      if (state.five) { state.five = false; restoreHourly(); }
      return;
    }
    const sid = state.sid, metric = state.metric, mm = hourly.mm;
    const lo = a / MS - DAY, hi = b / MS + DAY;
    const months = [];
    for (let k = 0; k < 12; k++) if (MT[k + 1] > lo && MT[k] < hi && state.sensor.months.includes(k + 1)) months.push(k + 1);
    $('note').textContent = 'Loading 5-min readings…';
    const chunks = await Promise.all(months.map((k) => ctx.data.json(`raw/c/${sid}/2025-${String(k).padStart(2, '0')}.json`)));
    if (sid !== state.sid || metric !== state.metric) return;
    const pts = [];
    for (const ch of chunks) {
      const vals = unpack(ch.m[metric], mm.dec);
      for (let i = 0; i < vals.length; i++) {
        const t = ch.t0 + i * ch.step;
        if (t >= lo && t <= hi) pts.push([t * MS, vals[i]]);
      }
    }
    state.five = true;
    chart.setOption({ series: [{ id: 'lo', data: [] }, { id: 'hi', data: [] }, { id: 'mean', data: pts, sampling: null, lineStyle: { width: 1.4 } }] });
    const nOk = pts.filter((p) => p[1] != null).length;
    $('note').textContent = `5-min readings: ${nOk} of ${pts.length} slots in view filled. Zoom out past a week for the hourly band.`;
  }
  function restoreHourly() {
    const { xs, mean, mn, mx } = hourly;
    chart.setOption({ series: [
      { id: 'lo', data: xs.map((x, i) => [x, mn[i]]) },
      { id: 'hi', data: xs.map((x, i) => [x, mx[i] == null || mn[i] == null ? null : mx[i] - mn[i]]) },
      { id: 'mean', data: xs.map((x, i) => [x, mean[i]]), sampling: 'lttb', lineStyle: { width: 1.2 } }] });
    $('note').textContent = 'Hourly mean (line) and min-max band. Zoom below a week for 5-min readings.';
  }

  // ------------------------------------------------------------ select
  async function select(sid, metric) {
    const s = byId[sid];
    if (!s) return;
    state.sid = sid; state.sensor = s; state.domain = s.domain;
    state.metric = metric && s.metrics.some((m) => m.m === metric) ? metric : s.metrics[0].m;
    domainButtons(); list();
    const t = $('title');
    t.replaceChildren(document.createTextNode(s.id));
    if (s.heldout) t.append(ui.chip('held out · test only', 'warn'));
    $('sub').textContent = `${s.label} · ${s.months.length} months of data`;
    $('note').textContent = 'Loading…';
    [state.doc, state.ana] = await Promise.all([ctx.data.json(`raw/s/${sid}.json`), ctx.data.json(`raw/a/${sid}.json`)]);
    if (state.sid !== sid) return;
    metrics();
    draw();
  }
  function metrics() {
    const s = state.sensor;
    $('metrics').replaceChildren(...s.metrics.map((m) => h('button', {
      text: m.label, role: 'tab', 'aria-selected': String(m.m === state.metric), title: `${(m.cov * 100).toFixed(0)}% coverage`,
      onclick: () => { state.metric = m.m; metrics(); draw(); },
    })));
  }
  function draw() {
    const mm = state.sensor.metrics.find((m) => m.m === state.metric);
    $('sub').textContent = `${state.sensor.label} · ${mm.label}${mm.unit ? ' (' + mm.unit + ')' : ''} · ${(mm.cov * 100).toFixed(1)}% of 2025 covered · ` +
      (mm.warn != null ? `limits ${mm.dir === 'low' ? 'below' : 'above'} ${mm.warn} / ${mm.crit}` + (mm.lo_warn != null ? ` and below ${mm.lo_warn} / ${mm.lo_crit}` : '') : 'no fixed limit');
    try { history.replaceState(null, '', `#/rawdata?s=${encodeURIComponent(state.sid)}&m=${encodeURIComponent(state.metric)}`); } catch (e) { /* ignore */ }
    build();
    analysis();
  }

  // ------------------------------------------------------------ analysis panel
  const minis = [];
  ctx.onCleanup(() => minis.forEach((c) => c.dispose()));
  const tip = (ins, n, extra) => `${extra ? extra + '<br>' : ''}<span style="color:${C.accent}">${esc(ins)}</span><br><span style="color:${C.muted}">n = ${n}</span>`;
  const base = (o) => ({
    animation: false, backgroundColor: 'transparent', textStyle: { fontFamily: C.sans, color: C.silver },
    grid: { left: 40, right: 10, top: 12, bottom: 24 },
    tooltip: { confine: true, backgroundColor: C.panel, borderColor: C.line, textStyle: { color: C.text, fontSize: 12 }, extraCssText: 'max-width:280px;white-space:normal' },
    ...o,
  });
  const ax = (o) => ({ axisLine: { lineStyle: { color: C.line } }, axisLabel: { color: C.muted, fontFamily: C.mono, fontSize: 9 }, splitLine: { lineStyle: { color: C.line } }, ...o });
  function card(title, insight, wide) {
    const c = h('div.c', { 'data-title': title, 'data-insight': insight || '' });
    const d = h(`div${wide ? '.w8' : ''}`, null, h('h4', { text: title }), h('p', { text: insight }), c);
    $('analysis').append(d);
    return c;
  }
  function mini(el, opt) {
    const c = echarts.init(el, null, { renderer: 'canvas' });
    c.setOption(base(opt));
    minis.push(c);
    el.style.position = 'relative';
    ctx.charts.addExpandButton(el, () => c, () => ({ title: el.dataset.title || 'Chart', text: el.dataset.insight || '' }));
    const r = new ResizeObserver(() => c.resize()); r.observe(el); ctx.onCleanup(() => r.disconnect());
  }
  function analysis() {
    minis.splice(0).forEach((c) => c.dispose());
    $('analysis').replaceChildren();
    const A = state.ana && state.ana[state.metric];
    const mm = state.sensor.metrics.find((m) => m.m === state.metric);
    if (!A || A.error) { $('analysis').append(h('p.muted', { text: A ? 'Too few readings for an analysis.' : 'No analysis.' })); return; }
    const u = mm.unit || '';
    const n = A.n;
    // distribution
    { const D = A.dist; const cats = D.counts.map((_, i) => D.edges[i]);
      mini(card('Distribution', D.insight), { xAxis: ax({ type: 'category', data: cats, axisLabel: { color: C.muted, fontSize: 9, fontFamily: C.mono, interval: 5 } }),
        yAxis: ax({ type: 'value' }),
        tooltip: { trigger: 'axis', formatter: (ps) => { const i = ps[0].dataIndex; return tip(D.insight, n, `${D.edges[i]}–${D.edges[i + 1]} ${esc(u)}: <b>${D.counts[i]}</b> (${(D.counts[i] / n * 100).toFixed(1)}%)<br>p5 ${D.pct.p5} · p50 ${D.pct.p50} · p95 ${D.pct.p95}`); } },
        series: [{ type: 'bar', data: D.counts, itemStyle: { color: C.accent }, barCategoryGap: '8%' }] }); }
    // monthly boxplot
    { const M = A.monthly; const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      mini(card('By month (p1–p99 whiskers)', M.insight), { xAxis: ax({ type: 'category', data: mon }), yAxis: ax({ type: 'value', scale: true }),
        tooltip: { trigger: 'item', formatter: (p) => { const b = M.box[p.dataIndex]; return b ? tip(M.insight, b[5], `${mon[p.dataIndex]}: median <b>${b[2]}</b> ${esc(u)}, quartiles ${b[1]}–${b[3]}`) : ''; } },
        series: [{ type: 'boxplot', data: M.box.map((b) => (b ? b.slice(0, 5) : [])),
          itemStyle: { color: 'rgba(76,125,255,0.2)', borderColor: C.accent } }] }); }
    // heatmap hour x weekday
    { const Hm = A.heat; const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']; const data = [];
      let lo = Infinity, hi = -Infinity;
      Hm.grid.forEach((row, d) => row.forEach((v, hr) => { if (v != null) { data.push([hr, d, v]); lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
      mini(card('Hour of day × weekday', Hm.insight), { grid: { left: 36, right: 10, top: 8, bottom: 24 },
        xAxis: ax({ type: 'category', data: [...Array(24).keys()].map((x) => String(x).padStart(2, '0')), splitLine: { show: false }, axisLabel: { color: C.muted, fontSize: 9, interval: 5 } }),
        yAxis: ax({ type: 'category', data: days, splitLine: { show: false } }),
        visualMap: { show: false, min: lo, max: hi > lo ? hi : lo + 1, inRange: { color: ['#1f2433', '#2f4a8f', C.accent, '#cfdcff'] } },
        tooltip: { trigger: 'item', formatter: (p) => tip(Hm.insight, Hm.n[p.value[1]][p.value[0]], `${days[p.value[1]]} ${String(p.value[0]).padStart(2, '0')}:00 mean <b>${p.value[2]}</b> ${esc(u)}`) },
        series: [{ type: 'heatmap', data }] }); }
    const dayX = A.trend.day.map((_, i) => (Y0 + i * DAY) * MS);
    // trend
    { const Tr = A.trend;
      mini(card('Daily mean and 7-day rolling mean ± std', Tr.insight, true), { xAxis: ax({ type: 'time', splitLine: { show: false } }), yAxis: ax({ type: 'value', scale: true }),
        tooltip: { trigger: 'axis', formatter: (ps) => { const i = ps[0].dataIndex; return tip(Tr.insight, n, `${fmtT(dayX[i]).slice(0, 6)}: day mean <b>${Tr.day[i] ?? '–'}</b>, 7-day ${Tr.roll[i] ?? '–'} ± ${Tr.rstd[i] ?? '–'} ${esc(u)}`); } },
        series: [
          { type: 'line', stack: 'b', symbol: 'none', lineStyle: { opacity: 0 }, data: dayX.map((x, i) => [x, Tr.roll[i] != null && Tr.rstd[i] != null ? Tr.roll[i] - Tr.rstd[i] : null]) },
          { type: 'line', stack: 'b', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: C.accentSoft }, data: dayX.map((x, i) => [x, Tr.rstd[i] != null ? 2 * Tr.rstd[i] : null]) },
          { type: 'line', symbol: 'none', lineStyle: { color: C.alt, width: 1 }, data: dayX.map((x, i) => [x, Tr.day[i]]) },
          { type: 'line', symbol: 'none', lineStyle: { color: C.accent, width: 1.6 }, data: dayX.map((x, i) => [x, Tr.roll[i]]) }] }); }
    // coverage
    { const Cv = A.coverage;
      mini(card('Coverage per day', Cv.insight), { xAxis: ax({ type: 'time', splitLine: { show: false } }), yAxis: ax({ type: 'value', max: 100 }),
        tooltip: { trigger: 'axis', formatter: (ps) => { const i = ps[0].dataIndex; return tip(Cv.insight, Math.round(Cv.day[i] * 288), `${fmtT(dayX[i]).slice(0, 6)}: <b>${Math.round(Cv.day[i] * 100)}%</b> of 288 slots`); } },
        series: [{ type: 'bar', barWidth: '100%', data: dayX.map((x, i) => ({ value: [x, Math.round(Cv.day[i] * 100)], itemStyle: { color: Cv.day[i] >= 0.95 ? C.accent : Cv.day[i] > 0 ? C.warn : C.bad } })) }] }); }
    // breaches
    if (A.breach && A.breach.n) {
      const B = A.breach; const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      const bars = (title, cats, vals, col) => mini(card(title, B.insight), { xAxis: ax({ type: 'category', data: cats, splitLine: { show: false } }), yAxis: ax({ type: 'value', minInterval: 1 }),
        tooltip: { trigger: 'axis', formatter: (ps) => tip(B.insight, B.n, `${esc(ps[0].name)}: <b>${ps[0].value}</b> breaches (${(ps[0].value / B.n * 100).toFixed(0)}%)`) },
        series: [{ type: 'bar', data: vals, itemStyle: { color: col } }] });
      bars('Breaches by month', mon, B.by_month, C.warn);
      bars('Breach duration', B.dur_labels, B.dur, C.warn);
      bars('Breach start, hour of day', [...Array(24).keys()].map((x) => String(x).padStart(2, '0')), B.by_hour, C.warn);
    } else if (A.breach) {
      $('analysis').append(h('div', null, h('h4', { text: 'Breaches' }), h('p', { text: A.breach.insight })));
    }
    // autocorrelation
    { const Ac = A.acf;
      mini(card('Autocorrelation of hourly means', Ac.insight), { xAxis: ax({ type: 'category', data: Ac.lags.map((_, i) => i + 1 + ' h'), axisLabel: { color: C.muted, fontSize: 9, interval: 11 } }),
        yAxis: ax({ type: 'value', min: -1, max: 1 }),
        tooltip: { trigger: 'axis', formatter: (ps) => tip(Ac.insight, n, `lag ${esc(ps[0].name)}: r = <b>${ps[0].value ?? '–'}</b>`) },
        series: [{ type: 'line', symbol: 'none', data: Ac.lags, lineStyle: { color: C.accent },
          markLine: { silent: true, symbol: 'none', data: [{ xAxis: '24 h' }, { xAxis: '48 h' }], lineStyle: { color: C.alt, type: 'dashed' }, label: { show: false } } }] }); }
    // correlation list
    { const Co = A.corr || { top: [], insight: 'No correlation computed' };
      const d = h('div', null, h('h4', { text: `Related sensors, building ${Co.building || ''}` }), h('p', { text: Co.insight }));
      const ul = h('ul.rd-corr');
      Co.top.forEach((c) => {
        const li = h('li', { title: `Pearson r on hourly means, n = ${c.n} h · ${Co.insight}` });
        const a = h('a', { href: `#/rawdata?s=${encodeURIComponent(c.id)}&m=${encodeURIComponent(c.m)}`, text: `${c.id} · ${c.label}`,
          onclick: (e) => { e.preventDefault(); select(c.id, c.m); window.scrollTo({ top: 0 }); } });
        li.append(a, h('b', { text: (c.r > 0 ? '+' : '') + c.r.toFixed(2) }));
        ul.append(li);
      });
      if (!Co.top.length) ul.append(h('li.muted', { text: 'None overlaps by 2 weeks.' }));
      d.append(ul);
      $('analysis').append(d);
    }
  }

  // ------------------------------------------------------------ sankey
  const sk = idx.sankey;
  const used = T.examples_v1 + T.examples_v2;
  $('flowclaim').textContent = `${fmtN(T.real_windows)} real 4 h windows → ${fmtN(used)} training bases`;
  ctx.charts.sankey($('sankey'), {
    meta: { id: 'raw_sankey', title: 'Raw windows to training examples', unit: 'windows', n: used,
      source_files: idx.source_files, script: idx.script },
    series: [{ name: 'flow', nodes: sk.nodes.filter((x) => x.name !== 'Not used'), links: sk.links.filter((l) => l.target !== 'Not used') }],
  }, { height: 360 });

  // ------------------------------------------------------------ start
  const q = ctx.query || {};
  let first = q.s && byId[q.s] ? q.s : null;
  if (!first) {
    const aq = idx.sensors.filter((s) => s.domain === 'air_quality').sort((a, b) => (b.used + b.breaches) - (a.used + a.breaches));
    first = (aq[0] || idx.sensors[0]).id;
  }
  state.domain = byId[first].domain;
  domainButtons();
  await select(first, q.m);
  ui.next && $('next').append(ui.next('rawdata'));
}
