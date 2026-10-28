// Decisions page: every decision, the evidence for it, and what each rejected option would have cost.
// Contract: Website/src/js/CHARTS.md (no imports; everything comes from ctx).

const TOPICS = [
  ['use_case', 'Use case', ['use_case']],
  ['latency', 'Latency', ['latency']],
  ['hardware', 'Hardware', ['hardware']],
  ['accuracy', 'Accuracy', ['accuracy']],
  ['agent', 'Agent design', ['agent_design']],
  ['refinement', 'Refinement', ['refinement']],
  ['training', 'Training', ['training_v2', 'dataset_v2']],
  ['app', 'App / UX', ['app_ux']],
  ['ops', 'Ops', ['ops', 'timeline']],
];
const STATUSES = [['kept', 'Kept', 'kept'], ['replaced', 'Replaced', 'replaced'], ['pending', 'Pending', 'pending']];
const FEATURED = 7; // <= 7 cards per screen before "Show all" (SPEC chunking)
const topicOf = (t) => (TOPICS.find((x) => x[2].includes(t)) || TOPICS[TOPICS.length - 1])[0];
const topicLabel = (k) => (TOPICS.find((x) => x[0] === k) || ['', k])[1];

// "n.s." / p >= 0.05 / "within noise" in the decision or evidence text -> the result is "no worse", not "better".
function notSignificant(texts) {
  const t = texts.filter(Boolean).join(' ');
  if (/\bn\.s\.|not significant|none significant|no significant|within (the )?noise|not a significant/i.test(t)) return true;
  const ps = [...t.matchAll(/\bp\s*=\s*(0?\.\d+|1(?:\.0+)?)/gi)].map((m) => parseFloat(m[1]));
  return ps.length > 0 && ps.every((p) => p >= 0.05);
}

function pointsOf(ds) {
  return (ds.series || []).flatMap((s) => s.points || s.data || (s.nodes ? s.nodes : []) || []);
}
function hasCI(ds) {
  if (ds.ci && ds.ci.length) return true;
  return pointsOf(ds).some((p) => p && typeof p === 'object' && (p.lo != null || p.ci));
}

export default async function mount(ctx) {
  const { root, h, ui, charts, data } = ctx;
  const slot = (n) => root.querySelector(`[data-slot="${n}"]`);
  slot('next').append(ui.next('decisions'));

  let dj, cat, sitIdx = null;
  try {
    [dj, cat, sitIdx] = await Promise.all([data.decisions(), data.catalog(), data.json('situations_index.json').catch(() => null)]);
  } catch (err) {
    slot('anchor').append(ui.coming('Decisions', 'The decision log is missing from this build.'));
    return;
  }
  const catalog = new Map(cat.map((e) => [e.id, e]));
  const sits = (sitIdx && sitIdx.situations) || [];
  const sitByKey = Object.fromEntries(sits.map((x) => [x.key, x]));
  const practice = ((sitIdx && sitIdx.meta && sitIdx.meta.decisions_order) || []).map((k) => sitByKey[k]).filter((x) => x && x.measured);
  const practiceOf = (id) => practice.filter((x) => (x.decisions || []).includes(id)).map((x) => x.key).slice(0, 2);
  const sitShort = (x) => String((x && x.question) || '').replace(/^What happens when\s+/i, '').replace(/\?$/, '');
  const raw = dj.decisions || dj || [];
  // Groups: a decision may carry `children` (objects, or ids of other entries). Children render inside their group card.
  const rawById = new Map(raw.map((d) => [d.id, d]));
  const childIds = new Set();
  const childOf = new Map(); // child id -> group id
  for (const [cid, gid] of Object.entries(dj.alias || {})) childOf.set(String(cid).toUpperCase(), gid);
  for (const d of raw) for (const c of d.children || []) {
    const cid = typeof c === 'string' ? c : c && c.id;
    if (!cid) continue;
    childIds.add(cid); childOf.set(String(cid).toUpperCase(), d.id);
  }
  const kidsOf = (d) => (d.children || []).map((c) => (typeof c === 'string' ? rawById.get(c) : c)).filter(Boolean)
    .map((c) => ({ ...c, ev: (c.evidence_ids || []).filter((id) => catalog.has(id)) }));
  const all = raw.filter((d) => !childIds.has(d.id)).map((d) => {
    const kids = kidsOf(d);
    const ev = (d.evidence_ids || []).filter((id) => catalog.has(id));
    const entries = ev.map((id) => catalog.get(id));
    const measured = entries.filter((e) => e.chart && e.chart.type);
    // evidence weight: size of the evidence (log n), measured charts, alternatives answered, still standing
    const w = entries.reduce((s, e) => s + Math.log10(1 + (Number(e.n) || 0)) + (e.chart && e.chart.type ? 1 : 0), 0)
      + 0.4 * (d.rejected || []).length + (d.status === 'kept' ? 0.5 : 0) + (ev.length ? 0 : -5);
    const text = [d.id, d.title, d.chosen, d.why, ...(d.rejected || []).flatMap((r) => [r.option, r.why_not]),
      ...kids.flatMap((c) => [c.id, c.title, c.chosen, c.why])].join(' ').toLowerCase();
    return { ...d, ev, kids, topicKey: topicOf(d.topic), weight: w, measured: measured.length, text };
  }).filter((d) => d.ev.length || d.kids.some((c) => c.ev.length)); // no data behind it -> not shown
  const withEv = all;
  const nKids = all.reduce((n, d) => n + d.kids.length, 0);
  const nRej = all.reduce((s, d) => s + (d.rejected || []).length + d.kids.reduce((t, c) => t + (c.rejected || []).length, 0), 0);
  const sc = all.reduce((m, d) => ((m[d.status] = (m[d.status] || 0) + 1), m), {});

  // featured: highest evidence weight, at most 2 per topic so the first screen covers the whole project
  // groups carry an importance rank (1 = most); otherwise rank by evidence weight
  const byWeight = all.slice().sort((a, b) => (a.rank != null && b.rank != null ? a.rank - b.rank : b.weight - a.weight));
  const featured = new Set();
  const perTopic = {};
  for (const d of byWeight) {
    if (featured.size >= FEATURED) break;
    if (d.rank == null && (perTopic[d.topicKey] || 0) >= 2) continue;
    perTopic[d.topicKey] = (perTopic[d.topicKey] || 0) + 1;
    featured.add(d.id);
  }

  // ---------------------------------------------------------------- anchor
  slot('anchor').append(ui.anchor({
    value: nKids ? `${all.length} decision groups` : `${all.length} decisions`,
    label: nKids ? `${all.length + nKids} decisions in all, each with its evidence, and why the alternatives lost`
      : 'each with its evidence, and why the alternatives lost',
    meta: `${sc.kept || 0} kept · ${sc.replaced || 0} replaced · ${sc.pending || 0} pending · ${nRej} alternatives rejected`,
  }));

  // ---------------------------------------------------------------- controls
  const state = { topic: null, status: null, q: '', showAll: false };
  const asked = ctx.params[0] ? String(ctx.params[0]).toUpperCase() : null;
  // a child id deep-links to its group card
  const target = asked && childOf.has(asked) ? String(childOf.get(asked)).toUpperCase() : asked;
  if (target && !featured.has(target)) state.showAll = true;

  const filterBtn = (group, key, label, count) => {
    const b = h(`button.chip.dec-filter${group === 'status' ? '.chip--' + key : ''}`, { type: 'button', 'aria-pressed': 'false', 'data-key': key, 'data-topic': group === 'topic' ? key : null }, `${label} ${count}`);
    b.addEventListener('click', () => {
      state[group] = state[group] === key ? null : key;
      b.parentNode.querySelectorAll('.dec-filter').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.key === state[group])));
      state.showAll = false;
      renderList();
    });
    return b;
  };
  const topicRow = h('div.dec-row', { role: 'group', 'aria-label': 'Filter by topic' }, h('span.label', { text: 'Topic' }),
    TOPICS.map(([k, label]) => { const n = all.filter((d) => d.topicKey === k).length; return n ? filterBtn('topic', k, label, n) : null; }));
  const statusRow = h('div.dec-row', { role: 'group', 'aria-label': 'Filter by status' }, h('span.label', { text: 'Status' }),
    STATUSES.map(([k, label]) => filterBtn('status', k, label, sc[k] || 0)));
  const search = h('input.dec-search', { type: 'search', placeholder: 'Search decisions, options, reasons', 'aria-label': 'Search decisions' });
  let tmr = null;
  search.addEventListener('input', () => { clearTimeout(tmr); tmr = setTimeout(() => { state.q = search.value.trim().toLowerCase(); state.showAll = false; renderList(); }, 120); });
  ctx.onCleanup(() => clearTimeout(tmr));
  slot('controls').append(search, topicRow, statusRow);

  // ---------------------------------------------------------------- list
  const grid = slot('grid');
  const cards = new Map(); // id -> card element (built once, kept across filter changes)
  // build a card's evidence only when it nears the viewport
  const io = new IntersectionObserver((ents) => ents.forEach((en) => { if (en.isIntersecting) { io.unobserve(en.target); en.target._show(); } }), { rootMargin: '400px 0px' });
  ctx.onCleanup(() => io.disconnect());

  function matches() {
    const words = state.q.split(/\s+/).filter(Boolean);
    return byWeight.filter((d) => (!state.topic || d.topicKey === state.topic)
      && (!state.status || d.status === state.status)
      && words.every((w) => d.text.includes(w)));
  }

  function renderList() {
    const filtered = !!(state.topic || state.status || state.q);
    let list = matches();
    const total = list.length;
    if (!state.showAll) list = filtered ? list.slice(0, FEATURED) : list.filter((d) => featured.has(d.id));
    charts.disposeIn(grid);
    io.disconnect();
    for (const el of cards.values()) if (el._handle) { el._handle.dispose(); el._handle = null; el._drawn = false; }
    grid.replaceChildren(...list.map((d) => cardFor(d)));
    list.forEach((d) => io.observe(cards.get(d.id)));
    slot('count').textContent = total === 0 ? ''
      : (list.length < total ? `${filtered ? 'Top' : 'The'} ${list.length} ${all.some((d) => d.rank != null) ? "most important" : "by evidence weight"}, of ${total}` : `${total} decision${total === 1 ? '' : 's'}`);
    if (!total) grid.append(h('p.dec-empty', { text: 'No decision matches. Clear a filter or the search.' }));
    const more = slot('more');
    more.replaceChildren();
    if (list.length < total) more.append(h('button.btn', { type: 'button', onclick: () => { state.showAll = true; renderList(); } }, `Show all ${total}`));
    else if (state.showAll && total > FEATURED) more.append(h('button.btn', { type: 'button', onclick: () => { state.showAll = false; renderList(); slot('controls').scrollIntoView({ block: 'start' }); } }, 'Show fewer'));
  }

  // ---------------------------------------------------------------- one card
  function cardFor(d) {
    if (cards.has(d.id)) return cards.get(d.id);
    const status = STATUSES.find((s) => s[0] === d.status) || [d.status, d.status, null];
    const card = h('article.card.dec-card.fade-in', { id: 'dec-' + d.id, 'aria-labelledby': 'dec-t-' + d.id, 'data-topic': d.topicKey });
    const permalink = `#/decisions/${encodeURIComponent(d.id)}`;
    card.append(
      h('div.dec-card__meta', null,
        h('span.label', { text: `${d.id} · ${topicLabel(d.topicKey)}${d.date ? ' · ' + d.date : ''}` }),
        ui.chip(status[1], status[2])),
      h('h3.card__claim', { id: 'dec-t-' + d.id, text: d.title }),
      h('p.dec-card__chosen', null, h('b', { text: 'Chose' }), d.chosen || ''));

    const flags = h('div.dec-flags');
    const evTabs = h('div.dec-evs', { role: 'group', 'aria-label': 'Evidence' });
    const cap = h('p.dec-cap');
    const box = h('div.dec-box');
    card.append(flags, evTabs, box, cap);
    if (d.why) card.append(h('p.card__why', { text: d.why }));

    const rejs = h('div.dec-rejs', { role: 'group', 'aria-label': 'Rejected options' });
    (d.rejected || []).forEach((r, i) => {
      const b = h('button.dec-rej', { type: 'button', 'aria-pressed': 'false', 'data-i': String(i) },
        h('b', { text: r.option }), h('span', { text: ' — ' + (r.why_not || 'no reason recorded') }));
      b.addEventListener('click', () => select(state2.rej === i ? null : i));
      rejs.append(b);
    });
    if ((d.rejected || []).length) card.append(rejs);
    if (d.kids && d.kids.length) {
      const det = h('details.dec-kids', null, h('summary', null, h('span.label', { text: `${d.kids.length} related decision${d.kids.length === 1 ? '' : 's'}` })));
      for (const c of d.kids) {
        const st = STATUSES.find((x) => x[0] === c.status) || [c.status, c.status, null];
        const li = h('div.dec-kid', { id: 'dec-' + c.id },
          h('div.dec-card__meta', null, h('span.label', { text: `${c.id}${c.date ? ' · ' + c.date : ''}` }), st[1] ? ui.chip(st[1], st[2]) : null),
          h('p.dec-kid__title', { text: c.title || '' }),
          c.chosen ? h('p.dec-card__chosen', null, h('b', { text: 'Chose' }), c.chosen) : null,
          (c.rejected || []).length ? h('ul.dec-kid__rej', null, c.rejected.map((r) => h('li', null, h('b', { text: r.option }), ' — ' + (r.why_not || '')))) : null,
          c.ev.length ? h('div.dec-kid__ev', null, c.ev.map((id) => h('button.chip', { type: 'button', title: (catalog.get(id) || {}).title || id,
            onclick: () => ui.modal(c.title || id, ui.card({ id })) }, (catalog.get(id) || {}).title || id))) : null);
        det.append(li);
      }
      card.append(det);
      card._openKid = (cid) => { det.open = true; const k = det.querySelector('#dec-' + CSS.escape(cid)); if (k) k.classList.add('is-target'); return k; };
    }

    const foot = h('div.card__foot');
    const srcSlot = h('span');
    const linkBtn = h('a.chip.dec-link', { href: permalink, title: 'Link to this card' }, 'Link');
    linkBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const url = location.href.split('#')[0] + permalink;
      try { navigator.clipboard && navigator.clipboard.writeText(url); linkBtn.textContent = 'Copied'; setTimeout(() => (linkBtn.textContent = 'Link'), 1400); } catch (_) {}
      history.replaceState(null, '', permalink); // no re-route
    });
    foot.append(srcSlot);
    for (const sk of practiceOf(d.id)) {
      foot.append(h('button.chip', { type: 'button', 'data-topic': 'situations', title: 'See this decision at work in a measured situation',
        onclick: () => { const el = root.querySelector('#sit-' + sk); if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' }); } },
        `In practice: ${sitShort(sitByKey[sk])} ↓`));
    }
    if (d.handbook_section) {
      const sec = String(d.handbook_section).split(';')[0].trim();
      const file = /^\d/.test(sec) ? `HANDBOOK.md#${sec}` : /^SPEC/.test(sec) ? 'Website/SPEC.md' : sec.split(' ')[0];
      foot.append(h('a.chip.chip--source', { href: `#/proofs?file=${encodeURIComponent(file)}`, title: d.handbook_section }, h('span', { text: 'Log' }), h('span.chip__file', { text: d.handbook_section })));
    }
    foot.append(linkBtn);
    card.append(foot);

    // ---- evidence switching
    const state2 = { ev: d.ev[0] || null, rej: null };
    const evBtns = d.ev.map((id, i) => {
      const e = catalog.get(id);
      const b = h('button.dec-ev', { type: 'button', 'aria-pressed': 'false', title: e.title }, d.ev.length > 1 ? `Evidence ${i + 1}` : 'Evidence');
      b.addEventListener('click', () => { state2.ev = id; state2.rej = null; sync(); });
      return [id, b];
    });
    if (d.ev.length > 1) evBtns.forEach(([, b]) => evTabs.append(b)); else evTabs.remove();

    function select(i) {
      state2.rej = i;
      if (i != null) {
        const r = d.rejected[i];
        if (r.evidence_id && catalog.has(r.evidence_id)) state2.ev = r.evidence_id;
      } else state2.ev = d.ev.includes(state2.ev) ? state2.ev : d.ev[0];
      sync();
    }

    let shownEv = null;
    function sync() {
      evBtns.forEach(([id, b]) => b.setAttribute('aria-pressed', String(state2.rej == null && id === state2.ev)));
      rejs.querySelectorAll('.dec-rej').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.i) === state2.rej)));
      const r = state2.rej != null ? d.rejected[state2.rej] : null;
      cap.className = 'dec-cap' + (r ? ' is-rej' : '');
      cap.replaceChildren();
      if (r) {
        const own = d.ev.includes(r.evidence_id);
        const wn = String(r.why_not || '').trim();
        cap.append(h('b', { text: `Rejected: ${r.option}. ` }), wn && !/[.!?]$/.test(wn) ? wn + '.' : wn,
          own ? h('span', { text: ' Same measurement as our choice: ours in blue, the alternatives in grey.' }) : null);
      }
      if (card._drawn && shownEv === state2.ev) { if (r) hint(r.option); return; }
      if (card._drawn) draw(); else shownEv = null;
    }

    function setFlags(ds, e, textOnly) {
      flags.replaceChildren();
      if (textOnly) flags.append(ui.chip('Text evidence, not a measurement', 'warn'));
      else if (!hasCI(ds) && !(Number(e.n) > 1)) flags.append(ui.chip('Single run, no CI', 'warn'));
      const decTexts = state2.rej == null ? [d.why, d.chosen] : [];
      if (notSignificant([...decTexts, ds.meta && ds.meta.claim, ds.meta && ds.meta.notes]))
        flags.append(ui.chip("n.s. · read as 'no worse', not 'better'", 'ns'));
    }

    function draw() {
      const id = state2.ev;
      shownEv = id;
      if (card._handle) { card._handle.dispose(); card._handle = null; }
      box.replaceChildren();
      if (!id) { flags.replaceChildren(ui.chip('No dataset: text-only decision', 'warn')); return; }
      const e = catalog.get(id);
      const dsP = data.dataset(id);
      dsP.then((ds) => {
        if (shownEv !== id) return;
        const pts = pointsOf(ds);
        const textOnly = pts.length <= 1 || (!(e.chart && e.chart.type) && ds.table && pts.length < 3);
        setFlags(ds, e, textOnly);
        srcSlot.replaceChildren(ui.sourceChip(ds.meta || e));
        const capTitle = h('span', { text: (ds.meta && (ds.meta.claim || ds.meta.title)) || e.title });
        if (state2.rej == null) cap.replaceChildren(capTitle);
        if (textOnly) {
          const t = h('div.dec-text');
          if (ds.table && ds.table.rows) {
            t.append(h('table', null,
              h('thead', null, h('tr', null, (ds.table.columns || []).map((c) => h('th', { text: c })))),
              h('tbody', null, ds.table.rows.slice(0, 8).map((row) => h('tr', null, [].concat(row).map((c) => h('td', { text: String(c) })))))));
            if (ds.table.rows.length > 8) t.append(h('p.muted', { text: `+ ${ds.table.rows.length - 8} more in the source file` }));
          }
          if (ds.meta && ds.meta.notes) t.append(h('p', { text: ds.meta.notes }));
          if (!t.childNodes.length) t.append(h('p', { text: e.title }));
          box.replaceChildren(t);
          return;
        }
        const el = h('div.card__chart');
        box.replaceChildren(el);
        card._handle = charts.render(el, 'auto', ds, { title: d.title });
        card._handle.ready.then(() => { if (state2.rej != null) hint(d.rejected[state2.rej].option); }).catch(() => {});
      }).catch(() => { flags.replaceChildren(ui.chip('Evidence file missing from this build', 'bad')); });
    }

    // point at the rejected option inside a shared chart (best effort: word overlap with category / series names)
    function hint(option) {
      const c = card._handle && card._handle.chart && card._handle.chart();
      if (!c) return;
      try {
        const words = String(option).toLowerCase().split(/[^a-z0-9.]+/).filter((w) => w.length > 2 || /\d/.test(w));
        const score = (s) => words.reduce((n, w) => n + (String(s).toLowerCase().includes(w) ? 1 : 0), 0);
        const o = c.getOption();
        let best = { s: 0 };
        (o.series || []).forEach((s, si) => {
          const sn = score(s.name || '');
          if (sn > best.s) best = { s: sn, si, di: 0 };
        });
        const cats = [].concat(o.xAxis || [], o.yAxis || []).map((a) => a && a.data).find((x) => Array.isArray(x) && x.length);
        (cats || []).forEach((v, di) => { const sv = score(v && v.value != null ? v.value : v); if (sv > best.s) best = { s: sv, si: 0, di }; });
        c.dispatchAction({ type: 'hideTip' });
        if (best.s > 0) c.dispatchAction({ type: 'showTip', seriesIndex: best.si, dataIndex: best.di });
      } catch (_) { /* hint is optional */ }
    }

    card._show = () => {
      if (card._drawn) return;
      card._drawn = true;
      draw();
      sync();
    };
    sync();
    cards.set(d.id, card);
    return card;
  }

  renderList();

  // ---------------------------------------------------------------- in practice: measured situations proving the decisions
  if (practice.length) {
    slot('practice').hidden = false;
    practice.forEach((x) => slot('practicegrid').append(ui.situation(x, { span: 6 })));
  }

  // ---------------------------------------------------------------- deep link
  if (target) {
    const parent = cards.get(target);
    const kid = parent && asked !== target && parent._openKid ? parent._openKid(raw.find((x) => String(x.id).toUpperCase() === asked)?.id || asked) : null;
    const el = kid || parent;
    if (el) {
      parent._show();
      (kid ? parent : el).classList.add('is-target');
      // Charts above the target draw lazily and change height; keep the target pinned until the layout settles
      // (or the visitor scrolls / presses a key), then stop.
      let done = false;
      const settle = () => { if (!done) el.scrollIntoView({ block: 'start' }); };
      const ro = new ResizeObserver(() => requestAnimationFrame(settle));
      const evs = ['wheel', 'touchstart', 'keydown', 'pointerdown'];
      const end = () => { if (done) return; done = true; ro.disconnect(); evs.forEach((e) => window.removeEventListener(e, end)); };
      ro.observe(slot('grid'));
      evs.forEach((e) => window.addEventListener(e, end, { passive: true }));
      requestAnimationFrame(settle);
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(settle);
      setTimeout(end, 5000);
      ctx.onCleanup(end);
    } else {
      slot('count').textContent = `No decision with id ${target}.`;
    }
  }
}
