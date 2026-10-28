// Q&A page: professor questions -> one-line answer + evidence charts (data/qa.json). Contract: src/js/CHARTS.md.

// Likely first questions (matched by text, so the order in qa.json does not matter).
const TOP = [
  'Against what did you measure accuracy?',
  'What is the headline accuracy?',
  'Why the NPU and not the GPU?',
  'How fast is an incident now?',
  'How many false alarms?',
  'How did you avoid leakage?',
  'Can the AI switch anything off?',
  'What are the honest limits?',
  'What runs on the QIDK today?',
];

// Small synonym map so plain words find the right question offline.
const SYN = {
  gpu: ['npu', 'adreno'], npu: ['gpu', 'hexagon'], fast: ['latency', 'time', 'speed'], speed: ['latency', 'fast'],
  slow: ['latency'], time: ['latency'], fp: ['false'], 'false': ['alarms'], positive: ['alarms'], alarm: ['alarms'],
  heat: ['thermals', 'hot'], temperature: ['thermals', 'hot'], energy: ['power'], battery: ['power'],
  leak: ['leakage'], split: ['leakage'], test: ['test', 'sets'], baseline: ['rules', 'status'], thresholds: ['rules'],
  human: ['safety', 'approval'], approve: ['safety', 'approval'], hallucinate: ['hallucinated'], cloud: ['cloud'],
  llm: ['model'], finetune: ['fine-tune'], window: ['4-hour', 'window'], crash: ['crashes', 'robustness'],
  progress: ['training'], eta: ['training'], deployed: ['qidk', 'today'], plan: ['next'],
};

// Q&A category -> site topic colour (tokens.css); safety uses the severity red, limits the "rejected" red.
const CAT_TOPIC = { 'use case': 'use_case', use_case: 'use_case', accuracy: 'accuracy', 'agent design': 'agent_design', latency: 'latency', data: 'dataset_v2', hardware: 'hardware',
  'false alarms': 'refinement', safety: 'ops', 'status quo': 'timeline', model: 'training_v2', training: 'training_v2', thermals: 'hardware',
  robustness: 'app_ux', situations: 'app_ux', limits: 'rejected', next: 'agent_design', status: 'app_ux' };

const HONEST = /\b(not measured|not significantly|not yet|still to do|planned|unsolved|circular)/i;

const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9.%+\- ]+/g, ' ');
const words = (s) => norm(s).split(/\s+/).filter((w) => w.length > 1);
const STOP = new Set(['the', 'is', 'are', 'and', 'or', 'of', 'to', 'in', 'on', 'for', 'do', 'does', 'did', 'you', 'your', 'why', 'what', 'how', 'we', 'it', 'a', 'an', 'not', 'than', 'vs']);

// distance <= 1 (one edit), cheap check for typos
function near(a, b) {
  if (a === b) return true;
  if (Math.abs(a.length - b.length) > 1 || a.length < 4) return false;
  let i = 0, j = 0, e = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { i++; j++; continue; }
    if (++e > 1) return false;
    if (a.length > b.length) i++; else if (b.length > a.length) j++; else { i++; j++; }
  }
  return e + (a.length - i) + (b.length - j) <= 1;
}

function score(item, query) {
  const toks = words(query).filter((t) => !STOP.has(t));
  if (!toks.length) return 0;
  let total = 0;
  for (const t of toks) {
    const alts = [t, ...(SYN[t] || [])];
    let best = 0;
    for (const a of alts) {
      const w = a === t ? 1 : 0.6;
      if (item._q.includes(a)) best = Math.max(best, 3 * w);
      else if (item._cat.includes(a)) best = Math.max(best, 2.5 * w);
      else if (item._a.includes(a)) best = Math.max(best, 1.2 * w);
      else if (item._qw.some((x) => near(a, x) || (a.length >= 3 && x.startsWith(a)))) best = Math.max(best, 2 * w);
      else if (item._aw.some((x) => near(a, x))) best = Math.max(best, 0.8 * w);
    }
    total += best;
  }
  return total / toks.length;
}

export default async function mount(ctx) {
  const { root, ui, h } = ctx;
  const slot = (s) => root.querySelector(`[data-slot="${s}"]`);
  const input = root.querySelector('#qa-q');

  const [qa, status, decisions, sitIdx] = await Promise.all([
    ctx.data.qa(),
    ctx.data.status().catch(() => null),
    ctx.data.decisions().catch(() => null),
    ctx.data.json('situations_index.json').catch(() => null),
  ]);
  const sits = (sitIdx && sitIdx.situations) || [];
  const sitByKey = Object.fromEntries(sits.map((x) => [x.key, x]));
  const sitById = Object.fromEntries(sits.filter((x) => x.id).map((x) => [x.id, x]));
  const items = (qa.qa || qa.questions || qa).map((it, i) => ({
    ...it, i,
    _q: norm(it.q), _a: norm(it.short_answer), _cat: norm(it.category),
    _qw: words(it.q), _aw: words(it.short_answer),
  }));
  const decList = decisions ? (decisions.decisions || decisions) : [];
  const decTitle = Object.fromEntries((Array.isArray(decList) ? decList : []).map((d) => [d.id, d.title]));
  const cats = (qa.meta && qa.meta.categories) || [...new Set(items.map((x) => x.category))];
  const topItems = TOP.map((t) => items.find((x) => x.q === t)).filter(Boolean);

  slot('count').textContent = `${items.length} questions in ${cats.length} topics. Click one to open its evidence.`;

  // ---------- one question ----------
  function statsLine(meta, series) {
    const pts = (series || []).flatMap((s) => s.points || s.data || []);
    const parts = [];
    if (meta.n != null) parts.push(['n', String(meta.n)]);
    const ciPt = pts.find((p) => p && (p.lo != null || p.ci));
    if (ciPt) parts.push(['95% CI', ciPt.ci_method ? ciPt.ci_method.replace(/95$/, '').replace(/^wilson/, 'Wilson') : 'on chart']);
    const pm = [meta.claim, meta.notes, meta.title].join(' ').match(/p\s*(?:=|<|≤)\s*0?\.\d+/i);
    if (pm) parts.push(['', pm[0].replace(/\s+/g, ' ')]);
    else if (meta.unit === 'p-value') parts.push(['', 'p values on chart']);
    const el = h('p.qa-stats');
    parts.forEach(([k, v], j) => { if (j) el.append('  ·  '); if (k) el.append(k + ' '); el.append(h('b', { text: v })); });
    return parts.length ? el : null;
  }

  function evidenceCard(id) {
    if (sitById[id]) return ui.situation(sitById[id], { span: 12 });
    const body = h('div');
    const card = ui.card({ id, span: 12, body });
    ctx.data.dataset(id).then((ds) => {
      const m = (ds && ds.meta) || {};
      const s = statsLine(m, ds.series);
      if (s) body.append(s);
      if (m.notes) body.append(h('details.qa-notes', null, h('summary', { text: 'Test conditions and caveats' }), h('p', { text: m.notes })));
    }).catch(() => {});
    return card;
  }

  function buildBody(it) {
    const body = h('div.qa-body');
    const honest = HONEST.test(it.short_answer);
    body.append(h('p.qa-answer', { text: it.short_answer }));
    const links = h('div.qa-links');
    if (honest) links.append(ui.chip('Honest limit', 'warn'));
    if (it.situation_id && sitByKey[it.situation_id]) links.append(h('a.chip', { href: `#/qa?sit=${it.situation_id}`, 'data-topic': 'situations',
      onclick: (e) => { if (showSit) { e.preventDefault(); showSit(it.situation_id, true); } } }, 'Situation card ↑'));
    if (it.decision_id) links.append(h('a.chip.chip--ours', { href: `#/decisions/${it.decision_id}`, title: decTitle[it.decision_id] || '' }, `See decision ${it.decision_id} →`));
    links.append(h('a.chip', { href: `#/qa?q=${it.i}`, title: 'Link to this answer' }, 'Link'));
    body.append(links);
    if (it.category === 'status' && status) body.append(ui.statusStrip(status));
    const grid = h('div.grid');
    body.append(grid);
    const ids = it.evidence_ids || [];
    if (!ids.length && it.situation_id && sitByKey[it.situation_id]) grid.append(ui.situation(sitByKey[it.situation_id], { span: 12 }));
    const SHOW = 2;
    ids.slice(0, SHOW).forEach((id) => grid.append(evidenceCard(id)));
    if (ids.length > SHOW) {
      const more = h('button.btn', { type: 'button', onclick: () => { ids.slice(SHOW).forEach((id) => grid.append(evidenceCard(id))); more.remove(); } },
        `+ ${ids.length - SHOW} more evidence chart${ids.length - SHOW > 1 ? 's' : ''}`);
      body.append(more);
    }
    return body;
  }

  // Esc closes the open answer (unless a dialog is open: the dialog takes Esc first)
  let openLi = null;
  const onKey = (e) => {
    if (e.key !== 'Escape' || !openLi || document.querySelector('dialog[open]')) return;
    const li = openLi; li._close(); li._btn.focus({ preventScroll: true });
  };
  document.addEventListener('keydown', onKey);
  ctx.onCleanup(() => document.removeEventListener('keydown', onKey));

  function row(it) {
    const li = h('li.qa-item');
    const id = `qa-b-${it.i}`;
    const btn = h('button.qa-q', { type: 'button', 'aria-expanded': 'false', 'aria-controls': id },
      h('span.label.qa-cat', { text: it.category, 'data-topic': CAT_TOPIC[it.category] || null }), h('span.qa-t', { text: it.q }), h('span.qa-ico', { 'aria-hidden': 'true', text: '+' }));
    let body = null;
    const setOpen = (open) => {
      btn.setAttribute('aria-expanded', String(open));
      li.classList.toggle('is-open', open);
      if (open) {
        // one answer open at a time: opening another closes the previous one
        if (openLi && openLi !== li && openLi._close) openLi._close();
        openLi = li;
        if (!body) { body = buildBody(it); body.id = id; li.append(body); ui.enhanceTerms(body); }
        body.hidden = false;
      } else {
        if (body) body.hidden = true;
        if (openLi === li) openLi = null;
      }
    };
    btn.addEventListener('click', () => setOpen(btn.getAttribute('aria-expanded') !== 'true'));
    li.append(btn);
    li._open = () => { if (btn.getAttribute('aria-expanded') !== 'true') setOpen(true); };
    li._close = () => { if (btn.getAttribute('aria-expanded') === 'true') setOpen(false); };
    li._btn = btn;
    return li;
  }

  // ---------- list, search, chips ----------
  const list = slot('list'), more = slot('more'), empty = slot('empty'), listLabel = slot('listlabel');
  let cat = null, showAll = false;
  const rows = new Map();
  const getRow = (it) => { if (!rows.has(it.i)) rows.set(it.i, row(it)); return rows.get(it.i); };

  function render() {
    const q = input.value.trim();
    let shown;
    if (q) {
      shown = items.filter((x) => !cat || x.category === cat).map((x) => [x, score(x, q)]).filter(([, s]) => s >= 1)
        .sort((a, b) => b[1] - a[1]).map(([x]) => x);
      listLabel.textContent = `${shown.length} match${shown.length === 1 ? '' : 'es'}`;
    } else if (cat) {
      shown = items.filter((x) => x.category === cat);
      listLabel.textContent = `${cat} · ${shown.length}`;
    } else if (showAll) {
      shown = items;
      listLabel.textContent = `All ${items.length} questions`;
    } else {
      shown = topItems;
      listLabel.textContent = 'Likely first questions';
    }
    list.replaceChildren(...shown.map(getRow));
    empty.hidden = shown.length > 0;
    more.hidden = !!(q || cat || showAll);
  }

  const chipBtns = [];
  const mkChip = (label, value) => {
    const b = h('button.chip', { type: 'button', 'aria-pressed': String(value === cat), text: label, 'data-topic': value ? CAT_TOPIC[value] || null : null,
      onclick: () => { cat = value; chipBtns.forEach((x) => x.setAttribute('aria-pressed', String(x._v === cat))); render(); } });
    b._v = value; chipBtns.push(b); return b;
  };
  slot('chips').append(mkChip('All', null), ...cats.map((c) => mkChip(c, c)));

  // ---------- situations: 'What happens when...?' graphical stories, one at a time (data/situations_index.json) ----------
  let showSit = null;
  if (sits.length) {
    const sec = slot('sits'), pick = slot('sitpick'), holder = slot('sitcard');
    sec.hidden = false;
    const order = ((sitIdx.meta && sitIdx.meta.qa_order) || sits.map((x) => x.key)).filter((k) => sitByKey[k]);
    const short = (x) => String(x.question || x.key).replace(/^What happens when\s+/i, '').replace(/\?$/, '');
    const btns = order.map((k) => h('button.chip', { type: 'button', 'aria-pressed': 'false', 'data-key': k, 'data-topic': 'situations',
      onclick: () => showSit(k) }, short(sitByKey[k]) + (sitByKey[k].measured ? '' : ' · not yet measured')));
    pick.append(...btns);
    const cards = new Map();
    showSit = (k, scroll) => {
      if (!sitByKey[k]) return;
      btns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.key === k)));
      if (!cards.has(k)) cards.set(k, ui.situation(sitByKey[k], { span: 12 }));
      holder.replaceChildren(cards.get(k));
      const c = cards.get(k); if (c._chart) c._chart.drawNow();
      if (scroll) requestAnimationFrame(() => sec.scrollIntoView({ block: 'start' }));
    };
    showSit(ctx.query && sitByKey[ctx.query.sit] ? ctx.query.sit : order[0], !!(ctx.query && ctx.query.sit));
  }

  // ---------- use case first: what the project is for (data/use_case/* + the 'use case' questions) ----------
  (async () => {
    const isUC = (c) => /^use[ _]case$/i.test(String(c || ''));
    let cat = [];
    try { cat = await ctx.data.catalog(); } catch (e) { /* no catalog */ }
    const ucSets = cat.filter((d) => isUC(d.topic));
    const ucQs = items.filter((x) => isUC(x.category));
    if (!ucSets.length && !ucQs.length) return;
    const sec = slot('usecase');
    sec.hidden = false;
    const dss = await Promise.all(ucSets.map((d) => ctx.data.dataset(d.id).catch(() => null)));
    const ok = dss.filter(Boolean);
    const lead = ok.find((d) => d.meta && d.meta.statement) || null;
    slot('ucstatement').textContent = (lead && lead.meta.statement) || (qa.meta && qa.meta.use_case_statement)
      || 'Faster, fewer and clearer alerts for a campus operator, on one phone chip, offline.';
    // big numbers, read from the use-case datasets (meta.anchor wins when the data provides one)
    const byId = Object.fromEntries(ok.map((d) => [d.meta.id, d]));
    const ser = (d, re) => d && d.series.find((x) => re.test(x.name));
    const pt = (sr, re) => sr && (sr.points || sr.data || []).find((q) => re.test(String(q.x)));
    const sum = (sr) => (sr ? (sr.points || sr.data || []).reduce((t, q) => t + (Number(q.y) || 0), 0) : 0);
    const fmtK = (v) => Math.round(v).toLocaleString('en-US');
    const anchors = ok.map((d) => d.meta && d.meta.anchor).filter(Boolean);
    const na = byId.uc_breaches_need_action;
    if (na && !anchors.length) {
      const all = sum(ser(na, /^all/i)), crit = sum(ser(na, /critical/i));
      if (all && crit) anchors.push({ before: fmtK(all), after: fmtK(crit), label: 'Limit breaches in a year → the persistent, critical ones a person must see.', meta: 'real 2025 campus data · laptop analysis' });
    }
    const ar = byId.uc_alert_reduction;
    if (ar && anchors.length < 3) {
      const r = pt(ser(ar, /rules|status quo/i), /false/i), o = pt(ser(ar, /agent|ours/i), /false/i);
      if (r && o) anchors.push({ before: `${Math.round(r.y * 100)} %`, after: `${Math.round(o.y * 100)} %`, label: 'False alarms on calm windows: threshold rules → our agents, same detection.', meta: `n = ${o.n} calm windows · QIDK NPU` });
    }
    if (anchors.length) slot('ucanchors').append(ui.anchors(anchors.slice(0, 2)));
    const ORDER = ['uc_breaches_need_action', 'uc_alert_reduction', 'uc_time_to_insight', 'uc_example_incident'];
    ok.filter((d) => !(d.meta && d.meta.chart && d.meta.chart.type === 'none'))
      .sort((x, y) => ((ORDER.indexOf(x.meta.id) + 99) % 99) - ((ORDER.indexOf(y.meta.id) + 99) % 99)).slice(0, 4)
      .forEach((d) => slot('ucgrid').append(ui.card({ id: d.meta.id, span: 6 })));
    slot('uclist').append(...ucQs.map(row));
  })().catch((e) => console.warn('[qa] use case', e));
  let tmr = null;
  input.addEventListener('input', () => { clearTimeout(tmr); tmr = setTimeout(render, 80); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { const f = list.querySelector('.qa-item'); if (f) f._open(); } });
  more.addEventListener('click', () => { showAll = true; render(); });
  ctx.onCleanup(() => clearTimeout(tmr));
  render();

  // deep link: #/qa?q=<index> or #/qa?s=<search text>
  const dq = ctx.query && ctx.query.q != null ? items[+ctx.query.q] : null;
  if (ctx.query && ctx.query.s) { input.value = ctx.query.s; render(); }
  if (dq) {
    if (!topItems.includes(dq)) { showAll = true; render(); }
    const r = getRow(dq); r._open(); requestAnimationFrame(() => r.scrollIntoView({ block: 'start' }));
  }

  // ---------- side card: what is not measured (status lives on the home strip and Route > Training v2) ----------
  const side = slot('side');
  const gaps = [
    ['Energy per incident (joules)', 'Not measured: no free power rail on this dev kit. Planned with free methods only: Perfetto/ODPM rails if exposed, else fuel gauge plus thermal zones.'],
    ['Mode 1 / 2 / 3 accuracy on one labelled grid', 'Not measured, so not claimed. Planned: ~600 labelled incidents on the QIDK, Cochran\'s Q and pairwise McNemar.'],
    ['Status-quo alert flood (alarms per hour)', 'Never measured. Planned: replay 24-72 h of real Nov-Dec data, count raw threshold crossings vs alerts vs incidents.'],
    ['htpd vs Genie accuracy (90.7 % vs 85.2 %)', 'Not significant (McNemar p = 0.45, n = 54). We claim "no worse" (and ≈ 47 s → 20.7 s on the chaos incident), not "better".'],
    ['Arithmetic inside agent free text', 'The gate checks JSON, labels and evidence ids, not prose arithmetic. One passed answer said "863 ppm exceeds the warning limit of 1000 ppm": model text, numerically wrong (label and action were right). v2 caps free text at 2 short observations.'],
    ['Some numbers in the answers', 'A few come from logs, not from a chart; their source chip points to that log.'],
  ];
  side.append(ui.card({ span: 12, claim: 'What we have not measured yet', why: 'Stating the gaps lets you weigh every other number fairly.',
    body: h('ul.qa-unmeasured', null, gaps.map(([t, d]) => h('li', null, h('b', { text: t }), h('span', { text: d })))),
    source: { files: ['HANDBOOK.md#2.36'] } }));

  // ---------- peak-end ----------
  slot('peak').append(ui.anchors([
    { before: '20 %', after: '94 %', label: 'Pattern accuracy: base model → fine-tuned, 150 held-out windows (laptop).', meta: 'n = 150 · Wilson 95% CI' },
  ]));
  slot('next').append(ui.next('qa'));
}
