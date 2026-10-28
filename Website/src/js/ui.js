// UI components shared by every page. Page modules get these as ctx.ui (bound to the page's data loader).
import * as charts from './charts.js';

export const PAGES = [
  { id: 'deck', title: 'Deck', sub: 'The slides, full screen' },
  { id: 'today', title: 'Today', sub: 'What runs on the board now, with its numbers' },
  { id: 'journey', title: 'Journey', sub: 'Ten steps from one slow call to today' },
  { id: 'route', title: 'Route', sub: 'How we got here, step by step' },
  { id: 'decisions', title: 'Decisions', sub: 'What we chose, what we rejected, why' },
  { id: 'proofs', title: 'Proofs', sub: 'Every number, its file and its script' },
  { id: 'rawdata', title: 'Raw data', sub: 'Every reading, breach and training window' },
  { id: 'qa', title: 'Q&A', sub: 'The questions you will ask, answered with evidence' },
];
export const START_HERE = ['today', 'journey', 'qa'];
export const NEXT = { deck: 'today', today: 'journey', journey: 'route', route: 'decisions', decisions: 'qa', qa: 'proofs', proofs: 'rawdata', rawdata: 'deck', kit: 'deck' };
const pageTitle = (id) => (PAGES.find((p) => p.id === id) || { title: id }).title;

/** Tiny DOM helper: h('div.card', {attrs}, ...children) */
export function h(tag, attrs, ...kids) {
  const [name, ...cls] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (cls.length) el.className = cls.join(' ');
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className += (el.className ? ' ' : '') + v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}

const basename = (p) => String(p || '').split(/[\\/]/).pop();

export function createUI({ data, glossary = {} }) {
  const ui = {};

  /** Source chip. `src` = {files:[...], script} or a dataset meta ({source_files, script}). */
  ui.sourceChip = (src = {}) => {
    const files = src.files || src.source_files || [];
    const script = src.script;
    const first = files[0];
    const a = h('a.chip.chip--source', {
      href: first ? `#/proofs?file=${encodeURIComponent(first)}` : '#/proofs',
      title: [...files, script ? `script: ${script}` : null].filter(Boolean).join('\n') || 'source',
    }, h('span', { text: 'Source' }), first ? h('span.chip__file', { text: basename(first) + (files.length > 1 ? ` +${files.length - 1}` : '') }) : null);
    return a;
  };

  /** Generic chip: kind = ours|good|warn|bad|rejected|source */
  ui.chip = (text, kind) => h(`span.chip${kind ? '.chip--' + kind : ''}`, { text });

  /** Big-number anchor. {before?, after|value, label, meta?, ours?=true} */
  ui.anchor = ({ before, after, value, label, meta, ours = true }) => {
    const v = h('div.anchor__value');
    if (before != null) v.append(h('span.anchor__before', { text: before }), h('span.anchor__arrow', { text: '→', 'aria-label': 'to' }));
    v.append(h(`span.anchor__after${ours ? '.is-ours' : ''}`, { text: after ?? value }));
    return h('div.anchor.fade-in', null, v, label ? h('p.anchor__label', { text: label }) : null, meta ? h('p.anchor__meta.label', { text: meta }) : null);
  };
  ui.anchors = (list) => h('div.anchors', null, list.map(ui.anchor));

  /**
   * Card = claim above, chart, "why it matters" below, source chip (+ optional rejected chips).
   * spec = {claim, why, chart:{type, data?|id?, opts?}, source?, rejected?:[{label, claim?, why?, chart}], span?:4|6|8|12}
   */
  ui.card = (spec) => {
    if (typeof spec === 'string') spec = { id: spec };
    if (spec.id && !spec.chart) spec = { ...spec, chart: { type: 'auto', id: spec.id } };
    const card = h(`article.card.fade-in${spec.span ? '.span-' + spec.span : ''}`, spec.topic ? { 'data-topic': spec.topic } : null);
    const claim = h('h3.card__claim', { text: spec.claim || '' });
    card.append(claim);
    let handle = null;
    let dsP = null;
    if (spec.chart) {
      const box = h('div.card__chart');
      card.append(box);
      dsP = spec.chart.data != null ? Promise.resolve(spec.chart.data) : data.dataset(spec.chart.id);
      handle = charts.render(box, spec.chart.type || 'auto', dsP, { title: spec.claim, ...(spec.chart.opts || {}) });
      card._chart = handle;
    }
    if (spec.body) card.append(spec.body.nodeType ? spec.body : h('div', { html: spec.body }));
    const why = h('p.card__why', { text: spec.why || '' });
    if (spec.why) card.append(why);
    const foot = h('div.card__foot');
    const rejected = [].concat(spec.rejected || []);
    for (const r of rejected) {
      const rr = typeof r === 'string' ? { id: r, label: r } : r;
      foot.append(h('button.chip.chip--rejected', { type: 'button', title: rr.why || '',
        onclick: () => ui.modal(`Rejected: ${rr.label}`, ui.card({ ...rr, label: undefined, rejected: undefined, span: undefined })) }, `Rejected: ${rr.label}`));
    }
    if (spec.source) foot.append(ui.sourceChip(spec.source));
    if (dsP) {
      const slot = h('span');
      if (!spec.source) foot.append(slot);
      dsP.then((ds) => {
        const m = (ds && ds.meta) || {};
        if (m.topic && !card.dataset.topic) card.dataset.topic = spec.topic || m.topic;
        if (!spec.claim) claim.textContent = m.claim || m.title || '';
        if (!spec.why && m.why) { why.textContent = m.why; claim.parentNode && (card.querySelector('.card__chart') || claim).after(why); }
        if (!spec.source && m.source_files) slot.replaceWith(ui.sourceChip(m));
      }).catch(() => slot.replaceWith(ui.chip('data missing', 'warn')));
    }
    if (!claim.textContent && !dsP) claim.remove();
    if (foot.childNodes.length) card.append(foot);
    return card;
  };

  /** Tiny colour legend: ui.legend([['Kept', 'var(--o-kept)'], ...]) - a dot + word per colour. */
  ui.legend = (items, label) => h('div.legend', { 'aria-label': label || 'Colour legend' },
    items.map(([text, color]) => h('span', null, h('i', { style: `--c:${color}`, 'aria-hidden': 'true' }), text)));
  ui.TOPIC_LEGEND = [['Latency', 'var(--t-latency)'], ['Hardware', 'var(--t-hardware)'], ['Accuracy', 'var(--t-accuracy)'],
    ['Agent design', 'var(--t-agent_design)'], ['Refinement', 'var(--t-refinement)'], ['Training', 'var(--t-training_v2)'],
    ['Dataset', 'var(--t-dataset_v2)'], ['App / UX', 'var(--t-app_ux)'], ['Ops', 'var(--t-ops)']];

  /** Modal dialog with a title and a node. Closes on Esc / backdrop / x. */
  ui.modal = (title, node) => {
    const dlg = h('dialog.modal', { 'aria-label': title });
    const close = () => { charts.disposeIn(dlg); dlg.close(); dlg.remove(); };
    dlg.append(
      h('div.modal__head', null, h('span.label', { text: title }), h('button.icon-btn', { type: 'button', 'aria-label': 'Close', onclick: close }, '×')),
      h('div.modal__body', null, node));
    dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); close(); });
    document.body.append(dlg);
    dlg.showModal();
    // charts in a dialog: render now (IntersectionObserver may not fire inside top layer immediately)
    if (node._chart) node._chart.drawNow();
    return dlg;
  };

  /** "Start here" guided path: Route -> Decisions -> Q&A */
  ui.startHere = () => h('nav.path', { 'aria-label': 'Start here' },
    START_HERE.map((id) => {
      const p = PAGES.find((x) => x.id === id);
      return h('a.path__step', { href: `#/${id}` }, h('span.label', { text: 'Step' }), h('span.path__title', { text: p.title }), h('span.path__sub', { text: p.sub }));
    }));

  /** Footer "Next ->" link. `to` defaults to the standard order. */
  ui.next = (from, to) => {
    const target = to || NEXT[from] || 'deck';
    return h('footer.next', null,
      h('span.label', { text: ['qa', 'proofs', 'rawdata'].includes(from) ? 'Then' : 'Next' }),
      h('a.next__link', { href: `#/${target}` }, h('span', { text: pageTitle(target) }), h('span', { text: '→', 'aria-hidden': 'true' })));
  };

  /** Status strip from data/status.json (defensive: renders whatever fields exist). */
  ui.statusStrip = (st) => {
    const strip = h('div.status', { role: 'status' });
    if (!st) return strip;
    const item = (label, value, frac) => {
      const el = h('div.status__item', null, h('span.label', { text: label }), h('span.v', { text: value }));
      if (frac != null && Number.isFinite(frac)) el.append(h('div.status__bar', { 'aria-hidden': 'true' }, h('i', { style: `width:${Math.max(0, Math.min(100, frac * 100)).toFixed(1)}%` })));
      return el;
    };
    const tr = st.training || st.train || st.training_v2 || null;
    const num = (v, d = 3) => (typeof v === 'number' ? v.toFixed(d) : String(v));
    if (tr) {
      const step = tr.step ?? tr.current_step, total = tr.total_steps ?? tr.max_steps;
      if (step != null) strip.append(item(st.training_v2 && !st.training ? 'Retrain v2' : 'Training', total ? `step ${step} / ${total}` : `step ${step}`, tr.progress ?? (total ? step / total : null)));
      const loss = tr.loss ?? tr.train_loss; if (loss != null) strip.append(item('Loss', num(loss)));
      const ev = tr.eval_loss ?? tr.best_dev_loss; if (ev != null) strip.append(item(tr.eval_loss != null ? 'Eval loss' : 'Best dev loss', num(ev)));
      const running = !/stop|paused|done|finished/i.test(String(tr.state || tr.status || ''));
      const eta = tr.eta ?? (running ? tr.trainer_eta_text : null) ?? (tr.eta_training_hours != null ? `≈ ${num(tr.eta_training_hours, 1)} h of training` : null);
      if (eta) strip.append(item(running ? 'ETA' : 'Remaining', String(eta)));
      if (tr.state || tr.status) strip.append(item('State', String(tr.state || tr.status)));
    }
    if (st.app_version) strip.append(item('App', String(st.app_version)));
    const dep = st.deployed || st.deployed_on_qidk;
    if (dep) {
      const txt = typeof dep === 'string' ? dep : (dep.model || dep.npu_engine || dep.summary || '');
      if (txt) strip.append(item('On the QIDK', String(txt).split(' (')[0]));
    }
    const asOf = st.as_of || st.generated_at || (st.meta && st.meta.generated_at);
    if (asOf) strip.append(item('As of', String(asOf).replace('T', ' ').slice(0, 16)));
    if (st.meta && st.meta.source_files) strip.append(ui.sourceChip(st.meta));
    return strip;
  };

  /** "Coming" placeholder for pages not built yet. */
  ui.coming = (title, line) => h('section.coming.section', null, h('span.label', { text: title }), h('p.statement', { text: line || 'Coming.' }));

  // ---------------- glossary tooltips ----------------
  let tip = null;
  const showTip = (el) => {
    const key = el.dataset.term || el.textContent.trim();
    const def = glossary[key] || glossary[key.toUpperCase()] || glossary[key.toLowerCase()];
    if (!def) return;
    hideTip();
    tip = h('div.tip', { role: 'tooltip', id: 'tip' }, h('b', { text: key }), typeof def === 'string' ? def : def.def || '');
    document.body.append(tip);
    const r = el.getBoundingClientRect();
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = Math.min(Math.max(16, r.left + r.width / 2 - tw / 2), window.innerWidth - tw - 16);
    let y = r.top - th - 8; if (y < 8) y = r.bottom + 8;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
    el.setAttribute('aria-describedby', 'tip');
  };
  const hideTip = () => { if (tip) { tip.remove(); tip = null; } };
  ui.glossary = glossary;
  /** Mark up every [data-term] (and <abbr>) under root with a hover/focus definition. */
  ui.enhanceTerms = (root) => {
    root.querySelectorAll('[data-term], abbr').forEach((el) => {
      if (el._term) return; el._term = true;
      el.classList.add('term');
      if (!el.hasAttribute('tabindex')) el.tabIndex = 0;
      el.removeAttribute('title');
      el.addEventListener('mouseenter', () => showTip(el));
      el.addEventListener('mouseleave', hideTip);
      el.addEventListener('focus', () => showTip(el));
      el.addEventListener('blur', hideTip);
      el.addEventListener('click', () => (tip ? hideTip() : showTip(el)));
      el.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideTip(); });
    });
  };
  /** A glossary term as an element: ui.term('NPU') */
  ui.term = (key, text) => { const s = h('span', { 'data-term': key, text: text || key }); ui.enhanceTerms(h('div', null, s)); return s; };
  window.addEventListener('scroll', hideTip, { passive: true });
  ui._hideTip = hideTip;

  // ---------------- situation story card (data/situations/*, data/situations_index.json) ----------------
  const SEV_VAR = { critical: 'var(--sev-critical)', warning: 'var(--sev-warning)', normal: 'var(--sev-normal)', sensor_fault: 'var(--sev-fault)' };
  const words_ = (v) => String(v ?? '').replace(/_/g, ' ');
  const sevChip = (sev, text) => h('span.chip.sit-chip', { style: `--c:${SEV_VAR[sev] || 'var(--muted)'}`, text: text ?? words_(sev) });
  const secs = (ms) => `${(ms / 1000).toFixed(1)} s`;
  /**
   * One graphical story: claim, sensor trace (alert + refined markers, limits), stage timeline with what the agent said,
   * the 12 h check, the outcome (severity, title, action, approval, latency), why it matters, decision links.
   * entry = an item of situations_index.json ({key, id, question, measured, claim?, why?, detail?, decisions}) or a dataset id.
   */
  ui.situation = (entry, o = {}) => {
    if (typeof entry === 'string') entry = { id: entry, key: entry.replace(/^sit_/, ''), measured: true };
    const card = h(`article.card.sit.fade-in${o.span ? '.span-' + o.span : ''}${o.full ? '.sit--full' : ''}`, { id: o.full ? null : `sit-${entry.key}`, 'data-topic': 'situations' });
    const q = h('span.label.sit__q', { text: entry.question || '' });
    const exp = o.full ? null : h('button.icon-btn.sit__exp', { type: 'button', 'aria-label': 'Expand this situation', title: 'Expand',
      html: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
      onclick: () => ui.modal(entry.question || 'Situation', ui.situation(entry, { full: true })) });
    const claim = h('h3.card__claim', { text: entry.claim || '' });
    card.append(h('div.sit__head', null, q, exp), claim);
    const decs = () => (entry.decisions || []).map((d) => h('a.chip.chip--ours', { href: `#/decisions/${d}`, title: 'The decision this situation proves' }, `Decision ${d} →`));
    if (!entry.measured) {
      card.classList.add('sit--nm');
      card.append(h('div.sit-nm', null, ui.chip('Not yet measured', 'warn'), h('p', { text: entry.detail || '' })));
      if (entry.why) card.append(h('p.card__why', { text: entry.why }));
      card.append(h('div.card__foot', null, ...decs(), entry.source_files ? ui.sourceChip({ files: entry.source_files }) : null));
      return card;
    }
    const box = h('div.card__chart.sit__chart');
    card.append(box);
    const dsP = data.dataset(entry.id);
    const handle = charts.render(box, 'trace', dsP, { title: entry.question });
    card._chart = handle;
    const rest = h('div.sit__rest');
    card.append(rest);
    dsP.then((ds) => {
      const m = ds.meta || {}, s = ds.situation || {};
      if (!claim.textContent) claim.textContent = m.claim || '';
      if (!q.textContent) q.textContent = s.question || m.title || '';
      const st = s.stages || [];
      // timeline: event start -> alert -> agents done -> refined 1.5 h -> refined 3 h
      const tl = h('ol.sit-tl', { 'aria-label': 'What happened, stage by stage' });
      for (const x of st) {
        const sev = x.severity || (x.key === 'alert' ? null : null);
        const dim = x.when === 'not measured' || x.when === 'before this view';
        const li = h(`li.sit-st${dim ? '.is-dim' : ''}`, { style: `--c:${SEV_VAR[sev] || (x.key === 'alert' ? 'var(--text)' : 'var(--muted)')}` },
          h('span.sit-st__dot', { 'aria-hidden': 'true' }),
          h('span.label.sit-st__name', { text: x.label }),
          h('span.sit-st__when', { text: x.key === 'start' && s.readings_to_alert != null ? `${x.when} · ${s.readings_to_alert} readings` : x.when }));
        if (x.pattern || x.status) li.append(h('span.sit-st__chips', null, h('span.chip.sit-chip.sit-chip--pat', { text: words_(x.pattern) }), sevChip(x.status)));
        else if (x.severity && x.key === 'early') li.append(h('span.sit-st__chips', null, sevChip(x.severity)));
        if (x.said && !dim && !(x.pattern || x.status)) li.append(h('span.sit-st__said', { text: x.said }));
        tl.append(li);
      }
      if (s.multi) rest.prepend(h('p.sit__hint', { text: 'Each line scaled to its own range · hover for real values' }));
      rest.append(tl);
      // the 12 h check
      const c12 = s.check_12h || {};
      const fired = !!c12.stage;
      rest.append(h(`div.sit-row.sit-12h${fired ? '.is-fired' : ''}`, null, h('span.label', { text: '12 h check' }),
        h('span.sit-row__v', { text: fired ? `${c12.stage === 'early' ? 'at the alert' : 'at ' + c12.stage.replace('h', ' h')}: ${String(c12.finding).replace(/^12 h view:\s*/, '')}` : c12.finding }),
        c12.raised_severity ? sevChip('warning', 'raised to warning') : null));
      // multi-sensor: agent verdicts as a severity bar
      const out = s.outcome || {};
      if (s.multi && out.final_app_status_counts) {
        const cnt = out.final_app_status_counts; const tot = Object.values(cnt).reduce((a, b) => a + b, 0) || 1;
        const order = ['critical', 'warning', 'sensor_fault', 'normal'];
        rest.append(h('div.sit-row', null, h('span.label', { text: `${tot} agents said` }),
          h('div.sit-bar', { role: 'img', 'aria-label': order.filter((k) => cnt[k]).map((k) => `${cnt[k]} ${words_(k)}`).join(', ') },
            order.filter((k) => cnt[k]).map((k) => h('i', { style: `flex:${cnt[k]};--c:${SEV_VAR[k]}`, title: `${cnt[k]} ${words_(k)}`, text: String(cnt[k]) })))));
      }
      // outcome
      const lat = [];
      if (out.early_ms != null && !s.multi) lat.push(`agents ${secs(out.early_ms)}`);
      if (out.refine_ms && out.refine_ms.length) lat.push(`re-reads ${out.refine_ms.map(secs).join(' · ')}`);
      if (out.final_app_s != null) lat.push(`final app ${out.final_app_s.toFixed(1)} s`);
      const facts = h('dl.sit-out');
      const fact = (k, v) => { if (v) facts.append(h('div', null, h('dt.label', { text: k }), h('dd', null, v))); };
      fact('Severity', sevChip(out.severity));
      fact('Title', h('span.sit-out__title', { text: out.title || '', title: out.title || '' }));
      fact('Action', out.action ? h('span.chip', { text: words_(out.action) }) : null);
      fact('Approval', h('span', { text: out.requires_human_approval ? `a person decides (${out.approval || 'pending'})` : String(out.approval || '') }));
      fact('Time', h('span.sit-out__mono', { text: lat.join(' · ') }));
      if (out.npu_calls != null) fact('NPU calls', h('span.sit-out__mono', { text: String(out.npu_calls) }));
      rest.append(facts);
      if (m.why) rest.append(h('p.card__why', { text: m.why }));
      if (o.full && m.notes) rest.append(h('p.sit__notes', { text: m.notes }));
      rest.append(h('div.card__foot', null, ...decs(), ui.sourceChip(m)));
    }).catch((e) => { rest.append(ui.chip('data missing', 'warn')); console.warn('[situation]', entry.id, e); });
    return card;
  };

  ui.h = h;
  return ui;
}
