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
    if (g && o) list.push({ before: `≈ ${g.y} s`, after: `${o.y} s`, label: '12-agent incident report on the QIDK: Genie → htpd.', meta: 'Genie 46–48 s (logged range) · htpd measured' });
    if (a40 && a3) list.push({ before: pct(a40.y), after: pct(a3.y), label: 'Agent pattern accuracy: alert at 40 min → refined at 3 h (QIDK NPU).', meta: `n = ${a3.n} events · same model` });
    if (list.length) $('anchor').replaceChildren(ui.anchors(list));
  }).catch(() => { /* datasets missing: the lead line above still says what this is */ });

  data.status().then((st) => {
    if (!st || (st.meta && /mock/i.test(String(st.meta.source || st.meta.notes || '')) && !st.training_v2)) return;
    $('status').append(ui.statusStrip(st));
    if (st.training_v2) $('status').append(ctx.h('p.deck-trlink', { style: 'margin:12px 0 0' }, ctx.h('a.chip.chip--ours', { href: '#/route?s=training' }, 'Training v2: progress, losses, interruptions, acceptance →')));
  }).catch(() => { /* no status.json in this build: the strip is simply absent */ });

  const intro = [...root.querySelectorAll('[data-intro]')];
  return deck.mount($('deck'), {
    onChange: (loaded) => intro.forEach((el) => { el.hidden = loaded; }),
  });
}
