// Route page: anchor -> journey timeline -> latency waterfall -> rejected strip -> accuracy route -> peak-end.
export default async function mount(ctx) {
  const { root, ui, h, data } = ctx;
  const slot = (s) => root.querySelector(`[data-slot="${s}"]`);

  const route = await data.route();

  // ---------- evidence card for any dataset id (text-only datasets get no chart, and say so)
  const evidence = async (id, claim) => {
    try {
      const ds = await data.dataset(id);
      if (ds.meta.chart && ds.meta.chart.type) return ui.card({ span: 12, chart: { type: 'auto', data: ds } });
      const card = ui.card({ span: 12, claim: ds.meta.claim || claim || ds.meta.title, why: ds.meta.why, source: ds.meta });
      card.querySelector('.card__foot')?.prepend(ui.chip('text only, no chart', 'warn'));
      return card;
    } catch (e) {
      return ui.card({ span: 12, claim: claim || id, why: 'Evidence dataset is missing from this build.' });
    }
  };

  // ---------- journey timeline
  const OUT = { kept: 'Kept', dropped: 'Dropped', pending: 'Pending' };
  const list = slot('journey');
  const GROUPS = [
    { title: 'Build v1 on the laptop', upTo: 3 }, { title: 'Onto the board', upTo: 8 },
    { title: 'After the mid-evaluation', upTo: 17 }, { title: 'Retrain v2 and this site', upTo: 99 }];
  const phaseNo = (s) => parseInt(s.phase, 10) || 0;
  const items = route.journey.map((s, i) => {
    const metric = s.metric_before || s.metric_after
      ? h('span.rt-metric', null, s.metric_before ? h('span.rt-before', { text: s.metric_before }) : null,
        s.metric_before && s.metric_after ? h('span.rt-arrow', { text: '→', 'aria-hidden': 'true' }) : null,
        s.metric_after ? h('span.rt-after', { text: s.metric_after }) : null)
      : null;
    const detail = h('div.rt-detail', { id: `rt-d${i}`, hidden: true });
    const btn = h('button.rt-step', { type: 'button', 'aria-expanded': 'false', 'aria-controls': `rt-d${i}` },
      h('span.rt-dot', { 'aria-hidden': 'true' }),
      h('span.rt-head', null,
        h('span.label', { text: `${s.date.slice(5)} · ${s.phase.replace(/^\d+\s*/, '')}` }),
        h('span.rt-what', { text: s.what }), metric),
      h('span.rt-out', { text: OUT[s.outcome] || s.outcome }));
    const li = h(`li.rt-item.is-${s.outcome}`, null, btn, detail);
    btn.addEventListener('click', async () => {
      const open = btn.getAttribute('aria-expanded') === 'true';
      list.querySelectorAll('.rt-step[aria-expanded="true"]').forEach((b) => {
        b.setAttribute('aria-expanded', 'false');
        const d = b.nextElementSibling; ctx.charts.disposeIn?.(d); d.hidden = true; d.replaceChildren();
      });
      if (open) return;
      btn.setAttribute('aria-expanded', 'true');
      detail.hidden = false;
      detail.replaceChildren(h('p.label', { text: 'Loading evidence' }));
      const card = await evidence(s.evidence_id, s.what);
      if (btn.getAttribute('aria-expanded') !== 'true') return;
      detail.replaceChildren(h('div.grid', null, card));
      card._chart?.drawNow?.();
    });
    return li;
  });
  // phases as collapsible groups (closed on phones, open on wide screens)
  // only the latest phase starts open; the rest is one click away (keeps the page short)
  const groups = GROUPS.map((g, gi) => {
    const lo = gi ? GROUPS[gi - 1].upTo : -1;
    const idx = route.journey.map((s, i) => i).filter((i) => phaseNo(route.journey[i]) > lo && phaseNo(route.journey[i]) <= g.upTo);
    if (!idx.length) return null;
    const js = idx.map((i) => route.journey[i]);
    const kept = js.filter((s) => s.outcome === 'kept').length;
    const d0 = js[0].date.slice(5), d1 = js[js.length - 1].date.slice(5);
    const det = h('details.rt-group', { open: gi === GROUPS.length - 1 },
      h('summary.rt-group__sum', null,
        h('span.rt-group__title', { text: g.title }),
        h('span.label.rt-group__meta', { text: `${d0 === d1 ? d0 : d0 + ' – ' + d1} · ${js.length} steps · ${kept} kept` })),
      h('ol.rt-tl', null, idx.map((i) => items[i])));
    det._idx = idx;
    return det;
  }).filter(Boolean);
  list.append(...groups);

  const counts = { all: items.length };
  for (const s of route.journey) counts[s.outcome] = (counts[s.outcome] || 0) + 1;
  const filter = slot('filter');
  const setFilter = (k) => {
    filter.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.k === k)));
    route.journey.forEach((s, i) => { items[i].hidden = k !== 'all' && s.outcome !== k; });
    groups.forEach((g) => { g.hidden = g._idx.every((i) => items[i].hidden); if (k !== 'all' && !g.hidden) g.open = true; });
  };
  for (const k of ['all', 'kept', 'dropped', 'pending']) {
    if (!counts[k]) continue;
    filter.append(h(`button.chip.rt-f.is-${k}`, { type: 'button', 'data-k': k, onclick: () => setFilter(k) },
      `${k === 'all' ? 'All' : OUT[k]} ${counts[k]}`));
  }
  setFilter('all');

  // ---------- training v2: progress (status.json, read from the live log at build time), loss, sessions, plan, acceptance
  try {
    const [st, sess, plan, routine, intrDs] = await Promise.all([data.status(), data.dataset('tv2_sessions'), data.dataset('tv2_plan'),
      data.dataset('ds_routine').catch(() => null), data.dataset('tv2_interruptions').catch(() => null)]);
    const tr = st.training_v2 || {};
    const fmt = (v) => Number(v).toLocaleString('en-US');
    const pct = tr.max_steps ? Math.round(100 * tr.step / tr.max_steps) : null;
    const asOf = String((st.meta && st.meta.generated_at) || '').replace('T', ' ').slice(0, 16);
    const finished = /finish|done/i.test(String(tr.state || '')) || pct >= 99;
    slot('tr-statement').textContent = finished ? 'Training v2 finished; v2 shipped on 21 Oct.' : pct != null ? `${pct} % trained: step ${fmt(tr.step)} of ${fmt(tr.max_steps)}.` : 'Retraining the domain agents.';
    const kv = (k, v) => h('div.tr-kv', null, h('span.label', { text: k }), h('span.tr-v', { text: v }));
    slot('tr-progress').append(h('div.tr-prog', { role: 'group', 'aria-label': 'Training progress' },
      h('div.tr-bar', { role: 'progressbar', 'aria-label': 'Training steps done', 'aria-valuemin': '0', 'aria-valuemax': String(tr.max_steps || 0), 'aria-valuenow': String(tr.step || 0) },
        h('i', { style: `width:${pct || 0}%` }), h('span.tr-bar__txt', { text: `${fmt(tr.step)} / ${fmt(tr.max_steps)} steps` })),
      h('div.tr-kvs', null,
        kv('Best dev loss', tr.best_dev_loss != null ? `${tr.best_dev_loss} (step ${fmt(tr.best_step)})` : '–'),
        kv('Speed', tr.recent_s_per_step ? `${tr.recent_s_per_step} s / step` : '–'),
        finished ? null : kv('Training left', tr.eta_training_hours != null ? `≈ ${tr.eta_training_hours} h + pauses` : '–'),
        kv('State', `${tr.state || '–'}`),
        kv('As of', asOf)),
      h('p.muted.tr-note', null, finished
        ? ['Read from the training log when the site was built. v2 replaced v1 on the board on 21 Oct; the agents later moved to mixA50 (25 Oct) and B50 (28 Oct). ', h('a', { href: '#/today', text: 'What runs today →' })]
        : 'Read from the training log when the site was built.')));

    const grid = slot('training');
    // 1) dev loss (every eval) + train loss per token
    const dh = tr.dev_loss_history || [];
    grid.append(ui.card({ span: 12, id: 'tv2_loss_curve',
      claim: dh.length ? `Dev loss ${dh[0].loss.toFixed(3)} → ${Number(tr.best_dev_loss).toFixed(3)} over ${dh.length} evals; train tracks dev, no overfitting` : undefined,
      chart: { type: 'line', id: 'tv2_loss_curve', opts: { logY: true, yMin: 0.04, yMax: 2 } },
      why: 'Loss is the only signal until the board test; the best checkpoint, not the last, is kept.' }));

    // 2) progress over wall-clock time, with every interruption on it (cause -> fix in the table)
    const intr = intrDs && intrDs.table;
    const prog = (((sess.folded || []).find((f) => f.id === 'tv2_progress') || {}).series || [{}])[0].points || [];
    const toIso = (w) => { const m = /^(\d\d)-(\d\d)(?:\s+(\d\d:\d\d))?/.exec(w); return m ? `2026-${m[1]}-${m[2]}T${m[3] || '12:00'}:00` : null; };
    const stepAt = (iso) => { let s = 0; for (const p of prog) { if (p.x <= iso) s = p.y; else break; } return s; };
    const rows = intr ? intr.rows : [];
    const ipts = rows.map((r) => { const x = toIso(r[0]); return x && { x, y: stepAt(x), label: r[1], note: `Cause: ${r[2]}. Fix: ${r[3]}.` }; }).filter(Boolean);
    const progDs = { meta: { ...sess.meta, id: 'tv2_progress_route', title: 'Training v2: optimizer step over time', unit: 'step', chart: { type: 'line' } },
      series: [{ name: 'optimizer step', role: 'ours', points: prog.map((p) => ({ x: p.x, y: p.y })) },
        { name: 'interruption (hover: cause and fix)', role: 'alt', color: 'rejected', dots: true, points: ipts }] };
    const tbl = h('div.ptable.tr-table', null, h('table', null,
      h('thead', null, h('tr', null, ['When', 'What happened', 'Cause', 'Fix'].map((c) => h('th', { text: c })))),
      h('tbody', null, rows.map((r) => h('tr', null, r.map((c) => h('td', { text: c })))))));
    grid.append(ui.card({ span: 12, claim: `${(sess.table && sess.table.rows || []).length} sessions, ${ipts.length} interruption causes, each now guarded`,
      why: 'Every stop resumed from a checkpoint; flat stretches are stops, crashes and sleeps.',
      chart: { type: 'line', data: progDs, opts: { yMin: 0, yMax: tr.max_steps || 4494, markLine: [{ y: tr.max_steps || 4494, label: '' }] } },
      body: h('details.tr-details', null, h('summary', { text: `Causes and fixes (${rows.length})` }), tbl),
      source: { files: [...sess.meta.source_files, ...(intrDs ? intrDs.meta.source_files : [])], script: sess.meta.script } }));

    // 3) what v2 changes (RETRAIN_V2_SPEC highlights)
    const P = Object.fromEntries(((plan.table && plan.table.rows) || []).map((r) => [r[0], r.slice(1)]));
    const g = (k, i, d) => (P[k] && P[k][i] != null ? P[k][i] : d);
    const nRoutine = routine ? ((routine.series.find((s) => s.name === 'train') || {}).points || []).reduce((a, p) => a + (p.y || 0), 0) : 0;
    const li = (b, t) => h('li', null, h('b', { text: b }), ' ', t);
    grid.append(ui.card({ span: 6, claim: 'What v2 changes, and why',
      why: 'Each change answers a measured v1 weakness from the window and placement studies.',
      body: h('ul.tr-list', null,
        li('Young events.', 'Onsets from minutes to hours before the window end (v1: 1–3 h), so the 40-min alert is read right (v1: 42 %).'),
        li('Any window length.', `${g('window lengths', 1, '2–12 h')} (v1: ${g('window lengths', 0, '4 h only')}).`),
        li('12 h history.', 'Level shift, drift and recent episodes go into the prompt.'),
        li('More patterns.', 'Recurring small spikes, old shifts, long drifts, 7 sensor-fault kinds.'),
        li('Routine is normal.', `${nRoutine ? fmt(nRoutine) + ' ' : ''}hard negatives (refills, load switching, daily cycles) against v1's 31 % false alarms.`),
        li('HVAC agent.', `roles ${g('roles', 1, '6')}; ${fmt(g('train examples', 1, 35946))} examples (v1: ${fmt(g('train examples', 0, 6480))}), LoRA ${String(g('LoRA rank / trainable', 1, 'r=32')).split(' /')[0]}.`),
        li('Shorter answers.', 'At most 2 observations; new fields: event active, onset, fault kind.')),
      source: { files: ['Code/smart-city-edge-agent/training/RETRAIN_V2_SPEC.md', ...plan.meta.source_files], script: plan.meta.script } }));
    // 4) acceptance + what happens after training
    grid.append(ui.card({ span: 6, claim: 'v2 ships only if it beats v1 on the board',
      why: 'The bar was fixed before training (spec #20), so it cannot move to fit the result.',
      body: h('div', null,
        h('span.label', { text: 'Acceptance · QIDK NPU · test months · paired vs v1' }),
        h('ul.tr-list.tr-check', null,
          li('Pattern ≥ 65 % at 40 min', '(v1: 42 %) and ≥ 88 % at 3 h.'),
          li('No regression', 'on the 54- and 900-window sets; JSON and policy ≥ 98 %.'),
          li('Fewer false alarms', 'on calm and routine windows than v1 (31 %).'),
          li('Latency is not a gate:', 'accuracy first, then optimise.')),
        h('span.label', { text: 'After the last step' }),
        h('ol.tr-list', null,
          h('li', { text: 'Keep the best dev-loss checkpoint; merge the adapter.' }),
          h('li', { text: 'Export GGUF Q4_0 (importance matrix from our prompts) for htpd.' }),
          h('li', { text: 'Run the acceptance test. Pass: deploy, v1 stays as revert. Fail: v1 stays, and we report which criterion failed.' }),
          h('li', { text: 'Latency pass back to ≤ 14.7 s for 13 agents and ≤ 3.8 s typical.' }),
          h('li', { text: 'Recalibrate confidence from v2 placement results; then the cross-domain reasoner.' }))),
      source: { files: ['Code/smart-city-edge-agent/training/RETRAIN_V2_SPEC.md'] } }));
    if (ctx.query && ctx.query.s === 'training') requestAnimationFrame(() => slot('training-sec').scrollIntoView({ block: 'start' }));
  } catch (e) {
    console.warn('[route] training', e);
    slot('training-sec').hidden = true;
  }

  // ---------- latency waterfalls (one at a time)
  const toS = (ds, scale) => ({ ...ds, meta: { ...ds.meta, unit: 's' },
    series: ds.series.map((s) => ({ ...s, points: s.points.map((p) => ({ ...p, y: +(p.y / scale).toFixed(3) })) })) });
  const WF = [
    { id: 'lat_route_13_agents', tab: '13 agents', why: 'htpd v1 was slower at first (red bar); HMX pipe, drafting and caches won it back.',
      prep: (ds) => ({ ...ds, series: [{ ...ds.series[0], points: ds.series[0].points.map((p, i) => i === 0
        ? { ...p, x: '≈ Genie, 13 agents', note: 'Midpoint of the logged 22–25 s range (not one run).' } : p) }] }),
      opts: { unit: 's', decimals: 1 } },
    { id: 'lat_route_incident', tab: '3-call incident', why: 'Same crowded-room incident, each step measured on the board.',
      prep: (ds) => toS(ds, 1000), opts: { unit: 's', decimals: 1 } },
    { id: 'lat_route_agent_call', tab: 'One agent call', why: '≈ bars are derived: separately measured deltas applied to the first value.',
      prep: (ds) => toS({ ...ds, series: ds.series.map((s) => ({ ...s, points: s.points.map((p) => p.derived
        ? { ...p, x: '≈ ' + p.x, note: `Derived, not an additive run (${p.delta}).` } : { ...p, note: p.delta }) })) }, 1000),
      opts: { unit: 's', decimals: 2 } },
  ];
  const tabs = slot('wf-tabs'), wfBox = slot('waterfall');
  const showWF = async (w) => {
    tabs.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.id === w.id)));
    ctx.charts.disposeIn?.(wfBox);
    const ds = w.prep(await data.dataset(w.id));
    wfBox.replaceChildren(ui.card({ span: 12, claim: ds.meta.claim, why: w.why,
      chart: { type: 'waterfall', data: ds, opts: { ...w.opts, height: window.innerWidth < 600 ? 300 : 360 } } }));
  };
  for (const w of WF) tabs.append(h('button.chip', { type: 'button', role: 'tab', 'data-id': w.id, onclick: () => showWF(w) }, w.tab));
  showWF(WF[0]);

  // ---------- tried and rejected (loss-framed)
  const LOSS = {
    'Parallel NPU sessions': 'Would make 4 agents 3× slower: 23.6 s → 76.5 s.',
    'poll=false': 'Would cost ~8% decode speed: 22.6 → 20.9 tok/s.',
    'First action-trim (string builder)': 'Would break JSON at chunk boundaries.',
    'Multi-graph bundle (3 graphs)': 'Would add 0.55 s to every call: 3.74 → 4.29 s.',
    'RPC / DCVS / mmap-budget / direct-io knobs': 'Zero gain: decode stayed 2.6–2.7 s.',
    'Pre-warming / streaming scripts': 'Saves nothing: Genie waits for the end of input.',
    'LADE lookahead decoding': 'Would change 13 of 14 answers; a stuck sensor read as normal.',
    'Grammar-constrained decoding': 'Would add ~0.45 s init and save no tokens.',
    'Continuous batching (shared engine)': 'Would cut 11 of 12 answers short.',
    'Batching while genied is up': 'Needs a second model copy; the SMMU limit refuses it.',
    'Agents on the Adreno GPU (OpenCL)': 'Would cost ~8.4 s per agent, with no batching gain.',
    'Longer windows for speed of detection (8/12 h)': 'Would cost +18% / +32% per agent and lose accuracy.',
  };
  const strip = slot('rejected');
  for (const r of route.latency_route.rejected) {
    const loss = LOSS[r.what] || (r.what.startsWith('Speculation') ? 'Changed outputs or doubled latency, for no gain.' : `${r.metric_before} → ${r.metric_after}`);
    strip.append(h('button.rt-rej', { type: 'button', onclick: async () => ui.modal(`Rejected: ${r.what}`, await evidence(r.evidence_id, r.what)) },
      h('span.label', { text: r.phase }), h('span.rt-rej__what', { text: r.what }), h('span.rt-rej__loss', { text: loss })));
  }

  // ---------- accuracy route (pattern accuracy, kept path vs dropped tries)
  const [quant, host, eng] = await Promise.all(['acc_quant_waterfall', 'acc_v1_host_eval', 'acc_device54_engines'].map((id) => data.dataset(id)));
  const q = (step) => quant.series[0].points.find((p) => p.step === step);
  const P = (x, p, extra = {}) => ({ x, y: p.y, k: p.k, n: p.n, lo: p.lo, hi: p.hi, ...extra });
  const D = (x, p, why) => ({ x, y: p.y, k: p.k, n: p.n, note: `${why} 95% CI ${Math.round(p.lo * 100)}–${Math.round(p.hi * 100)} %.` });
  const base = host.series.find((s) => s.role === 'alt' && /base/i.test(s.name)).points.find((p) => p.x === 'pattern');
  const ft = host.series.find((s) => s.role === 'ours').points.find((p) => p.x === 'pattern');
  const htpd = eng.series.find((s) => s.role === 'ours').points.find((p) => p.x === 'pattern');
  const ORDER = ['Base model', 'Fine-tuned (laptop)', '1st NPU export', 'MSE-clipped', 'GPTQ', 'Recalibrated', 'BOS fixed', 'Live, 54 windows', 'htpd runtime'];
  const accDs = {
    meta: { ...quant.meta, unit: 'fraction', source_files: [...quant.meta.source_files, ...eng.meta.source_files], chart: { type: 'line' } },
    series: [
      { name: 'Kept route', role: 'ours', points: [
        P('Fine-tuned (laptop)', ft, { note: 'Laptop eval, 150 windows.' }), P('1st NPU export', q(2)), P('GPTQ', q(6)),
        P('BOS fixed', q(9)), P('Live, 54 windows', q(10)), P('htpd runtime', htpd, { note: 'vs Genie 85.2 %: p = 0.45, not significant.' })] },
      { name: 'Tried, dropped', role: 'alt', color: 'rejected', dots: true, points: [
        D('Base model', base, 'Base Llama 3.2 3B, prompt only, laptop, 150 windows.'),
        D('MSE-clipped', q(3), 'Clipped weight scales made it worse.'), D('Recalibrated', q(7), 'Kaggle-recalibrated ranges: no gain.')] },
    ],
  };
  const accCard = ui.card({ span: 12, claim: '54% → 90.7% on the board: a prompt bug mattered most',
    why: 'Device steps n = 46 same windows; last two n = 54. Five steps survive only in HANDBOOK text.',
    chart: { type: 'line', data: accDs, opts: { order: ORDER, yMin: 0, yMax: 100, height: 340 } } });
  slot('accuracy').append(accCard);

  // ---------- peak-end
  slot('end').append(ui.card({ span: 12, id: 'ad_longrange_arms',
    claim: 'The shipped agent now catches 93% of old steps (was 73%)',
    why: 'Without the 12 h check we would miss about 1 in 4 old steps; with it, 1 in 14.' }));
  slot('next').append(ui.next('route'));
}
