// Home: anchor statement, Start-here path and status strip; the deck viewer below (it takes over once a deck is loaded).
export default async function mount(ctx) {
  const { root, ui, data, deck } = ctx;
  const $ = (s) => root.querySelector(`[data-slot="${s}"]`);

  $('path').append(ui.startHere());

  // Anchor: the two headline results, read from their datasets (not typed in), each labelled with where it was measured.
  const pick = (ds, role, x) => ((ds.series.find((s) => s.role === role) || {}).points || []).find((p) => p.x === x);
  const pct = (v) => `${Math.trunc(v * 100 + 1e-9)} %`; // same rounding as the dataset claim (42 %, 88 %)
  Promise.all([data.dataset('lat_chaos_genie_vs_htpd'), data.dataset('ad_placement_curve')]).then(([lat, pl]) => {
    const g = pick(lat, 'alt', '12 agents + synth'), o = pick(lat, 'ours', '12 agents + synth');
    const a40 = pick(pl, 'ours', '40 min'), a3 = pick(pl, 'ours', '3 h');
    const list = [];
    if (g && o) list.push({ before: `≈ ${g.y} s`, after: `${o.y} s`, label: '12-agent incident report on the QIDK: Genie → htpd.', meta: '16 Oct · Genie 46–48 s (logged range) · htpd measured' });
    if (a40 && a3) list.push({ before: pct(a40.y), after: pct(a3.y), label: 'Agent pattern accuracy: alert at 40 min → refined at 3 h (QIDK NPU).', meta: `v1 agents, 16 Oct · n = ${a3.n} events · v2 later lifted 40 min to 74 %` });
    if (list.length) $('anchor').replaceChildren(ui.anchors(list));
  }).catch(() => { /* datasets missing: the lead line above still says what this is */ });

  // Status strip: what runs on the board now (data/today.json), with links to Today and Journey.
  data.json('today.json').then((t) => {
    const f = t.final || {}, d = t.decisions || {};
    const item = (label, value) => ctx.h('div.status__item', null, ctx.h('span.label', { text: label }), ctx.h('span.v', { text: value }));
    const deploy = !f.present ? 'in progress' : f.passed ? 'passed' : 'rolled back';
    const live = f.present && f.passed;
    const reasoner = live && /rsn_v2/.test(d.reasoner || '') ? 'Qwen3.5-4B rsn_v2' : 'Qwen3.5-4B rsn_v1';
    const ch = t.chaos_tonight && t.chaos_tonight.summary;
    const strip = ctx.h('div.status', { role: 'status' },
      item('Agents', 'B50 · Llama 3.2 3B'), item('Reasoner', reasoner),
      item('Event → full report', ch && ch.done_min ? `${ch.done_min}–${ch.done_max} s` : '28–39 s'),
      item('Final deploy', deploy),
      item('As of', String((t.meta && t.meta.generated_at) || '').replace('T', ' ').slice(0, 16)));
    $('status').append(strip, ctx.h('p.deck-trlink', { style: 'margin:12px 0 0;display:flex;gap:8px;flex-wrap:wrap' },
      ctx.h('a.chip.chip--ours', { href: '#/today' }, 'Today: what runs on the board →'),
      ctx.h('a.chip', { href: '#/journey' }, 'Journey: ten steps to here →')));
  }).catch(() => { /* no today.json in this build: the strip is simply absent */ });

  const intro = [...root.querySelectorAll('[data-intro]')];
  return deck.mount($('deck'), {
    onChange: (loaded) => intro.forEach((el) => { el.hidden = loaded; }),
  });
}
