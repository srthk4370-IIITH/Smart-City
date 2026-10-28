// Chart kit over Apache ECharts (vendored). Every chart on the site goes through here so they all look alike.
// API and data shapes: see CHARTS.md next to this file.
//
//   import * as charts from './charts.js'      (shell)   |   ctx.charts            (page modules)
//   const h = charts.bar(el, dataset, opts)               ->  handle {ready, chart(), update(ds, opts), dispose()}
//
// Rules baked in: ours = --accent; alternatives = muted meaningful hues (chart topic first, see PALETTE_KEYS); mono axis labels,
// tooltips show value, n, 95% CI and the source file, drawn only when scrolled into view, resized with the box.

const TYPES = ['bar', 'stackedBar', 'line', 'waterfall', 'scatter', 'boxplot', 'heatmap', 'ciDot', 'sankey', 'funnel', 'timeline', 'trace'];

// ---------------------------------------------------------------- tokens
let T = null;
function tokens() {
  if (T) return T;
  const cs = getComputedStyle(document.documentElement);
  const v = (n, d) => (cs.getPropertyValue(n).trim() || d);
  T = {
    bg: v('--bg', '#141518'), panel: v('--panel', '#1c1d21'), line: v('--line', '#2a2c31'), lineStrong: v('--line-strong', '#3a3d44'),
    text: v('--text', '#e9e9ea'), silver: v('--silver', '#c4c6cc'), muted: v('--muted', '#9a9ca3'),
    accent: v('--accent', '#4c7dff'), accentText: v('--accent-text', '#7fa2ff'),
    alt: v('--alt', '#6b6e76'), alt2: v('--alt-2', '#8a8d95'), alt3: v('--alt-3', '#4f5259'),
    good: v('--good', '#3fbf7f'), warn: v('--warn', '#e0a33a'), bad: v('--bad', '#e5534b'),
    sans: v('--font-sans', 'Inter, system-ui, sans-serif'), mono: v('--font-mono', 'ui-monospace, monospace'),
  };
  const P = {};
  for (const [group, keys] of Object.entries(PALETTE_KEYS)) {
    P[group] = {};
    for (const [k, [cssVar, fallback]] of Object.entries(keys)) P[group][k] = v(cssVar, fallback);
  }
  T.pal = P;
  return T;
}

// Semantic palette: mirrors tokens.css (CSS wins when present). Ours stays --accent; colours mean something.
const PALETTE_KEYS = {
  topic: {
    latency: ['--t-latency', '#3cc8e6'], hardware: ['--t-hardware', '#f0903e'], accuracy: ['--t-accuracy', '#46c98a'],
    agent_design: ['--t-agent_design', '#a98bf5'], refinement: ['--t-refinement', '#2fc9b4'], training_v2: ['--t-training_v2', '#f2b83d'],
    dataset_v2: ['--t-dataset_v2', '#f27bbd'], app_ux: ['--t-app_ux', '#6cb4f5'], ops: ['--t-ops', '#f06e62'], timeline: ['--t-timeline', '#b9bcc4'], use_case: ['--t-use_case', '#8fb3ff'],
  },
  outcome: {
    kept: ['--o-kept', '#46c98a'], replaced: ['--o-replaced', '#f2b83d'], pending: ['--o-pending', '#a98bf5'],
    rejected: ['--o-rejected', '#d77a72'], dropped: ['--o-rejected', '#d77a72'], before: ['--o-before', '#c9867f'], after: ['--o-after', '#5fd39a'],
    better: ['--d-better', '#46c98a'], worse: ['--d-worse', '#ef6a5f'], ns: ['--d-ns', '#9a9ca3'],
  },
  severity: {
    critical: ['--sev-critical', '#f05a52'], warning: ['--sev-warning', '#f2b83d'], normal: ['--sev-normal', '#46c98a'], sensor_fault: ['--sev-fault', '#b78cf2'],
  },
  domain: {
    air: ['--dom-air', '#7cc4f5'], water: ['--dom-water', '#2fc4d8'], power: ['--dom-power', '#f0d24b'],
    weather: ['--dom-weather', '#f0903e'], occupancy: ['--dom-occupancy', '#f27bbd'], hvac: ['--dom-hvac', '#7ee8b8'],
  },
};
/** The semantic palette {topic, outcome, severity, domain} as resolved colours. */
export function palette() { return tokens().pal; }

// perceptual scales: viridis-like sequential (dark-bg friendly start), red-grey-green diverging for +/- deltas
const SEQUENTIAL = ['#2b1b4a', '#3b3f8f', '#2f6f9a', '#21998f', '#47c16e', '#b4dd3c', '#f6e83a'];
const DIVERGING = ['#e5534b', '#b4524c', '#3a3d44', '#3f8f68', '#46c98a'];
// mix a hex colour toward grey (less saturated "alternative" version of a meaningful hue)
export function mute(hex, k = 0.42, grey = '#6b6e76') {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const a = p(hex), b = p(grey);
  return '#' + a.map((x, i) => Math.round(x * (1 - k) + b[i] * k).toString(16).padStart(2, '0')).join('');
}
// topic of the chart being built (set by render() right before a builder runs; builders are synchronous)
let CUR_TOPIC = null;
const ALT_ORDER = ['hardware', 'agent_design', 'training_v2', 'dataset_v2', 'refinement', 'ops', 'latency', 'accuracy', 'app_ux'];
// series names that carry a meaning of their own (baselines, rules, other runtimes)
function semanticFor(name) {
  const n = String(name || '').toLowerCase();
  const P = tokens().pal;
  if (/\brules?\b|mode 1/.test(n)) return P.topic.hardware;
  if (/\bbase\b|baseline|status quo/.test(n)) return P.outcome.before;
  if (/genie/.test(n)) return P.topic.training_v2;
  if (/\bgpu\b|adreno|opencl/.test(n)) return P.topic.hardware;
  return null;
}
const reducedMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Colour for a series / point. `ours` wins (accent), then a named / semantic colour, then a muted meaningful hue:
 *  the chart's topic hue first, then other palette hues, all less saturated than ours. */
export function colorFor(item, greyIndex = 0) {
  const t = tokens(); const P = t.pal;
  if (!item) return t.alt;
  if (item.ours) return t.accent;
  if (item.ref) return t.muted;
  if (item.color) {
    const named = { accent: t.accent, ours: t.accent, alt: t.alt, good: t.good, warn: t.warn, bad: t.bad, muted: t.muted, silver: t.silver,
      ...P.outcome, ...P.severity };
    for (const [k, v] of Object.entries(P.domain)) named['dom:' + k] = v;
    for (const [k, v] of Object.entries(P.topic)) named['topic:' + k] = v;
    return named[item.color] || item.color;
  }
  const sem = semanticFor(item.name);
  if (sem) return mute(sem, 0.3);
  const hues = [CUR_TOPIC, ...ALT_ORDER.filter((k) => k !== CUR_TOPIC)].filter((k) => k && P.topic[k]);
  return mute(P.topic[hues[greyIndex % hues.length]], 0.42);
}

// ---------------------------------------------------------------- echarts loader
let echartsP = null;
export function ensureEcharts() {
  if (window.echarts) return Promise.resolve(window.echarts);
  if (echartsP) return echartsP;
  echartsP = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'vendor/echarts/echarts.min.js';
    s.onload = () => resolve(window.echarts);
    s.onerror = () => reject(new Error('echarts failed to load'));
    document.head.appendChild(s);
  });
  return echartsP;
}

// ---------------------------------------------------------------- helpers
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const basename = (p) => String(p || '').split(/[\\/]/).pop();

export function fmt(v, opts = {}) {
  if (v == null || v === '' || Number.isNaN(v)) return '–';
  if (typeof opts.format === 'function') return opts.format(v);
  if (typeof v !== 'number') return String(v);
  const d = opts.decimals ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : Math.abs(v) >= 1 ? 2 : 3);
  const s = new Intl.NumberFormat('en-GB', { maximumFractionDigits: d, minimumFractionDigits: 0 }).format(v);
  return opts.percent ? s + ' %' : s;
}
const withUnit = (v, unit, opts) => {
  const s = fmt(v, opts);
  if (!unit || s === '–') return s;
  return unit === '%' ? s + ' %' : `${s} ${unit}`;
};

/** Normalise any accepted dataset input into {meta, series:[{name, ours, color, data:[point]}]}. */
export function normalize(ds) {
  if (!ds) return { meta: {}, series: [] };
  if (Array.isArray(ds)) ds = { series: ds };
  const meta = ds.meta || {};
  let series = ds.series || [];
  // allow a flat list of points as series
  if (series.length && !('data' in series[0]) && !('nodes' in series[0]) && ('x' in series[0] || 'y' in series[0])) {
    series = [{ name: meta.title || 'value', data: series }];
  }
  const chart = meta.chart || {};
  series = series.map((s, i) => {
    const pts = (s.data || s.points || []).map((p) => (Array.isArray(p) ? { x: p[0], y: p[1] } : { ...p }));
    // meta.chart.x naming a point field (e.g. "agents") means: use that field as x, keep the old x as the label
    if (chart.x && pts.length && pts.every((p) => p[chart.x] !== undefined)) {
      for (const p of pts) { p.label = p.label ?? p.x; p.x = p[chart.x]; }
    }
    for (const p of pts) {
      if (!p.ci && p.lo != null && p.hi != null) p.ci = [p.lo, p.hi];
      if (p.role === 'ours') p.ours = true;
      if (p.role === 'ref') p.ref = true;
    }
    return {
      ...s,
      name: s.name ?? `series ${i + 1}`,
      ours: s.ours ?? s.role === 'ours',
      ref: s.ref ?? s.role === 'ref',
      data: pts,
    };
  });
  // merge top-level ci [{series?, x, lo, hi}] into points
  if (Array.isArray(ds.ci)) {
    for (const c of ds.ci) {
      for (const s of series) {
        if (c.series != null && c.series !== s.name) continue;
        const p = s.data.find((q) => String(q.x) === String(c.x));
        if (p && !p.ci) p.ci = [c.lo, c.hi];
      }
    }
  }
  // highlight_x: the chosen option on the x axis is "ours"
  if (chart.highlight_x != null) {
    const hx = [].concat(chart.highlight_x).map(String);
    for (const s of series) for (const p of s.data) if (hx.includes(String(p.x))) p.highlight = true;
  }
  return ds.situation ? { meta, series, situation: ds.situation } : { meta, series };
}

/** Options implied by the dataset (meta.chart, unit). Explicit opts always win. */
function impliedOpts(ds, type) {
  const meta = ds.meta || {};
  const chart = meta.chart || {};
  const pts = ds.series[0]?.data || [];
  const o = {};
  const isField = (k) => k && pts.length && pts[0][k] !== undefined;
  if (chart.x && type !== 'heatmap') o.xName = chart.x;
  if (chart.y && !isField(chart.y) && type !== 'heatmap') o.yName = chart.y;
  if (chart.log_y) o.logY = true;
  if (chart.highlight_x != null) o.highlightX = [].concat(chart.highlight_x).map(String);
  if (type === 'heatmap' && chart.y) o.rowField = chart.y;
  return o;
}

/** unit "fraction" is shown as percent (values x100), everything else as is. */
const SCALE_KEYS = ['y', 'v', 'min', 'max', 'q1', 'q3', 'median', 'mean', 'lo', 'hi'];
function asPercent(ds) {
  for (const s of ds.series) if (s.unit === 'fraction') s.unit = '%';
  for (const s of ds.series) for (const p of s.data || []) {
    for (const k of SCALE_KEYS) if (typeof p[k] === 'number') p[k] = +(p[k] * 100).toFixed(4);
    if (p.ci) p.ci = p.ci.map((v) => (typeof v === 'number' ? +(v * 100).toFixed(4) : v));
  }
  ds.meta = { ...ds.meta, unit: '%' };
  return ds;
}

function categoriesOf(series, order) {
  if (order) return order.slice();
  const seen = new Set();
  const out = [];
  for (const s of series) for (const p of s.data) { const k = String(p.x); if (!seen.has(k)) { seen.add(k); out.push(k); } }
  return out;
}

function sourceLine(meta, p) {
  const files = (p && p.source) ? [p.source] : (meta.source_files || []);
  const parts = [];
  if (files.length) parts.push(esc(basename(files[0])) + (files.length > 1 ? ` +${files.length - 1}` : ''));
  if (meta.script) parts.push(esc(basename(meta.script)));
  return parts.length ? `<div class="ct-src">source · ${parts.join(' · ')}</div>` : '';
}

function tipHTML({ title, rows, meta, point }) {
  const r = rows.filter(Boolean).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join('');
  return `<div class="ct-tip"><div class="ct-title">${esc(title)}</div><table>${r}</table>${point && point.note ? `<div class="ct-note">${esc(point.note)}</div>` : ''}${sourceLine(meta || {}, point)}</div>`;
}

function pointRows(p, unit, opts, label = 'value') {
  const n = p.n ?? null;
  return [
    [label, `<b>${esc(withUnit(p.y, unit, opts))}</b>`],
    p.ci ? ['95% CI', esc(`${fmt(p.ci[0], opts)} – ${withUnit(p.ci[1], unit, opts)}`)] : null,
    n != null ? ['n', esc(p.k != null ? `${fmt(p.k, { decimals: 0 })} / ${fmt(n, { decimals: 0 })}` : fmt(n, { decimals: 0 }))] : null,
  ];
}

function baseOption(meta, opts) {
  const t = tokens();
  const axisLabel = { color: t.muted, fontFamily: t.mono, fontSize: 11 };
  return {
    backgroundColor: 'transparent',
    animation: !reducedMotion(),
    animationDuration: 350,
    animationEasing: 'cubicOut',
    aria: { enabled: true, decal: { show: false } },
    textStyle: { fontFamily: t.sans, color: t.silver },
    grid: { left: 6, right: 18, top: opts.legend === false ? 30 : 56, bottom: 6, containLabel: true },
    tooltip: {
      trigger: 'item', confine: true, appendToBody: false,
      backgroundColor: '#f1f1f2', borderWidth: 0, padding: [9, 11],
      textStyle: { color: '#141518', fontFamily: t.sans, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.45);max-width:320px;white-space:normal;',
    },
    legend: {
      show: opts.legend !== false, top: 0, left: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10,
      textStyle: { color: t.silver, fontFamily: t.mono, fontSize: 11 }, inactiveColor: t.alt3,
    },
    _axisLabel: axisLabel,
  };
}
function valueAxis(opts, meta, extra = {}) {
  const t = tokens();
  const name = opts.yName ?? (opts.unit || meta.unit || '');
  return {
    type: opts.logY ? 'log' : 'value', min: opts.yMin, max: opts.yMax, scale: !!opts.scale,
    name, nameGap: 12, nameTextStyle: { color: t.muted, fontFamily: t.mono, fontSize: 10, align: 'left', padding: [0, 0, 0, -4] },
    axisLabel: { color: t.muted, fontFamily: t.mono, fontSize: 11, formatter: (v) => fmt(v, { ...opts, decimals: opts.axisDecimals }) },
    splitLine: { lineStyle: { color: t.line, type: [3, 4] } }, axisLine: { show: false }, axisTick: { show: false },
    ...extra,
  };
}
function categoryAxis(cats, opts, narrow, extra = {}) {
  const t = tokens();
  return {
    type: 'category', data: cats, name: opts.xName || '',
    nameTextStyle: { color: t.muted, fontFamily: t.mono, fontSize: 10 },
    axisLabel: {
      color: t.silver, fontFamily: t.mono, fontSize: 11, interval: 0, hideOverlap: true,
      width: narrow ? 90 : 140, overflow: 'truncate',
    },
    axisLine: { lineStyle: { color: t.lineStrong } }, axisTick: { show: false },
    ...extra,
  };
}
function markLineFor(opts) {
  const t = tokens();
  const lines = [].concat(opts.markLine || []).filter(Boolean);
  const vx = [].concat(opts._vx || []).filter((v) => v != null);
  if (!lines.length && !vx.length) return undefined;
  return {
    symbol: 'none', silent: true,
    lineStyle: { color: t.muted, type: [4, 4], width: 1 },
    label: { color: t.silver, fontFamily: t.mono, fontSize: 10, formatter: (p) => p.data.name || '' },
    data: [
      ...lines.map((m) => (opts._horizontal ? { xAxis: m.y ?? m.value, name: m.label } : { yAxis: m.y ?? m.value, name: m.label })),
      ...vx.map((x) => ({ xAxis: String(x), name: String(x), lineStyle: { color: t.accent, type: [4, 4], width: 1 }, label: { color: t.accentText, position: 'end' } })),
    ],
  };
}

// whisker renderer for CI error bars on category charts
function whiskerSeries({ cats, ciPoints, horizontal, k = 1, idx = 0, color, gapCat = 0.35, gapBar = 0.2 }) {
  return {
    type: 'custom', silent: true, z: 10, tooltip: { show: false },
    renderItem(params, api) {
      const ci = api.value(1), hi = api.value(2), ci0 = api.value(0);
      const lo = ci;
      const band = horizontal ? api.size([0, 1])[1] : api.size([1, 0])[0];
      const inner = band * (1 - gapCat);
      const w = inner / (k + gapBar * (k - 1));
      const off = -inner / 2 + idx * w * (1 + gapBar) + w / 2;
      const cap = Math.max(4, Math.min(10, w * 0.3));
      let a, b;
      if (horizontal) { a = api.coord([lo, ci0]); b = api.coord([hi, ci0]); a[1] += off; b[1] += off; }
      else { a = api.coord([ci0, lo]); b = api.coord([ci0, hi]); a[0] += off; b[0] += off; }
      const style = { stroke: color, lineWidth: 1.5 };
      const children = horizontal
        ? [{ type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style },
           { type: 'line', shape: { x1: a[0], y1: a[1] - cap / 2, x2: a[0], y2: a[1] + cap / 2 }, style },
           { type: 'line', shape: { x1: b[0], y1: b[1] - cap / 2, x2: b[0], y2: b[1] + cap / 2 }, style }]
        : [{ type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style },
           { type: 'line', shape: { x1: a[0] - cap / 2, y1: a[1], x2: a[0] + cap / 2, y2: a[1] }, style },
           { type: 'line', shape: { x1: b[0] - cap / 2, y1: b[1], x2: b[0] + cap / 2, y2: b[1] }, style }];
      return { type: 'group', children };
    },
    encode: horizontal ? { y: 0, x: [1, 2] } : { x: 0, y: [1, 2] },
    data: ciPoints.map((p) => [cats.indexOf(String(p.x)), p.ci[0], p.ci[1]]),
  };
}

// ---------------------------------------------------------------- builders (return an ECharts option)
const builders = {
  bar(ds, opts, ctx) { return barLike(ds, opts, ctx, false); },
  stackedBar(ds, opts, ctx) { return barLike(ds, opts, ctx, true); },

  line(ds, opts) {
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, opts);
    const unit = opts.unit ?? meta.unit;
    const first = series[0]?.data[0]?.x;
    const xType = opts.xType || (typeof first === 'number' ? 'value' : /^\d{4}-\d{2}-\d{2}/.test(String(first)) ? 'time' : 'category');
    const cats = xType === 'category' ? categoriesOf(series, opts.order) : null;
    let grey = 0;
    const out = [];
    series.forEach((s, si) => {
      const color = s.ours || s.color || s.ref ? colorFor(s) : colorFor(s, grey++);
      const xy = (p) => (xType === 'category' ? [String(p.x), p.y] : [p.x, p.y]);
      if (s.data.some((p) => p.ci)) {
        const band = s.data.filter((p) => p.ci && p.ci[0] != null && p.ci[1] != null);
        out.push({
          type: 'custom', name: s.name, silent: true, z: 1, tooltip: { show: false },
          data: [[0]],
          renderItem(params, api) {
            const X = (p) => (xType === 'category' ? String(p.x) : p.x);
            const top = band.map((p) => api.coord([X(p), p.ci[1]]));
            const bot = band.map((p) => api.coord([X(p), p.ci[0]])).reverse();
            return { type: 'polygon', shape: { points: top.concat(bot) }, style: { fill: color, opacity: 0.16 } };
          },
        });
      }
      out.push({
        type: 'line', name: s.name, data: s.data.map((p) => ({ value: xy(p), _p: p, symbolSize: p.highlight ? 11 : (s.dots ? 10 : 6), itemStyle: p.highlight ? { color: t.accent, borderColor: t.text, borderWidth: 1.5 } : undefined })),
        smooth: false, showSymbol: s.data.length <= 40 || s.data.some((p) => p.highlight), symbolSize: 6,
        lineStyle: s.dots ? { width: 0, opacity: 0 } : { color, width: s.ours ? 2.5 : 1.8, type: s.dashed || s.ref ? 'dashed' : 'solid' }, itemStyle: { color },
        ...(s.dots ? { symbol: 'emptyCircle', showSymbol: true, symbolSize: 10, emphasis: { lineStyle: { width: 0 } } } : {}),
        step: s.step || opts.step || false, z: s.ours ? 5 : 3,
        markLine: si === 0 ? markLineFor({ ...opts, _vx: xType === 'category' ? opts.highlightX : null }) : undefined,
        areaStyle: opts.area ? { color, opacity: 0.12 } : undefined,
      });
    });
    o.legend.data = series.map((s) => s.name);
    o.xAxis = xType === 'category' ? categoryAxis(cats, opts, ctx_narrow(opts)) : {
      type: xType, name: opts.xName || '', nameTextStyle: { color: t.muted, fontFamily: t.mono, fontSize: 10 },
      axisLabel: { color: t.muted, fontFamily: t.mono, fontSize: 11, hideOverlap: true }, axisLine: { lineStyle: { color: t.lineStrong } },
      splitLine: { show: false }, min: opts.xMin, max: opts.xMax, scale: true,
    };
    o.yAxis = valueAxis(opts, meta);
    o.series = out;
    o.tooltip.trigger = 'item';
    o.tooltip.formatter = (prm) => {
      const p = prm.data && prm.data._p; if (!p) return '';
      return tipHTML({ title: `${prm.seriesName} · ${p.label ?? p.x}`, rows: pointRows(p, unit, opts), meta, point: p });
    };
    return o;
  },

  scatter(ds, opts) {
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, opts);
    const unit = opts.unit ?? meta.unit;
    let grey = 0;
    const catX = series.some((s) => s.data.some((p) => typeof p.x !== 'number'));
    const cats = catX ? categoriesOf(series, opts.order) : null;
    o.series = series.map((s) => {
      const base = s.ours || s.color || s.ref ? colorFor(s) : colorFor(s, grey++);
      return {
        type: 'scatter', name: s.name, itemStyle: { color: base }, symbolSize: (v, prm) => (prm.data._p.size ? Math.max(5, Math.min(30, prm.data._p.size)) : 9),
        data: s.data.map((p) => ({ value: [catX ? String(p.x) : p.x, p.y], _p: p, itemStyle: { color: p.ours || p.highlight ? t.accent : p.color ? colorFor(p) : base, opacity: 0.9 } })),
        z: s.ours ? 5 : 3,
        label: { show: !!opts.labels, formatter: (prm) => prm.data._p.label || '', position: 'right', color: t.silver, fontFamily: t.mono, fontSize: 10 },
      };
    });
    if (opts.diagonal) {
      o.series.push({ type: 'line', data: opts.diagonal, symbol: 'none', silent: true, tooltip: { show: false }, lineStyle: { color: t.muted, type: [4, 4], width: 1 } });
    }
    o.legend.data = series.map((s) => s.name);
    o.xAxis = catX ? categoryAxis(cats, opts, ctx_narrow(opts)) : valueAxis({ ...opts, yName: opts.xName ?? '', logY: opts.logX, yMin: opts.xMin, yMax: opts.xMax, scale: true }, meta, { splitLine: { show: false }, axisLine: { show: true, lineStyle: { color: t.lineStrong } } });
    if (!catX) { o.xAxis.nameLocation = 'middle'; o.xAxis.nameGap = 26; o.grid.bottom = 22; }
    o.yAxis = valueAxis({ ...opts, scale: true }, meta);
    o.tooltip.formatter = (prm) => {
      const p = prm.data && prm.data._p; if (!p) return '';
      return tipHTML({ title: p.label || prm.seriesName, rows: [[opts.xName || 'x', esc(fmt(p.x, opts))], ...pointRows(p, unit, opts, opts.yName || 'y')], meta, point: p });
    };
    return o;
  },

  waterfall(ds, opts) {
    // series[0].data: [{x, y, kind:'total'|'delta', ours?}]  totals are absolute, deltas are changes.
    // Without any `kind`, points are LEVELS (each y is the value after that step): first and last are totals,
    // the steps in between float from the previous level. Several series -> drawn as a category line instead.
    if (ds.series.length > 1) return builders.line(ds, { ...opts, xType: 'category' });
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, { ...opts, legend: false });
    const unit = opts.unit ?? meta.unit;
    let pts = series[0]?.data || [];
    const levels = !pts.some((p) => p.kind);
    const higherBetter = opts.higherIsBetter ?? (unit === '%');
    if (levels && pts.length) {
      pts = pts.map((p, i) => {
        if (i === 0) return { ...p, kind: 'total', _level: p.y };
        const d = p.y - pts[i - 1].y;
        if (i === pts.length - 1) return { ...p, kind: 'total', ours: p.ours ?? (series[0].ours && p.role !== 'alt'), _level: p.y, _delta: d };
        return { ...p, y: d, kind: 'delta', _level: p.y, _delta: d };
      });
    }
    const cats = pts.map((p) => String(p.x));
    let run = 0;
    const base = [], vis = [];
    pts.forEach((p, i) => {
      const kind = p.kind || (i === 0 ? 'total' : 'delta');
      if (kind === 'total') {
        const v = p.y ?? run; run = v;
        base.push(0);
        const isLast = i === pts.length - 1;
        vis.push({ value: v, _p: { ...p, y: v }, _kind: 'total', itemStyle: { color: p.ours || (isLast && p.ours !== false && p.role !== 'alt') ? t.accent : mute(t.pal.outcome.before, 0.25) } });
      } else {
        const start = run; run = start + p.y;
        base.push(Math.min(start, run));
        const better = higherBetter ? p.y >= 0 : p.y <= 0;
        const col = p.color ? colorFor(p) : p.role === 'alt' ? t.alt : p.ours ? t.accent : better ? t.pal.outcome.better : t.pal.outcome.worse;
        vis.push({ value: Math.abs(p.y), _p: p, _kind: 'delta', _from: start, _to: run, itemStyle: { color: col, opacity: better ? 0.8 : 0.95 } });
      }
    });
    const horiz = !!opts.horizontal;
    o.grid.top = 16;
    const catAx = categoryAxis(cats, opts, ctx_narrow(opts), horiz ? { inverse: true } : {});
    const valAx = valueAxis(opts, meta);
    o.xAxis = horiz ? valAx : catAx;
    o.yAxis = horiz ? catAx : valAx;
    o.series = [
      { type: 'bar', stack: 'wf', data: base, itemStyle: { color: 'transparent' }, silent: true, tooltip: { show: false }, emphasis: { disabled: true } },
      {
        type: 'bar', stack: 'wf', data: vis, barCategoryGap: '30%',
        label: {
          show: opts.labels !== false, position: horiz ? 'right' : 'top', color: t.silver, fontFamily: t.mono, fontSize: 10,
          formatter: (prm) => (prm.data._kind === 'total' ? fmt(prm.data.value, opts) : (prm.data._p.y > 0 ? '+' : prm.data._p.y < 0 ? '−' : '±') + fmt(Math.abs(prm.data._p.y), opts)),
        },
        markLine: markLineFor({ ...opts, _horizontal: horiz }),
      },
    ];
    o.tooltip.formatter = (prm) => {
      const d = prm.data; if (!d || !d._p) return '';
      const p = d._p;
      const sign = (v) => (v > 0 ? '+' : v < 0 ? '−' : '±') + withUnit(Math.abs(v), unit, opts);
      if (p._level != null) {
        const rows = [['value', `<b>${esc(withUnit(p._level, unit, opts))}</b>`], p._delta != null ? ['change', esc(sign(p._delta))] : null,
          ...pointRows({ ...p, y: p._level }, unit, opts).slice(1)];
        return tipHTML({ title: p.label || p.x, rows, meta, point: p });
      }
      const rows = d._kind === 'total'
        ? pointRows(p, unit, opts, 'total')
        : [['change', `<b>${esc((p.y > 0 ? '+' : '−') + withUnit(Math.abs(p.y), unit, opts))}</b>`], ['after', esc(withUnit(d._to, unit, opts))],
           p.ci ? ['95% CI', esc(`${fmt(p.ci[0], opts)} – ${withUnit(p.ci[1], unit, opts)}`)] : null, p.n != null ? ['n', esc(fmt(p.n, { decimals: 0 }))] : null];
      return tipHTML({ title: p.label || p.x, rows, meta, point: p });
    };
    return o;
  },

  boxplot(ds, opts) {
    // series[i].data: [{x, min, q1, median, q3, max, n?, mean?, ours?}]
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, opts);
    const unit = opts.unit ?? meta.unit;
    const cats = categoriesOf(series, opts.order);
    let grey = 0;
    o.series = series.map((s) => {
      const c = s.ours || s.color ? colorFor(s) : colorFor(s, grey++);
      return {
        type: 'boxplot', name: s.name, itemStyle: { color: hexA(c, 0.25), borderColor: c }, boxWidth: ['30%', '60%'],
        data: cats.map((k) => {
          const p = s.data.find((q) => String(q.x) === k);
          if (!p) return { value: [] };
          const col = p.ours || p.highlight ? t.accent : p.color ? colorFor(p) : c;
          const med = p.median ?? p.y;
          const q1 = p.q1 ?? p.p25 ?? med, q3 = p.q3 ?? p.p75 ?? med;
          p.median = med; p._q1 = q1; p._q3 = q3;
          return { value: [p.min ?? q1, q1, med, q3, p.max ?? q3], _p: p, itemStyle: { color: hexA(col, 0.25), borderColor: col, borderWidth: 1.5 } };
        }),
      };
    });
    o.legend.show = opts.legend ?? series.length > 1;
    o.xAxis = categoryAxis(cats, opts, ctx_narrow(opts));
    o.yAxis = valueAxis(opts, meta);
    if (opts.markLine) o.series[0].markLine = markLineFor(opts);
    o.tooltip.formatter = (prm) => {
      const p = prm.data && prm.data._p; if (!p) return '';
      return tipHTML({
        title: `${series.length > 1 ? prm.seriesName + ' · ' : ''}${p.x}`, meta, point: p,
        rows: [['median', `<b>${esc(withUnit(p.median, unit, opts))}</b>`], p.q1 != null || p.p25 != null ? ['IQR', esc(`${fmt(p._q1, opts)} – ${fmt(p._q3, opts)}`)] : null, ['range', esc(`${fmt(p.min, opts)} – ${fmt(p.max, opts)}`)],
          p.mean != null ? ['mean', esc(withUnit(p.mean, unit, opts))] : null, p.ci ? ['95% CI', esc(`${fmt(p.ci[0], opts)} – ${fmt(p.ci[1], opts)}`)] : null, p.n != null ? ['n', esc(fmt(p.n, { decimals: 0 }))] : null],
      });
    };
    return o;
  },

  heatmap(ds, opts) {
    // series[0].data: [{x, y, v, n?}]
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, { ...opts, legend: false });
    const unit = opts.unit ?? meta.unit;
    // cells: {x, y:row, v} or the data contract's {x, y:value, <rowField>:row} or one row per series
    const pts = [];
    for (const s of series) for (const p of s.data) {
      if (p.v !== undefined) pts.push({ ...p, _row: p.y });
      else if (opts.rowField && p[opts.rowField] !== undefined) pts.push({ ...p, v: p.y, _row: p[opts.rowField] });
      else pts.push({ ...p, v: p.y, _row: s.name });
    }
    for (const p of pts) p.y = p._row;
    const xs = opts.xOrder || [...new Set(pts.map((p) => String(p.x)))];
    const ys = opts.yOrder || [...new Set(pts.map((p) => String(p.y)))];
    const vals = pts.map((p) => p.v).filter((v) => typeof v === 'number');
    const min = opts.vMin ?? Math.min(...vals), max = opts.vMax ?? Math.max(...vals);
    o.grid = { left: 6, right: 12, top: 10, bottom: 46, containLabel: true };
    o.xAxis = categoryAxis(xs, opts, ctx_narrow(opts), { splitArea: { show: false } });
    o.yAxis = categoryAxis(ys, opts, ctx_narrow(opts), { axisLine: { show: false } });
    o.visualMap = {
      min, max, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 140, itemWidth: 10,
      inRange: { color: opts.diverging ? DIVERGING.slice() : (opts.reverse ? SEQUENTIAL.slice().reverse() : SEQUENTIAL.slice()) },
      textStyle: { color: t.muted, fontFamily: t.mono, fontSize: 10 }, formatter: (v) => fmt(v, opts),
    };
    o.series = [{
      type: 'heatmap',
      data: pts.map((p) => ({ value: [xs.indexOf(String(p.x)), ys.indexOf(String(p.y)), p.v], _p: p })),
      label: { show: opts.labels ?? pts.length <= 64, color: t.text, fontFamily: t.mono, fontSize: 10, formatter: (prm) => fmt(prm.data._p.v, opts) },
      itemStyle: { borderColor: t.bg, borderWidth: 2, borderRadius: 3 },
      emphasis: { itemStyle: { borderColor: t.text, borderWidth: 1 } },
    }];
    o.tooltip.formatter = (prm) => {
      const p = prm.data._p;
      return tipHTML({ title: `${p.x} · ${p.y}`, meta, point: p, rows: [['value', `<b>${esc(withUnit(p.v, unit, opts))}</b>`], p.ci ? ['95% CI', esc(`${fmt(p.ci[0], opts)} – ${fmt(p.ci[1], opts)}`)] : null, p.n != null ? ['n', esc(fmt(p.n, { decimals: 0 }))] : null] });
    };
    return o;
  },

  ciDot(ds, opts) {
    // point estimate + 95% CI, one row per item. series[i].data: [{x:label, y, ci:[lo,hi], n, ours?}]
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, opts);
    const unit = opts.unit ?? meta.unit;
    const cats = categoriesOf(series, opts.order);
    const k = series.length;
    o.legend.show = opts.legend ?? k > 1;
    o.grid.top = o.legend.show ? 40 : 12;
    o.yAxis = categoryAxis(cats, opts, ctx_narrow(opts), { inverse: true, axisLine: { show: false } });
    o.xAxis = valueAxis({ ...opts, scale: opts.scale ?? true }, meta, { name: opts.xName ?? (unit || ''), nameLocation: 'end' });
    o.yAxis.name = '';
    let grey = 0;
    const out = [];
    series.forEach((s, si) => {
      const c = s.ours || s.color ? colorFor(s) : colorFor(s, grey++);
      const off = (si - (k - 1) / 2) * 12;
      out.push({
        type: 'scatter', name: s.name, itemStyle: { color: c }, symbolSize: 11, z: 5, symbolOffset: [0, off],
        data: s.data.map((p) => ({ value: [p.y, String(p.x)], _p: p, itemStyle: { color: p.ours ? t.accent : p.color ? colorFor(p) : c } })),
        markLine: si === 0 && opts.ref != null ? { symbol: 'none', silent: true, lineStyle: { color: t.muted, type: [4, 4] }, label: { color: t.silver, fontFamily: t.mono, fontSize: 10, formatter: opts.refLabel || '' }, data: [{ xAxis: opts.ref }] } : undefined,
      });
      const ciPts = s.data.filter((p) => p.ci);
      if (ciPts.length) {
        out.push({
          type: 'custom', silent: true, z: 4, tooltip: { show: false },
          renderItem(params, api) {
            const a = api.coord([api.value(1), api.value(0)]); const b = api.coord([api.value(2), api.value(0)]);
            a[1] += off; b[1] += off;
            const col = api.value(3) ? t.accent : c;
            const style = { stroke: col, lineWidth: 2, opacity: 0.85 };
            return { type: 'group', children: [
              { type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style },
              { type: 'line', shape: { x1: a[0], y1: a[1] - 5, x2: a[0], y2: a[1] + 5 }, style },
              { type: 'line', shape: { x1: b[0], y1: b[1] - 5, x2: b[0], y2: b[1] + 5 }, style }] };
          },
          encode: { y: 0, x: [1, 2] },
          data: ciPts.map((p) => [cats.indexOf(String(p.x)), p.ci[0], p.ci[1], p.ours ? 1 : 0]),
        });
      }
    });
    o.series = out;
    o.tooltip.formatter = (prm) => {
      const p = prm.data && prm.data._p; if (!p) return '';
      return tipHTML({ title: `${k > 1 ? prm.seriesName + ' · ' : ''}${p.label ?? p.x}`, rows: pointRows(p, unit, opts, opts.valueLabel || 'estimate'), meta, point: p });
    };
    return o;
  },

  sankey(ds, opts) {
    // series[0] = {nodes:[{name, ours?, color?}], links:[{source, target, value, n?}]}
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, { ...opts, legend: false });
    const s = series[0] || { nodes: [], links: [] };
    const unit = opts.unit ?? meta.unit;
    o.series = [{
      type: 'sankey', left: 4, right: ctx_narrow(opts) ? 70 : 120, top: 8, bottom: 8, nodeGap: 12, nodeWidth: 12, draggable: false,
      orient: opts.vertical ? 'vertical' : 'horizontal',
      data: (s.nodes || []).map((n, i) => ({ name: n.name, itemStyle: { color: n.ours ? t.accent : n.color ? colorFor(n) : colorFor({}, i % 3), borderWidth: 0 } })),
      links: (s.links || []).map((l) => ({ ...l, _p: l })),
      lineStyle: { color: 'source', opacity: 0.28, curveness: 0.5 },
      label: { color: t.silver, fontFamily: t.mono, fontSize: 11 },
      emphasis: { focus: 'adjacency' },
    }];
    o.tooltip.formatter = (prm) => {
      if (prm.dataType === 'edge') {
        const l = prm.data;
        return tipHTML({ title: `${l.source} → ${l.target}`, meta, point: l, rows: [['value', `<b>${esc(withUnit(l.value, unit, opts))}</b>`], l.n != null ? ['n', esc(fmt(l.n, { decimals: 0 }))] : null] });
      }
      return tipHTML({ title: prm.name, meta, rows: [['total', `<b>${esc(withUnit(prm.value, unit, opts))}</b>`]] });
    };
    return o;
  },

  funnel(ds, opts) {
    // series[0].data: [{x:stage, y, n?, ours?}]
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, { ...opts, legend: false });
    const unit = opts.unit ?? meta.unit;
    const pts = series[0]?.data || [];
    const maxV = Math.max(...pts.map((p) => p.y));
    o.series = [{
      type: 'funnel', left: '4%', right: '4%', top: 8, bottom: 8, minSize: '18%', sort: opts.sort || 'none', gap: 3,
      data: pts.map((p, i) => ({ name: String(p.x), value: p.y, _p: p, itemStyle: { color: p.ours ? t.accent : p.color ? colorFor(p) : colorFor({}, i % 3), borderWidth: 0 } })),
      label: { show: true, position: 'inside', color: t.text, fontFamily: t.mono, fontSize: 11, formatter: (prm) => `${prm.name}  ${fmt(prm.value, opts)}` },
      max: maxV,
    }];
    o.tooltip.formatter = (prm) => tipHTML({ title: prm.name, meta, point: prm.data._p, rows: pointRows(prm.data._p, unit, opts) });
    return o;
  },

  trace(ds, opts) {
    // Sensor trace around one incident (data/situations/*): x = hours from the alert (sensor time).
    // One series -> real values + warning/critical limits; several -> each line scaled to its own range (tooltip shows real values).
    const { meta, series } = ds; const t = tokens(); const P = t.pal;
    const sit = ds.situation || opts.situation || {};
    const multi = series.length > 1;
    const showLegend = multi && series.length <= 4;
    const o = baseOption(meta, { ...opts, legend: showLegend });
    const narrow = ctx_narrow(opts);
    const sevC = (v) => (v && P.severity[v]) || t.silver;
    const stageOf = (k) => (sit.stages || []).find((x) => x.key === k) || {};
    const xs = series.flatMap((s) => s.data.map((p) => p.x));
    const xMax = xs.length ? Math.max(...xs) : 0, xMin = xs.length ? Math.min(...xs) : 0;
    const scale = series.map((s) => {
      const ys = s.data.map((p) => p.y).filter((v) => typeof v === 'number');
      const lo = Math.min(...ys), hi = Math.max(...ys);
      return { lo, span: hi - lo || 1 };
    });
    const Y = (si, y) => (multi ? (y - scale[si].lo) / scale[si].span : y);
    const unitOf = (s) => { const m = /\(([^)]*)\)\s*$/.exec(s.name || ''); return m ? m[1] : (meta.unit || ''); };
    const at = (s, x) => s.data.reduce((b, p) => (Math.abs(p.x - x) < Math.abs(b.x - x) ? p : b), s.data[0]);
    const out = series.map((s, si) => {
      const c = multi ? (P.domain[s.domain] || t.silver) : t.accent;
      return {
        type: 'line', name: s.name, showSymbol: false, symbolSize: 5, smooth: false, z: 3,
        lineStyle: { color: c, width: multi ? 1.5 : 2.2, opacity: multi && series.length > 4 ? 0.8 : 1 }, itemStyle: { color: c },
        data: s.data.map((p) => ({ value: [p.x, Y(si, p.y)], _p: p })),
      };
    });
    const earlySev = stageOf('early').severity || 'warning';
    const lines = [];
    const lab = (txt, color, pos) => ({ formatter: txt, color, fontFamily: t.mono, fontSize: 10, position: pos });
    if (sit.start_h != null) lines.push({ xAxis: sit.start_h, lineStyle: { color: t.muted, type: [3, 3] }, label: lab(narrow ? 'start' : 'event starts', t.muted, 'insideStartTop') });
    lines.push({ xAxis: 0, lineStyle: { color: sevC(earlySev), type: 'solid', width: 1.5 }, label: lab('alert', sevC(earlySev), 'insideStartTop') });
    for (const [k, x] of [['1.5h', 1.5], ['3h', 3]]) {
      if (xMax >= x - 0.01) lines.push({ xAxis: x, lineStyle: { color: sevC(stageOf(k).severity), type: [5, 4] }, label: lab(x + ' h', sevC(stageOf(k).severity), 'insideStartTop') });
    }
    if (!multi && sit.limits) {
      lines.push({ yAxis: sit.limits.warning, lineStyle: { color: P.severity.warning, type: [6, 4] }, label: lab('warning ' + sit.limits.warning, P.severity.warning, 'insideEndBottom') });
      lines.push({ yAxis: sit.limits.critical, lineStyle: { color: P.severity.critical, type: [6, 4] }, label: lab('critical ' + sit.limits.critical, P.severity.critical, 'insideEndBottom') });
    }
    if (out[0]) {
      out[0].markLine = { symbol: 'none', silent: true, data: lines, animation: false };
      const a0 = sit.start_before_view ? xMin : sit.start_h;
      if (a0 != null && a0 < 0) out[0].markArea = { silent: true, itemStyle: { color: hexA(sevC(earlySev), 0.09) }, data: [[{ xAxis: a0 }, { xAxis: 0 }]] };
    }
    // markers: the alert and each refined re-read, on the first trace, coloured by the severity at that stage
    const marks = [['early', 0], ['1.5h', 1.5], ['3h', 3]].filter(([, x]) => series[0] && xMax >= x - 0.01);
    if (marks.length) {
      out.push({
        type: 'scatter', name: 'stages', z: 6, tooltip: { show: false }, silent: true,
        data: marks.map(([k, x]) => {
          const p = at(series[0], x);
          const c = sevC(stageOf(k).severity || (k === 'early' ? earlySev : null));
          return { value: [p.x, Y(0, p.y)], symbolSize: 11, itemStyle: { color: c, borderColor: t.bg, borderWidth: 2 } };
        }),
      });
    }
    o.legend.data = showLegend ? series.map((s) => s.name) : [];
    o.grid = { left: 14, right: 14, top: showLegend ? 52 : 26, bottom: 6, containLabel: true };
    o.xAxis = {
      type: 'value', min: Math.floor(xMin), max: xMax > 0 ? Math.ceil(xMax) : 0.3, interval: narrow ? 2 : 1,
      axisLabel: { color: t.muted, fontFamily: t.mono, fontSize: 10, showMaxLabel: xMax > 0, formatter: (v) => (v > 0 ? '+' : '') + v + ' h' },
      axisLine: { lineStyle: { color: t.lineStrong } }, splitLine: { show: false },
    };
    o.yAxis = multi
      ? { type: 'value', min: -0.05, max: 1.1, axisLabel: { show: false }, splitLine: { show: false }, axisLine: { show: false }, axisTick: { show: false } }
      : valueAxis({ ...opts, scale: true, yName: unitOf(series[0] || {}) }, meta);
    o.series = out;
    o.tooltip.trigger = 'axis';
    o.tooltip.axisPointer = { type: 'line', lineStyle: { color: t.muted, type: 'dashed' } };
    o.tooltip.formatter = (arr) => {
      const ps = [].concat(arr).filter((q) => q.data && q.data._p);
      if (!ps.length) return '';
      const min = Math.round(ps[0].data._p.x * 60);
      const rows = ps.slice(0, 8).map((q) => {
        const s = series[q.seriesIndex] || { name: q.seriesName };
        return [s.name.replace(/\s*\([^)]*\)\s*$/, ''), `<b>${esc(fmt(q.data._p.y))} ${esc(unitOf(s))}</b>`];
      });
      if (ps.length > 8) rows.push(['', `+${ps.length - 8} more`]);
      return tipHTML({ title: `${min === 0 ? 'alert' : (min > 0 ? '+' : '') + min + ' min'} · sensor time`, rows, meta });
    };
    return o;
  },

  timeline(ds, opts) {
    // Events on a time (or ordered category) axis, one lane per series (or per string y).
    // Point: {date|x, label?, outcome?:'kept'|'dropped'|'pending'|'replaced', severity?, y?, detail?, evidence_id?}
    //  - y string  -> it is the lane;  y number -> dot size (counts, steps)
    const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, { ...opts, legend: false });
    const P = t.pal;
    const col = { kept: P.outcome.kept, dropped: P.outcome.rejected, replaced: P.outcome.replaced, pending: P.outcome.pending, rejected: P.outcome.rejected,
      normal: P.severity.normal, sensor_fault: P.severity.sensor_fault, warning: P.severity.warning, critical: P.severity.critical };
    const isDate = (v) => /^\d{4}-\d{2}-\d{2}/.test(String(v));
    const all = series.flatMap((s) => s.data.map((p) => ({ s, p })));
    const timeAxis = all.length > 0 && all.every(({ p }) => isDate(p.date ?? p.x));
    const laneOf = ({ s, p }) => (typeof p.y === 'string' ? p.y : s.name);
    const lanes = [...new Set(all.map(laneOf))];
    const nums = all.map(({ p }) => p.y).filter((v) => typeof v === 'number');
    const maxY = nums.length ? Math.max(...nums) : 0;
    const sized = nums.length && maxY > 0 && new Set(nums).size > 1;
    const cats = timeAxis ? null : categoriesOf(series, opts.order);
    o.grid = { left: 6, right: 18, top: 14, bottom: 6, containLabel: true };
    o.xAxis = timeAxis
      ? { type: 'time', axisLabel: { color: t.muted, fontFamily: t.mono, fontSize: 10, hideOverlap: true }, axisLine: { lineStyle: { color: t.lineStrong } }, splitLine: { show: true, lineStyle: { color: t.line, type: [3, 4] } } }
      : categoryAxis(cats, opts, ctx_narrow(opts), { axisLabel: { color: t.muted, fontFamily: t.mono, fontSize: 10, hideOverlap: true, rotate: cats.length > 8 ? 35 : 0, width: 120, overflow: 'truncate' } });
    o.yAxis = categoryAxis(lanes, opts, ctx_narrow(opts), { inverse: true, axisLine: { show: false }, splitLine: { show: true, lineStyle: { color: t.line } } });
    let grey = 0;
    o.series = series.map((s) => {
      const sc = s.ours || s.ref || s.color ? colorFor(s) : colorFor(s, grey++);
      return {
        type: 'scatter', name: s.name, itemStyle: { color: sc },
        data: s.data.map((p) => {
          const tag = p.outcome || p.severity || p.status;
          const c = p.ours || p.highlight ? t.accent : col[tag] || sc;
          const hollow = tag === 'dropped' || tag === 'rejected' || tag === 'replaced';
          const size = sized && typeof p.y === 'number' ? 7 + 19 * Math.sqrt(Math.max(0, p.y) / maxY) : 12;
          return { value: [timeAxis ? (p.date ?? p.x) : String(p.x), laneOf({ s, p })], _p: p, symbolSize: size, symbol: hollow ? 'emptyCircle' : 'circle', itemStyle: { color: c, borderColor: c, borderWidth: 2, opacity: 0.9 } };
        }),
      };
    });
    o.tooltip.formatter = (prm) => {
      const p = prm.data._p;
      const skip = new Set(['x', 'y', 'date', 'label', 'what', 'detail', 'note', 'outcome', 'role', 'ours', 'highlight', 'ci', 'lo', 'hi', 'ci_method']);
      const extra = Object.entries(p).filter(([k, v]) => !skip.has(k) && !k.startsWith('_') && v != null && typeof v !== 'object').slice(0, 5).map(([k, v]) => [k.replace(/_/g, ' '), esc(String(v))]);
      return tipHTML({ title: p.label || p.what || String(p.x), meta, point: { ...p, note: p.detail || p.note }, rows: [
        timeAxis ? ['date', esc(String(p.date ?? p.x).replace('T', ' '))] : null, ['lane', esc(laneOf({ s: { name: prm.seriesName }, p }))],
        typeof p.y === 'number' ? ['value', `<b>${esc(withUnit(p.y, opts.unit ?? meta.unit, opts))}</b>`] : null,
        p.outcome ? ['outcome', esc(p.outcome)] : null, ...extra] });
    };
    return o;
  },
};

function hexA(hex, a) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
function ctx_narrow(opts) { return !!opts._narrow; }

/** Series in a different unit than meta.unit (e.g. ms + a fraction) get their own small panel, never a shared axis. */
function splitBars(ds, opts, stacked) {
  const { meta, series } = ds;
  const main = series.filter((s) => !s.unit || s.unit === meta.unit);
  const other = series.filter((s) => s.unit && s.unit !== meta.unit);
  const u2 = other[0].unit;
  const scale = u2 === 'fraction' && opts.fraction !== 'raw';
  const conv = (s) => (scale ? { ...s, data: s.data.map((p) => ({ ...p, y: p.y * 100, ci: p.ci && p.ci.map((v) => v * 100) })) } : s);
  const sub = { ...opts, _sub: true, horizontal: false, legend: false, highlightX: null, markLine: null };
  const A = barLike({ meta, series: main }, sub, null, stacked);
  const B = barLike({ meta: { ...meta, unit: scale ? '%' : u2 }, series: other.map(conv) }, { ...sub, yMin: scale ? 0 : undefined, yMax: scale ? 100 : undefined, unit: scale ? '%' : u2, decimals: scale ? 1 : opts.decimals }, null, stacked);
  const narrow = !!opts._narrow;
  const o = baseOption(meta, opts);
  const gA = narrow ? { left: 6, right: 18, top: 56, height: '36%', containLabel: true } : { left: 6, width: '58%', top: 56, bottom: 6, containLabel: true };
  const gB = narrow ? { left: 6, right: 18, bottom: 6, height: '30%', containLabel: true } : { left: '66%', right: 18, top: 56, bottom: 6, containLabel: true };
  o.grid = [gA, gB];
  o.xAxis = [{ ...A.xAxis, gridIndex: 0 }, { ...B.xAxis, gridIndex: 1 }];
  o.yAxis = [{ ...A.yAxis, gridIndex: 0 }, { ...B.yAxis, gridIndex: 1 }];
  o.series = [...A.series.map((x) => ({ ...x, xAxisIndex: 0, yAxisIndex: 0 })), ...B.series.map((x) => ({ ...x, xAxisIndex: 1, yAxisIndex: 1 }))];
  o.legend.show = true;
  o.legend.data = series.map((x) => x.name);
  const nA = A.series.length;
  o.tooltip.formatter = (prm) => (prm.seriesIndex < nA ? A.tooltip.formatter(prm) : B.tooltip.formatter({ ...prm, seriesIndex: prm.seriesIndex - nA }));
  return o;
}

function barLike(ds, opts, _ctx, stacked) {
  if (!opts._sub && ds.series.length > 1 && ds.series.some((s) => s.unit && s.unit !== ds.meta.unit) && ds.series.some((s) => !s.unit || s.unit === ds.meta.unit)) return splitBars(ds, opts, stacked);
  const { meta, series } = ds; const t = tokens(); const o = baseOption(meta, opts);
  const unit = opts.unit ?? meta.unit;
  const cats = categoriesOf(series, opts.order);
  let horizontal = opts.horizontal;
  if (horizontal == null) horizontal = opts._narrow && cats.length > 4 && !stacked ? true : false;
  if (horizontal == null) horizontal = false;
  const k = series.length;
  const percent = stacked && opts.percent;
  const totals = cats.map((c) => series.reduce((a, s) => a + (s.data.find((p) => String(p.x) === c)?.y || 0), 0));
  let grey = 0;
  const out = [];
  series.forEach((s, si) => {
    const sc = s.ours || s.color ? colorFor(s) : colorFor(s, grey++);
    out.push({
      type: 'bar', name: s.name, stack: stacked ? 'total' : undefined, itemStyle: { color: sc },
      barCategoryGap: '35%', barGap: '20%', barMaxWidth: 56,
      data: cats.map((c, ci) => {
        const p = s.data.find((q) => String(q.x) === c);
        if (!p) return { value: null };
        const v = percent ? (totals[ci] ? (100 * p.y) / totals[ci] : 0) : p.y;
        let color = p.ours || p.highlight ? t.accent : p.color ? colorFor(p) : sc;
        if (opts.highlightX && s.ours && !p.highlight && !p.ours) color = hexA(t.accent, 0.42);
        return { value: v, _p: p, itemStyle: { color, borderRadius: stacked ? 0 : (horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]) } };
      }),
      label: {
        show: opts.labels ?? (!stacked && cats.length * k <= 12 && !series.some((q) => q.data.some((p) => p.ci))), position: stacked ? 'inside' : (horizontal ? 'right' : 'top'),
        color: t.silver, fontFamily: t.mono, fontSize: 10, formatter: (prm) => (prm.value == null ? '' : fmt(prm.value, { ...opts, percent: false })),
      },
      markLine: si === 0 ? markLineFor({ ...opts, _horizontal: horizontal }) : undefined,
      emphasis: { focus: k > 1 ? 'series' : 'none' },
    });
  });
  if (!stacked) {
    series.forEach((s, si) => {
      const ciPts = s.data.filter((p) => p.ci);
      if (ciPts.length) out.push(whiskerSeries({ cats, ciPoints: ciPts, horizontal, k, idx: si, color: t.text }));
    });
  }
  o.legend.show = opts.legend ?? k > 1;
  o.legend.data = series.map((s) => s.name);
  if (!o.legend.show) o.grid.top = 30;
  const catAx = categoryAxis(cats, opts, ctx_narrow(opts), horizontal ? { inverse: true } : {});
  const valAx = valueAxis(percent ? { ...opts, yMax: 100, yName: '%' } : opts, meta);
  o.xAxis = horizontal ? valAx : catAx;
  o.yAxis = horizontal ? catAx : valAx;
  o.series = out;
  o.tooltip.formatter = (prm) => {
    const p = prm.data && prm.data._p; if (!p) return '';
    const rows = pointRows(p, unit, opts, k > 1 ? prm.seriesName : 'value');
    if (percent) rows.splice(1, 0, ['share', esc(fmt(prm.value, { decimals: 1 }) + ' %')]);
    return tipHTML({ title: p.label ?? p.x, rows, meta, point: p });
  };
  return o;
}

// ---------------------------------------------------------------- mounting (lazy + responsive)
let io = null;
const pending = new Map();
function observer() {
  if (io) return io;
  if (!('IntersectionObserver' in window)) return null;
  io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const fn = pending.get(e.target);
      if (fn) { pending.delete(e.target); io.unobserve(e.target); fn(); }
    }
  }, { rootMargin: '250px 0px' });
  return io;
}

function defaultHeight(type, ds, opts, width) {
  if (opts.height) return opts.height;
  const narrow = width < 520;
  const cats = categoriesOf(ds.series || []).length;
  if (type === 'ciDot') return Math.max(160, cats * (28 + 10 * Math.max(0, ds.series.length - 1)) + 70);
  if (type === 'trace') return narrow ? 210 : 250;
  if (type === 'timeline') {
    const lanes = new Set((ds.series || []).flatMap((s) => s.data.map((p) => (typeof p.y === 'string' ? p.y : s.name))));
    return Math.max(170, lanes.size * 44 + 80);
  }
  if ((type === 'bar' || type === 'waterfall') && (opts.horizontal || (narrow && cats > 4 && opts.horizontal !== false && type === 'bar'))) return Math.max(200, cats * 36 + 60);
  if (type === 'heatmap') return Math.max(240, [...new Set((ds.series[0]?.data || []).map((p) => p.y))].length * 32 + 90);
  return narrow ? 260 : 320;
}

/**
 * Draw a chart into `el` when it scrolls into view.
 * @param {HTMLElement} el
 * @param {string} type  one of TYPES
 * @param {object|Promise<object>} dataset  contract dataset {meta, series, ci?} (or a Promise of one)
 * @param {object} [opts]
 */
export function render(el, type, dataset, opts = {}) {
  if (type !== 'auto' && !builders[type]) throw new Error(`charts: unknown type "${type}". Known: auto, ${TYPES.join(', ')}`);
  let chart = null, ro = null, disposed = false, curDs = dataset, curOpts = opts, lastDs = null;
  let resolveReady, rejectReady;
  const ready = new Promise((res, rej) => { resolveReady = res; rejectReady = rej; });
  el.classList.add('chart');
  el.classList.add('is-pending');
  el.setAttribute('role', 'img');

  async function draw() {
    if (disposed) return;
    try {
      const [echarts, raw] = await Promise.all([ensureEcharts(), Promise.resolve(curDs)]);
      if (disposed) return;
      const ds = normalize(raw);
      CUR_TOPIC = curOpts.topic || ds.meta.topic || null;
      let ty = type === 'auto' ? ((ds.meta.chart && ds.meta.chart.type) || 'bar') : type;
      if (!builders[ty]) ty = 'bar';
      if (ds.meta.unit === 'fraction' && curOpts.fraction !== 'raw') asPercent(ds);
      const width = el.clientWidth || el.parentElement?.clientWidth || 600;
      const o2 = { ...impliedOpts(ds, ty), ...curOpts, _narrow: width < 520 };
      el.style.height = defaultHeight(ty, ds, o2, width) + 'px';
      el.dataset.chartType = ty;
      if (!el.getAttribute('aria-label')) el.setAttribute('aria-label', curOpts.title || ds.meta.claim || ds.meta.title || `${ty} chart`);
      const option = builders[ty](ds, o2);
      delete option._axisLabel;
      // a legend that wraps onto several rows must not cover the plot: make room for it
      if (option.legend && option.legend.show !== false && (option.legend.data || []).length > 1) {
        const avail = width - 12; let rows = 1, x = 0;
        for (const n of option.legend.data) { const iw = String(n).length * 6.8 + 30; if (x + iw > avail && x > 0) { rows++; x = 0; } x += iw; }
        const need = rows * 20 + 26;
        const grids = [].concat(option.grid || []);
        const g0 = grids[0];
        if (g0 && typeof g0.top === 'number' && g0.top < need) {
          const extra = need - g0.top;
          grids.forEach((g) => { if (typeof g.top === 'number') g.top += extra; });
          el.style.height = (parseInt(el.style.height, 10) + extra) + 'px';
        }
      }
      if (!chart) {
        chart = echarts.init(el, null, { renderer: 'canvas' });
        if (typeof curOpts.onClick === 'function') chart.on('click', (prm) => curOpts.onClick(prm.data && (prm.data._p || prm.data), prm));
        let lastW = width;
        ro = new ResizeObserver(() => {
          if (!chart) return;
          const w = el.clientWidth;
          if ((w < 520) !== (lastW < 520)) { lastW = w; draw(); return; }
          lastW = w; chart.resize();
        });
        ro.observe(el);
      }
      chart.setOption(option, true);
      lastDs = ds;
      if (!curOpts._noExpand) addExpandButton(el, () => chart, () => ({ title: curOpts.title || ds.meta.claim || ds.meta.title, ds: lastDs, meta: ds.meta }));
      chart.resize();
      el.classList.remove('is-pending');
      resolveReady(chart);
    } catch (err) {
      el.classList.remove('is-pending');
      el.innerHTML = `<p class="card__error">Chart unavailable: ${esc(err.message)}</p>`;
      el.style.height = 'auto';
      console.error('[charts]', type, err);
      rejectReady(err);
    }
  }

  const obs = curOpts.eager ? null : observer();
  if (obs) { pending.set(el, draw); obs.observe(el); } else { draw(); }

  return {
    el, type, ready,
    chart: () => chart,
    /** draw immediately, even if not scrolled into view (dialogs, exports, tests) */
    drawNow() { pending.delete(el); if (io) io.unobserve(el); draw(); return ready; },
    update(ds, o) { curDs = ds ?? curDs; curOpts = o ? { ...curOpts, ...o } : curOpts; if (chart) draw(); },
    dispose() { disposed = true; pending.delete(el); if (io) io.unobserve(el); if (ro) ro.disconnect(); if (chart) chart.dispose(); chart = null; },
  };
}

// one function per chart type, identical signature: (el, dataset, opts) -> handle
export const bar = (el, ds, o) => render(el, 'bar', ds, o);
export const stackedBar = (el, ds, o) => render(el, 'stackedBar', ds, o);
export const line = (el, ds, o) => render(el, 'line', ds, o);
export const waterfall = (el, ds, o) => render(el, 'waterfall', ds, o);
export const scatter = (el, ds, o) => render(el, 'scatter', ds, o);
export const boxplot = (el, ds, o) => render(el, 'boxplot', ds, o);
export const heatmap = (el, ds, o) => render(el, 'heatmap', ds, o);
export const ciDot = (el, ds, o) => render(el, 'ciDot', ds, o);
export const sankey = (el, ds, o) => render(el, 'sankey', ds, o);
export const funnel = (el, ds, o) => render(el, 'funnel', ds, o);
export const timeline = (el, ds, o) => render(el, 'timeline', ds, o);
export const trace = (el, ds, o) => render(el, 'trace', ds, o);
export const types = TYPES.slice();

/** Dispose every chart inside `root` (router calls this on page change). */
export function disposeIn(root) {
  if (!window.echarts) return;
  root.querySelectorAll('.chart').forEach((el) => {
    pending.delete(el); if (io) io.unobserve(el);
    const c = window.echarts.getInstanceByDom(el); if (c) c.dispose();
  });
}


// ---------------------------------------------------------------- expand: full-screen, zoomable copy of any chart
const EXPAND_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';

/** Put an "expand" button on a chart box. getInst() -> echarts instance; getInfo() -> {title, ds?, meta?, text?}. */
export function addExpandButton(el, getInst, getInfo) {
  if (!el || el.querySelector(':scope > .chart-expand')) return;
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'chart-expand'; b.title = 'Expand: zoom, table, save PNG';
  b.setAttribute('aria-label', 'Expand chart');
  b.innerHTML = EXPAND_SVG;
  b.addEventListener('click', (e) => { e.stopPropagation(); const inst = getInst(); if (inst) expand(inst, getInfo ? getInfo() : {}); });
  el.appendChild(b);
}

// plain-words summary of a dataset: range per series and ours vs the best alternative
export function analysisText(ds) {
  if (!ds || !ds.series) return '';
  const unit = ds.meta && ds.meta.unit ? ' ' + ds.meta.unit : '';
  const lines = [];
  const num = (p) => typeof p.y === 'number' && Number.isFinite(p.y);
  for (const s of ds.series.slice(0, 8)) {
    const pts = (s.data || []).filter(num);
    if (!pts.length) continue;
    const lo = pts.reduce((a, b) => (b.y < a.y ? b : a)), hi = pts.reduce((a, b) => (b.y > a.y ? b : a));
    const mean = pts.reduce((a, b) => a + b.y, 0) / pts.length;
    lines.push(pts.length === 1
      ? `${s.name}: ${fmt(pts[0].y)}${unit}${pts[0].n ? ` (n = ${pts[0].n})` : ''}.`
      : `${s.name}: ${pts.length} points, lowest ${fmt(lo.y)}${unit} at ${lo.label ?? lo.x}, highest ${fmt(hi.y)}${unit} at ${hi.label ?? hi.x}, mean ${fmt(mean)}${unit}.`);
  }
  const ours = ds.series.find((s) => s.ours);
  const alts = ds.series.filter((s) => !s.ours && !s.ref);
  if (ours && alts.length) {
    const lower = /^(ms|s|seconds|min|minutes|h|hours)$/i.test(String((ds.meta && ds.meta.unit) || ''));
    let win = 0, tot = 0;
    for (const p of ours.data.filter(num)) {
      const others = alts.map((a) => a.data.find((q) => String(q.x) === String(p.x))).filter((q) => q && num(q));
      if (!others.length) continue;
      tot++;
      const best = lower ? Math.min(...others.map((q) => q.y)) : Math.max(...others.map((q) => q.y));
      if (lower ? p.y <= best : p.y >= best) win++;
    }
    if (tot) lines.push(`${ours.name} is ${lower ? 'as fast or faster' : 'as good or better'} than every alternative on ${win} of ${tot} shared categories.`);
  }
  return lines.join(' ');
}

function tableHTML(ds) {
  const rows = [];
  for (const s of ds.series || []) for (const p of s.data || []) {
    if (p == null || typeof p !== 'object') continue;
    rows.push(`<tr><td>${esc(s.name)}</td><td>${esc(p.label ?? p.x ?? p.date ?? '')}</td><td>${esc(p.y ?? p.v ?? p.median ?? '')}</td><td>${esc(p.n ?? '')}</td><td>${p.ci ? esc(fmt(p.ci[0]) + ' – ' + fmt(p.ci[1])) : ''}</td></tr>`);
  }
  if (!rows.length) return '<p style="padding:12px">No tabular values.</p>';
  return `<div class="ct-dataview"><table><thead><tr><th>series</th><th>x</th><th>value${ds.meta && ds.meta.unit ? ' (' + esc(ds.meta.unit) + ')' : ''}</th><th>n</th><th>95% CI</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}

/** Open a full-screen copy of an echarts instance with dataZoom (slider + wheel/pinch), toolbox, crosshair. */
export function expand(src, info = {}) {
  const t = tokens();
  const echarts = window.echarts;
  if (!echarts || !src) return null;
  const dlg = document.createElement('dialog');
  dlg.className = 'modal modal--chart';
  dlg.setAttribute('aria-label', info.title || 'Chart');
  const head = document.createElement('div'); head.className = 'modal__head';
  const lab = document.createElement('span'); lab.className = 'label'; lab.textContent = info.title || 'Chart';
  const close = document.createElement('button'); close.type = 'button'; close.className = 'icon-btn'; close.setAttribute('aria-label', 'Close'); close.textContent = '×';
  head.append(lab, close);
  const body = document.createElement('div'); body.className = 'modal__body';
  const box = document.createElement('div'); box.className = 'chart-full';
  const hint = document.createElement('p'); hint.className = 'chart-full__hint';
  hint.textContent = 'Wheel or pinch to zoom, drag the slider to pan, click legend items to hide a series. Toolbar: box zoom, reset, table, save PNG.';
  body.append(box, hint);
  const txt = info.text || (info.ds ? analysisText(info.ds) : '');
  if (txt) { const p = document.createElement('p'); p.className = 'chart-full__text'; p.textContent = txt; body.append(p); }
  if (info.meta && info.meta.notes) { const p = document.createElement('p'); p.className = 'chart-full__notes'; p.textContent = info.meta.notes; body.append(p); }
  dlg.append(head, body);
  document.body.append(dlg);
  dlg.showModal();

  const inst = echarts.init(box, null, { renderer: 'canvas' });
  const opt = src.getOption();
  opt.animation = false;
  const xa = opt.xAxis || [], ya = opt.yAxis || [];
  const grids = [].concat(opt.grid || []);
  if (xa.length && ya.length) {
    const horiz = ya[0].type === 'category' && xa[0].type !== 'category';
    const key = horiz ? 'yAxisIndex' : 'xAxisIndex';
    const idx = (horiz ? ya : xa).map((_, i) => i);
    if (!opt.dataZoom || !opt.dataZoom.length) {
      opt.dataZoom = [
        { type: 'inside', [key]: idx, filterMode: 'none', zoomOnMouseWheel: true, moveOnMouseMove: true },
        { type: 'slider', [key]: idx, filterMode: 'none', ...(horiz ? { right: 6, width: 18 } : { bottom: 8, height: 22 }),
          borderColor: t.line, textStyle: { color: t.muted, fontSize: 10 }, fillerColor: 'rgba(76,125,255,0.18)',
          handleStyle: { color: t.silver }, dataBackground: { lineStyle: { color: t.alt }, areaStyle: { color: 'rgba(107,110,118,0.25)' } } },
      ];
      grids.forEach((g) => { if (horiz) g.right = (typeof g.right === 'number' ? g.right : 18) + 34; else if (typeof g.bottom === 'number') g.bottom += 40; });
    }
    const cross = { show: true, type: 'line', lineStyle: { color: t.muted, type: 'dashed' }, label: { show: true, backgroundColor: t.panel, color: t.text, fontFamily: t.mono, fontSize: 10 } };
    opt.xAxis = xa.map((a) => ({ ...a, axisPointer: { ...cross, snap: a.type === 'category' } }));
    opt.yAxis = ya.map((a) => ({ ...a, axisPointer: { ...cross, snap: a.type === 'category' } }));
  }
  grids.forEach((g) => { if (typeof g.top === 'number') g.top += 24; });
  if (grids.length) opt.grid = grids;
  opt.toolbox = [{
    show: true, right: 8, top: 0, itemSize: 16, iconStyle: { borderColor: t.silver }, emphasis: { iconStyle: { borderColor: t.text, textFill: t.text } },
    feature: {
      ...(xa.length ? { dataZoom: { title: { zoom: 'Box zoom', back: 'Undo zoom' } } } : {}),
      restore: { title: 'Reset' },
      dataView: { title: 'Table', readOnly: true, lang: ['Data', 'Close', 'Refresh'], backgroundColor: t.panel, textColor: t.text,
        textareaColor: t.bg, textareaBorderColor: t.line, buttonColor: t.accent, buttonTextColor: '#fff',
        ...(info.ds ? { optionToContent: () => tableHTML(info.ds) } : {}) },
      saveAsImage: { title: 'Save PNG', backgroundColor: t.bg, pixelRatio: 2, name: String(info.title || 'chart').replace(/[^\w.-]+/g, '_').slice(0, 60) },
    },
  }];
  if (opt.legend) opt.legend = [].concat(opt.legend).map((l) => ({ ...l, type: 'scroll', right: 170, pageTextStyle: { color: t.muted } }));
  inst.setOption(opt, true);
  const onResize = () => inst.resize();
  window.addEventListener('resize', onResize);
  const done = () => { window.removeEventListener('resize', onResize); inst.dispose(); dlg.close(); dlg.remove(); };
  close.addEventListener('click', done);
  dlg.addEventListener('click', (e) => { if (e.target === dlg) done(); });
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); done(); });
  close.focus();
  return inst;
}
