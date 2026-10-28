// Proofs: every dataset in data/catalog.json as a card (claim, chart, why, source), by topic.
// Cards are created only for the visible tab and only when scrolled near (charts draw lazily inside the kit).

const TABS = [
  ['use_case', 'Use case'], ['latency', 'Latency'], ['hardware', 'Hardware'], ['accuracy', 'Accuracy'], ['agent_design', 'Agent design'],
  ['refinement', 'Refinement'], ['training_v2', 'Training v2'], ['dataset_v2', 'Dataset v2'], ['app_ux', 'App / UX'],
  ['ops', 'Ops'], ['timeline', 'Timeline'],
];
// Datasets that read better as a table than as a chart (labels, statuses, mixed units).
const AS_TABLE = new Set(['hw_platform_paths', 'hw_gpu_bringup_failures', 'ad_placement_called', 'ref_go_tests',
  'lat_two_windows', 'ux_report_page_checks', 'ux_scenario_outcomes', 'ref_ui_checks', 'ad_reasoner_plan', 'ad_self_learning']);
const WIDE = new Set(['line', 'heatmap', 'waterfall', 'timeline', 'sankey', 'stackedBar']);
const SHOTS = [
  ['Before · 14 Oct', [['b_inc2', 'Incident detail, old layout'], ['b_stream1', 'Notification while agents run'], ['b_ui1', 'Sensors page, old'],
    ['b_ui3', 'Incident list, old'], ['b_ui4', 'Incident steps, old'], ['b_ui5', 'Campus live, old'], ['b_ui6', 'Sliders, old']]],
  ['After · report page · 16 Oct', [['a_01_list_real_data', 'Incident list, real data'], ['a_02_list_all_severities_synthetic', 'All severities (synthetic states)'],
    ['a_03_done_detail_top', 'Finished report, top'], ['a_04_done_detail_full', 'Finished report, full'], ['a_08_npu_agents_expanded', 'NPU agent expanded'],
    ['a_09_running_detail_top', 'Report while agents run'], ['a_12_light_done_detail', 'Light theme'], ['a_d0_current', 'On the QIDK screen']]],
  ['Refined re-analysis · 16 Oct', [['r_01_early_detail_top', 'Early call'], ['r_02_refined_1_5h_detail_top', 'Refined at 1.5 h'], ['r_03_refined_3h_detail_top', 'Refined at 3 h'],
    ['r_04_history_real', 'History of one incident'], ['r_05_refined_detail_full', 'Refined report, full'], ['r_07_list_refined_marker', 'List with refined marker'],
    ['r_08_list_synthetic_changed', 'Severity changed (synthetic)'], ['r_09_history_synthetic_spike_kept_then_step', 'Spike kept, then step'],
    ['r_11_detail_synthetic_1_5h_kept_top', 'Kept at 1.5 h'], ['r_13_light_synthetic_detail_top', 'Light theme, refined']]],
];

const fmtN = (v) => (typeof v === 'number' ? v.toLocaleString('en-US') : v);
const kb = (b) => (b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB');
const base = (p) => String(p || '').split(/[\\/#]/).filter(Boolean).pop() || p;
const pts = (s) => s.points || s.data || [];


// ---- auto analysis: ours vs baseline, from the series alone ----
const erf = (x) => { const t = 1 / (1 + 0.3275911 * Math.abs(x)); const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return x >= 0 ? y : -y; };
const pTwo = (z) => Math.max(0, Math.min(1, 1 - erf(Math.abs(z) / Math.SQRT2)));
const r3 = (v) => (Math.abs(v) >= 100 ? Math.round(v) : +v.toPrecision(3));
function pairsOf(ds) {
  const S = (ds.series || []).filter((s) => !s.nodes);
  const num = (p) => p && typeof p.y === 'number' && isFinite(p.y);
  const out = [];
  const ours = S.find((s) => s.role === 'ours'); const alt = S.find((s) => s !== ours && s.role !== 'ref') || S.find((s) => s !== ours);
  if (ours && alt && (!ds.meta.unit || !alt.unit || alt.unit === ours.unit)) {
    for (const b of pts(ours)) { const a = pts(alt).find((q) => q.x === b.x); if (num(a) && num(b)) out.push({ x: b.x, a, b, an: alt.name, bn: ours.name }); }
    if (out.length) return out;
  }
  const P = pts(S[0] || {}).filter(num);
  if (P.length >= 2 && S.length === 1) {
    const ob = P.filter((p) => p.ours || p.role === 'ours'); const b = ob[0] || P[P.length - 1];
    const a = P.find((p) => p !== b && !(p.ours || p.role === 'ours')) || P[0];
    if (a !== b) out.push({ x: `${a.x} → ${b.x}`, a, b, an: a.x, bn: b.x });
  }
  return out;
}
function analyse(ds) {
  const frac = ds.meta.unit === 'fraction'; const k = frac ? 100 : 1; const u = frac ? ' pp' : (ds.meta.unit && ds.meta.unit !== '-' ? ' ' + ds.meta.unit : '');
  const rows = [];
  for (const { x, a, b, an, bn } of pairsOf(ds).slice(0, 12)) {
    const d = b.y - a.y; const r = { x: String(x), y: d * k, n: b.n };
    let txt = `${x}: ${an} ${r3(a.y * k)} → ${bn} ${r3(b.y * k)} (${d >= 0 ? '+' : ''}${r3(d * k)}${u}${a.y ? `, ${d >= 0 ? '+' : ''}${r3(100 * d / Math.abs(a.y))} %` : ''})`;
    let p = null, test = null, eff = null;
    if (a.k != null && a.n && b.k != null && b.n) {
      const p1 = a.k / a.n, p2 = b.k / b.n, pp = (a.k + b.k) / (a.n + b.n);
      const se0 = Math.sqrt(pp * (1 - pp) * (1 / a.n + 1 / b.n)); const se = Math.sqrt(p1 * (1 - p1) / a.n + p2 * (1 - p2) / b.n);
      if (se0 > 0) { p = pTwo((p2 - p1) / se0); test = 'two-proportion z-test'; }
      r.lo = (p2 - p1 - 1.96 * se) * k; r.hi = (p2 - p1 + 1.96 * se) * k;
      const h = 2 * Math.asin(Math.sqrt(p2)) - 2 * Math.asin(Math.sqrt(p1)); eff = `Cohen's h ${h.toFixed(2)} (${Math.abs(h) < 0.2 ? 'negligible' : Math.abs(h) < 0.5 ? 'small' : Math.abs(h) < 0.8 ? 'medium' : 'large'})`;
      txt += `, n ${a.n} vs ${b.n}`;
    } else if (a.lo != null && a.hi != null && b.lo != null && b.hi != null) {
      const se = Math.hypot((a.hi - a.lo) / 3.92, (b.hi - b.lo) / 3.92);
      if (se > 0) { p = pTwo(d / se); test = 'z-test from the two 95% CIs'; r.lo = (d - 1.96 * se) * k; r.hi = (d + 1.96 * se) * k; }
    }
    if (r.lo != null) txt += `; 95% CI of the difference ${r3(r.lo)} to ${r3(r.hi)}${u}`;
    if (p != null) txt += `; ${test} p = ${p < 0.0001 ? '< 0.0001' : p.toFixed(4)} → ${p < 0.05 ? 'significant at 5 %' : 'not significant at 5 %'}`;
    if (eff) txt += `; ${eff}`;
    if (p == null && (a.n || b.n)) txt += `; n ${a.n ?? '?'} vs ${b.n ?? '?'}, no spread recorded, so no test`;
    // colour: improvement green, regression red, not significant / untested grey (lower is better for time units)
    const lowerBetter = /^(ms|s|seconds|min|minutes|h|hours|°c|c|mb|gb|w)$/i.test(String(ds.meta.unit || '').trim());
    const good = lowerBetter ? d < 0 : d > 0;
    r.sig = p != null && p < 0.05 ? (good ? 'better' : 'worse') : (d === 0 ? 'ns' : p == null ? (good ? 'better' : 'worse') : 'ns');
    r.tested = p != null;
    r.color = r.sig; r.label = txt; rows.push(r);
  }
  return rows;
}

function pickType(ds) {
  const m = ds.meta || {};
  if (m.id === 'ds_roles') return 'sankey';
  if (AS_TABLE.has(m.id)) return 'table';
  const t = m.chart && m.chart.type;
  if (t) return t;
  const all = (ds.series || []).flatMap(pts);
  if (!all.length || all.some((p) => p.y == null || typeof p.y !== 'number')) return 'table';
  if (m.unit === 'fraction' && all.every((p) => p.lo != null && p.hi != null) && all.length <= 8) return 'ciDot';
  return 'bar';
}

// rows per role -> split, as a sankey (dataset composition)
function toSankey(ds) {
  const nodes = new Map(); const links = [];
  for (const s of ds.series) for (const p of pts(s)) {
    nodes.set(p.x, { name: p.x }); nodes.set(s.name, { name: s.name, ours: s.role === 'ours' });
    links.push({ source: p.x, target: s.name, value: p.y });
  }
  return { meta: { ...ds.meta, chart: { type: 'sankey' } }, series: [{ name: 'rows', nodes: [...nodes.values()], links }] };
}

function table(h, ds) {
  const rows = []; const cols = new Set(['series']);
  const multi = (ds.series || []).length > 1;
  for (const s of ds.series || []) for (const p of pts(s)) {
    const r = { series: s.name };
    for (const [k, v] of Object.entries(Array.isArray(p) ? { x: p[0], y: p[1] } : p)) {
      if (k === 'path' || k === 'ci_method') continue;
      cols.add(k);
      r[k] = Array.isArray(v) ? v.map((e) => (Array.isArray(e) ? e.join(': ') : e)).join(', ')
        : v && typeof v === 'object' ? Object.entries(v).map(([a, b]) => `${a}: ${b}`).join(', ') : v;
    }
    rows.push(r);
  }
  if (!multi) cols.delete('series');
  const C = [...cols].filter((c) => rows.some((r) => r[c] != null && r[c] !== ''));
  const unit = ds.meta && ds.meta.unit && ds.meta.unit !== '-' ? ds.meta.unit : '';
  const head = (c) => (c === 'x' ? '' : c === 'y' ? (unit || 'value') : c);
  return h('div.ptable', null, h('table', null,
    h('thead', null, h('tr', null, C.map((c) => h('th', { text: head(c) })))),
    h('tbody', null, rows.map((r) => h('tr', null, C.map((c) => h('td', { text: r[c] == null ? '' : fmtN(r[c]) })))))));
}

export default async function mount(ctx) {
  const { root, ui, h, data } = ctx;
  const slot = (s) => root.querySelector(`[data-slot="${s}"]`);
  slot('next').append(ui.next('proofs'));
  const nl = root.querySelector('.next .label'); if (nl) nl.textContent = 'Next';

  let cat = [];
  try { cat = await data.catalog(); } catch (e) {
    slot('cards').append(ui.chip('data/catalog.json missing from this build', 'warn')); return;
  }
  // only datasets with real data behind them (the catalog may flag the rest)
  cat = cat.filter((d) => d.has_data !== false && d.empty !== true && d.n !== 0);
  let catFull = null;
  try { catFull = await data.json('catalog.json'); } catch (e) { /* packs list optional */ }

  // ---- anchor: big numbers, computed from the data ----
  const files = new Set(cat.flatMap((d) => d.source_files || []));
  const packs = (catFull && catFull.packs) || [];
  const perSample = packs.filter((p) => /scores|stress|metrics/.test(p.file)).reduce((a, p) => a + (p.items || 0), 0);
  slot('statement').textContent = `${cat.length} measured results, every one traceable.`;
  const anchors = [{ value: String(cat.length), label: 'Results, each with its source file and script.', meta: `${files.size} source files` }];
  if (perSample) anchors.push({ value: fmtN(perSample), label: 'Per-sample scores you can download.', meta: 'labels and scores, no inputs', ours: false });
  try {
    const st = await data.dataset('ux_v6_final_checks');
    const ps = st.series.flatMap(pts); const k = ps.reduce((a, p) => a + (p.k || 0), 0); const n = ps.reduce((a, p) => a + (p.n || 0), 0);
    if (n) anchors.push({ value: `${k} / ${n}`, label: 'App stress checks passed on the final NPU build.', meta: `${n - k} failed, all heat · n = ${n}`, ours: false });
  } catch (e) { /* optional */ }
  slot('anchors').append(ui.anchors(anchors));

  // ---- deep link: #/proofs?file=<path> or ?id=<dataset> ----
  const q = ctx.query || {};
  const wantFile = q.file ? String(q.file) : null;
  const matchIds = new Set(cat.filter((d) => (q.id && d.id === q.id) ||
    (wantFile && (d.source_files || []).some((f) => f === wantFile || f.startsWith(wantFile) || wantFile.startsWith(f.split('#')[0])))).map((d) => d.id));
  if (wantFile || q.id) {
    slot('filter').append(h('div.proofs-filter', null,
      h('span.label', { text: matchIds.size ? `${matchIds.size} result${matchIds.size > 1 ? 's' : ''} from` : 'No result cites' }),
      h('code', { text: wantFile || q.id }),
      h('a.chip', { href: '#/proofs', text: 'Show all' })));
  }

  const byTopic = {};
  for (const d of cat) (byTopic[d.topic] = byTopic[d.topic] || []).push(d);
  const tabs = TABS.filter(([t]) => byTopic[t]);
  for (const t of Object.keys(byTopic)) if (!tabs.some(([x]) => x === t)) tabs.push([t, t]);
  let active = (q.topic && byTopic[q.topic] && q.topic) ||
    (matchIds.size && cat.find((d) => matchIds.has(d.id)).topic) || tabs[0][0];

  // lazily build cards when their placeholder comes near the viewport
  const io = new IntersectionObserver((ents) => {
    for (const e of ents) if (e.isIntersecting) { io.unobserve(e.target); build(e.target); }
  }, { rootMargin: '600px 0px' });
  ctx.onCleanup(() => io.disconnect());

  function build(ph) {
    const id = ph.dataset.id; const d = cat.find((x) => x.id === id);
    data.dataset(id).then((ds) => {
      const ty = pickType(ds);
      const m = ds.meta || {};
      const method = [m.script ? `made by ${base(m.script)}` : null, m.notes ? m.notes.split(/(?<=\.)\s/)[0] : null].filter(Boolean).join(' · ');
      const extra = h('div.proofs-meta', null,
        h('span.label', { text: [m.n != null ? `n = ${fmtN(m.n)}` : null, m.unit && m.unit !== '-' ? m.unit : null].filter(Boolean).join(' · ') || ' ' }),
        method ? h('p.proofs-method', { text: method }) : null);
      const spec = { claim: m.claim || m.title, why: m.why || '', source: { files: m.source_files || [], script: m.script } };
      if (id === 'ux_screenshots') {
        spec.claim = `${SHOTS.reduce((a, g) => a + g[1].length, 0)} app screens, before and after`;
        spec.body = h('div', null, h('a.btn', { href: '#gallery', onclick: (ev) => { ev.preventDefault(); slot('gallery-wrap').scrollIntoView({ behavior: 'smooth' }); } }, 'Open the gallery ↓'), extra);
      } else if (ty === 'table') {
        spec.body = h('div', null, table(h, ds), extra);
      } else {
        spec.chart = { type: ty, data: ty === 'sankey' && id === 'ds_roles' ? toSankey(ds) : ds, opts: {} };
        spec.body = extra;
      }
      if (m.claim && m.title !== m.claim) spec.claim = m.claim;
      const span = ph.dataset.span;
      const card = ui.card({ ...spec, span: Number(span) });
      card.id = 'ds-' + id;
      if (matchIds.has(id)) card.classList.add('is-match');
      const foot = card.querySelector('.card__foot');
      if (foot && ty !== 'table' && id !== 'ux_screenshots') {
        foot.append(h('button.chip', { type: 'button', onclick: () => ui.modal(m.title || id, table(h, ds)) }, 'Numbers'));
      }
      const an = ty === 'table' || id === 'ux_screenshots' ? [] : analyse(ds);
      if (an.length) {
        const unitD = m.unit === 'fraction' ? 'pp' : m.unit;
        const line = h('p.proofs-analysis', { title: an.map((r) => r.label).join('\n') }, h('span.label', { text: 'Analysis ' }), an[0].label + (an.length > 1 ? ` (+${an.length - 1} more, hover)` : ''));
        (card.querySelector('.proofs-meta') || card).prepend(line);
        if (foot) foot.append(h('button.chip.chip--ours', { type: 'button', onclick: () => ui.modal('Difference vs baseline', h('div', null,
          ui.card({ claim: 'Difference, ours minus baseline (95% CI where the data allow)', chart: { type: 'ciDot', data: { meta: { ...m, id: m.id + '_diff', unit: unitD, chart: { type: 'ciDot' } }, series: [{ name: 'difference', role: 'ours', points: an }] }, opts: { ref: 0, refLabel: 'no change', eager: true } }, source: { files: m.source_files || [], script: m.script } }),
          ctx.ui.legend([['Improvement', 'var(--d-better)'], ['Regression', 'var(--d-worse)'], ['Not significant (n.s.)', 'var(--d-ns)']]),
          h('ul.proofs-an-list', null, an.map((r) => h(`li.delta--${r.sig}`, null, r.label, r.sig === 'ns' ? h('span.badge-ns', { text: 'n.s.' }) : null))))) }, 'Δ vs baseline'));
      }
      if (foot && m.script) foot.append(h('span.chip.proofs-script', { title: m.script, text: base(m.script) }));
      ph.replaceWith(card);
    }).catch((err) => { ph.replaceWith(h(`article.card.span-${ph.dataset.span}`, null, h('h3.card__claim', { text: d.title }), ui.chip('data missing', 'warn'))); console.warn(err); });
  }

  function guessSpan(d) {
    const t = (d.chart && d.chart.type) || '';
    return WIDE.has(t) || d.id === 'ds_roles' || AS_TABLE.has(d.id) ? 12 : 6;
  }

  function show(topic) {
    active = topic;
    for (const b of slot('tabs').children) b.setAttribute('aria-selected', String(b.dataset.topic === topic)), b.tabIndex = b.dataset.topic === topic ? 0 : -1;
    const grid = slot('cards');
    for (const ph of grid.querySelectorAll('.proofs-ph')) io.unobserve(ph);
    ctx.charts.disposeIn(grid);
    grid.innerHTML = '';
    const list = byTopic[topic].slice().sort((a, b) => (matchIds.has(b.id) - matchIds.has(a.id)) || (!!b.claim - !!a.claim));
    const title = (catFull && catFull.topic_titles && catFull.topic_titles[topic]) || topic;
    slot('topicline').textContent = `${title} · ${list.length} results`;
    // at most 7 cards before "more" (a deep-linked card is always among the first)
    const LIMIT = 7;
    const add = (d) => {
      const ph = h(`div.proofs-ph.span-${guessSpan(d)}`, { 'data-id': d.id, 'data-span': guessSpan(d), 'aria-busy': 'true' }, h('span.label', { text: d.title }));
      grid.append(ph); io.observe(ph);
    };
    if (topic === 'training_v2') grid.append(h('a.proofs-raw.span-12', { href: '#/route?s=training' },
      h('span.label', { text: 'Overview' }), h('span.proofs-raw__title', { text: 'Training v2 at a glance: progress, interruptions, what changes, acceptance' }),
      h('span.proofs-raw__go', { text: '→', 'aria-hidden': 'true' })));
    list.slice(0, LIMIT).forEach(add);
    if (list.length > LIMIT) {
      const more = h('button.btn.proofs-more.span-12', { type: 'button', onclick: () => { more.remove(); list.slice(LIMIT).forEach(add); } },
        `Show ${list.length - LIMIT} more result${list.length - LIMIT > 1 ? 's' : ''}`);
      grid.append(more);
    }
    slot('gallery-wrap').hidden = topic !== 'app_ux';
    try { history.replaceState(null, '', `#/proofs?topic=${topic}`); } catch (e) { /* ignore */ }
    if (matchIds.size) {
      const first = list.find((d) => matchIds.has(d.id));
      if (first) requestAnimationFrame(() => grid.querySelector(`[data-id="${first.id}"]`)?.scrollIntoView({ block: 'center' }));
    }
  }

  for (const [t, label] of tabs) {
    slot('tabs').append(h('button.proofs-tab', { type: 'button', role: 'tab', 'data-topic': t, onclick: () => show(t) },
      h('span', { text: label }), h('span.proofs-tab__n', { text: String(byTopic[t].length) })));
  }
  slot('tabs').addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const i = tabs.findIndex(([t]) => t === active); const j = (i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
    show(tabs[j][0]); slot('tabs').children[j].focus(); e.preventDefault();
  });
  show(active);

  // ---- gallery (images decrypted on demand) ----
  const gal = slot('gallery');
  const imgIO = new IntersectionObserver((ents) => {
    for (const e of ents) if (e.isIntersecting) {
      imgIO.unobserve(e.target);
      ctx.asset(`proofs/shots/${e.target.dataset.shot}.webp`).then((u) => { e.target.src = u; }).catch(() => e.target.replaceWith(ui.chip('image missing', 'warn')));
    }
  }, { rootMargin: '400px 0px' });
  ctx.onCleanup(() => imgIO.disconnect());
  for (const [group, list] of SHOTS) {
    const row = h('div.shots');
    for (const [f, cap] of list) {
      const img = h('img', { alt: cap, 'data-shot': f, loading: 'lazy', width: 540, height: 1170 });
      imgIO.observe(img);
      row.append(h('figure.shot', null, h('button.shot__btn', { type: 'button', 'aria-label': `Enlarge: ${cap}`,
        onclick: () => { const big = h('img.shot__big', { alt: cap, src: img.src }); ui.modal(cap, big); } }, img), h('figcaption', { text: cap })));
    }
    gal.append(h('div.shots-group', null, h('span.label', { text: group }), row));
  }
  gal.append(h('p.muted.shots-note', { text: 'After-screens come from a laptop backend with mock agents unless marked QIDK; some states are synthetic. Sensor chart screens are left out: they show raw readings.' }));

  // ---- packs ----
  const pk = slot('packs');
  if (!packs.length) pk.append(ui.chip('no packs in this build', 'warn'));
  for (const p of packs) {
    const name = base(p.file);
    const btn = h('button.btn.btn--solid', { type: 'button' }, 'Download');
    btn.addEventListener('click', async () => {
      btn.disabled = true; btn.textContent = 'Decrypting…';
      try { await data.download(p.file, name); btn.textContent = 'Saved'; } catch (e) { btn.textContent = 'Failed'; console.error(e); }
      setTimeout(() => { btn.disabled = false; btn.textContent = 'Download'; }, 2500);
    });
    pk.append(h('div.pack', null,
      h('div.pack__text', null, h('span.pack__name', { text: name }), h('p.pack__desc', { text: p.description || '' }),
        h('span.label', { text: [p.items != null ? `${fmtN(p.items)} items` : null, p.bytes ? kb(p.bytes) + ' gz' : null].filter(Boolean).join(' · ') })),
      btn));
  }
}
