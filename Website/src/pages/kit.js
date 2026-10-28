// Demo of every component and chart type (mock data). Page agents: copy patterns from here.
const M = (id, title, unit, extra = {}) => ({ id, title, unit, n: extra.n, source_files: [`proofs/MOCK/${id}.json`], script: 'Website/src/pages/kit.js', generated_at: '2026-10-19', ...extra });

export default async function mount(ctx) {
  const { root, ui } = ctx;
  const slot = (s) => root.querySelector(`[data-slot="${s}"]`);

  slot('anchors').append(ui.anchors([
    { before: '47 s', after: '21 s', label: 'Mock anchor: before → after, ours in blue.' },
    { value: '94 %', label: 'Mock single big number.', meta: 'n = 240 · 95% CI 91–96 %' },
  ]));

  const cards = [
    { span: 6, claim: 'Bar: ours against two baselines', why: 'Contrast with the status quo, never ours alone.',
      chart: { type: 'bar', data: { meta: M('bar', 'Accuracy', '%', { n: 240 }), series: [{ name: 'accuracy', data: [
        { x: 'Rules', y: 61, n: 240, ci: [55, 67] }, { x: 'Base Llama', y: 48, n: 240, ci: [42, 54] }, { x: 'Fine-tuned (ours)', y: 89, n: 240, ci: [85, 92], ours: true }] }] } },
      rejected: [{ label: 'GPU path', claim: 'Mock: the GPU path was 3× slower', why: 'Rejected because it lost on latency at equal accuracy.',
        chart: { type: 'bar', data: { meta: M('gpu', 'Latency', 's'), series: [{ name: 'latency', data: [{ x: 'GPU', y: 63, n: 30, ci: [58, 70] }, { x: 'NPU (ours)', y: 21, n: 30, ci: [19, 23], ours: true }] }] } } }] },
    { span: 6, claim: 'Stacked bar: where the time goes', why: 'Shows which stage dominates.',
      chart: { type: 'stackedBar', opts: { unit: 's' }, data: { meta: M('stack', 'Time split', 's'), series: [
        { name: 'prefill', data: [{ x: 'v1', y: 9 }, { x: 'v4', y: 5 }, { x: 'v6', y: 2 }] },
        { name: 'decode', data: [{ x: 'v1', y: 30 }, { x: 'v4', y: 18 }, { x: 'v6', y: 15 }] },
        { name: 'other', ours: true, data: [{ x: 'v1', y: 8 }, { x: 'v4', y: 6 }, { x: 'v6', y: 4 }] }] } } },
    { span: 12, claim: 'Waterfall: the latency route', why: 'Each step and its measured effect, in order.',
      chart: { type: 'waterfall', opts: { unit: 's' }, data: { meta: M('wf', 'Latency route', 's'), series: [{ name: 'route', data: [
        { x: 'Genie CLI', y: 47, kind: 'total', n: 20 }, { x: 'Keep model loaded', y: -12, n: 20, ci: [-14, -10] }, { x: 'Batched daemon', y: -7, n: 20 },
        { x: 'Longer prompt', y: 2, n: 20, note: 'a cost we accepted for accuracy' }, { x: 'Prefix cache', y: -6, n: 20 }, { x: 'NEON argmax', y: -3, n: 20 }, { x: 'Now', kind: 'total', ours: true }] }] } } },
    { span: 6, claim: 'Line with 95% CI band', why: 'Training converges; the band shows run-to-run spread.',
      chart: { type: 'line', opts: { xName: 'step', yName: 'loss' }, data: { meta: M('line', 'Loss', ''), series: [
        { name: 'v2 (ours)', ours: true, data: Array.from({ length: 12 }, (_, i) => ({ x: i * 100, y: +(2.2 * Math.exp(-i / 4) + 0.3).toFixed(3), ci: [+(2.1 * Math.exp(-i / 4) + 0.26).toFixed(3), +(2.3 * Math.exp(-i / 4) + 0.34).toFixed(3)] })) },
        { name: 'v1', data: Array.from({ length: 12 }, (_, i) => ({ x: i * 100, y: +(2.2 * Math.exp(-i / 6) + 0.45).toFixed(3) })) }] } } },
    { span: 6, claim: 'Scatter: predicted vs measured', why: 'Points near the diagonal mean the estimate is honest.',
      chart: { type: 'scatter', opts: { xName: 'measured s', yName: 'predicted s', diagonal: [[0, 0], [40, 40]] }, data: { meta: M('scatter', 'Pred vs measured', 's'), series: [
        { name: 'ours', ours: true, data: Array.from({ length: 30 }, (_, i) => ({ x: 5 + i, y: +(5 + i + Math.sin(i) * 3).toFixed(2), label: `case ${i}` })) },
        { name: 'baseline', data: Array.from({ length: 30 }, (_, i) => ({ x: 5 + i, y: +(8 + i * 0.6 + Math.cos(i) * 5).toFixed(2) })) }] } } },
    { span: 6, claim: 'Boxplot: spread per mode', why: 'Medians hide tails; the box shows them.',
      chart: { type: 'boxplot', opts: { unit: 's' }, data: { meta: M('box', 'Analysis time', 's'), series: [{ name: 'time', data: [
        { x: 'Mode 1', min: 0.1, q1: 0.1, median: 0.2, q3: 0.2, max: 0.3, n: 80 }, { x: 'Mode 2', min: 6, q1: 9, median: 11, q3: 14, max: 22, n: 80 },
        { x: 'Mode 3', min: 2.3, q1: 3.2, median: 4.1, q3: 6, max: 12, n: 80, ours: true }] }] } } },
    { span: 6, claim: 'Heatmap: accuracy by window and sensor', why: 'Finds where a choice wins and where it does not.',
      chart: { type: 'heatmap', opts: { unit: '%' }, data: { meta: M('heat', 'Accuracy grid', '%'), series: [{ name: 'acc', data:
        ['1 h', '2 h', '4 h', '8 h', '12 h'].flatMap((w, i) => ['air', 'water', 'power', 'occupancy'].map((s, j) => ({ x: w, y: s, v: Math.round(60 + 30 * Math.sin((i + 1) * (j + 2) / 5)), n: 40 }))) }] } } },
    { span: 6, claim: 'Point + 95% CI: the difference is real', why: 'Overlap would mean no proven gain.',
      chart: { type: 'ciDot', opts: { unit: 'pp', ref: 0, refLabel: 'no change' }, data: { meta: M('ci', 'Gain', 'pp'), series: [{ name: 'gain', data: [
        { x: '4 h vs 1 h', y: 12, ci: [7, 17], n: 240, ours: true }, { x: '8 h vs 4 h', y: 1, ci: [-3, 5], n: 240 }, { x: '12 h vs 4 h', y: -2, ci: [-7, 3], n: 240 }] }] } } },
    { span: 6, claim: 'Sankey: where samples go', why: 'Shows the share that reaches the AI and survives the policy gate.',
      chart: { type: 'sankey', opts: { unit: 'windows' }, data: { meta: M('sankey', 'Flow', 'windows'), series: [{ name: 'flow',
        nodes: [{ name: 'windows' }, { name: 'normal' }, { name: 'flagged' }, { name: 'AI accepted', ours: true }, { name: 'AI rejected' }],
        links: [{ source: 'windows', target: 'normal', value: 700 }, { source: 'windows', target: 'flagged', value: 300 }, { source: 'flagged', target: 'AI accepted', value: 270 }, { source: 'flagged', target: 'AI rejected', value: 30 }] }] } } },
    { span: 6, claim: 'Funnel: from data to training set', why: 'What was filtered, and how much remains.',
      chart: { type: 'funnel', opts: { unit: 'examples' }, data: { meta: M('funnel', 'Dataset', 'examples'), series: [{ name: 'f', data: [
        { x: 'candidates', y: 12000 }, { x: 'deduplicated', y: 9100 }, { x: 'leak-free', y: 7400 }, { x: 'final', y: 6480, ours: true }] }] } } },
    { span: 12, claim: 'Timeline: kept, dropped, pending', why: 'The route in one glance; hover a dot for the detail.',
      chart: { type: 'timeline', data: { meta: M('tl', 'Route', ''), series: [
        { name: 'latency', data: [{ date: '2026-09-20', label: 'Genie CLI', outcome: 'dropped' }, { date: '2026-10-02', label: 'Kept model loaded', outcome: 'kept' }, { date: '2026-10-16', label: 'htpd', outcome: 'kept' }] },
        { name: 'accuracy', data: [{ date: '2026-09-25', label: 'Base Llama', outcome: 'dropped' }, { date: '2026-10-05', label: 'Fine-tune v1', outcome: 'kept' }, { date: '2026-10-17', label: 'Retrain v2', outcome: 'pending' }] },
        { name: 'agent', data: [{ date: '2026-10-08', label: 'Mode 3', outcome: 'kept' }, { date: '2026-10-16', label: '4 h window', outcome: 'kept' }] }] } } },
  ];
  const grid = slot('cards');
  for (const c of cards) grid.append(ui.card(c));
  // real data path: the first dataset in data/catalog.json, drawn with the type its meta.chart asks for
  ctx.data.catalog().then((cat) => {
    if (cat.length) grid.append(ui.card({ span: 12, id: cat[0].id }));
  }).catch(() => grid.append(ui.card({ span: 12, claim: 'data/catalog.json is not in this build yet', why: 'Cards by id light up once the DATA agent writes the catalog.' })));
  slot('next').append(ui.next('kit'));
}
