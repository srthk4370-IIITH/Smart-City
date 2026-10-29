// Today: what runs on the board now, read from data/today.json (build/collect/today.py <- proofs/2026-10-28_master).
// Anything not yet written by the night's scripts shows as "pending"; nothing here is typed in by hand except the
// numbers that come from earlier, closed proof folders (each card names its source).
const MODEL = {
  'ft_B50_q4_0.gguf': { name: 'B50', what: 'Llama 3.2 3B domain agents (mixA50 + half of a LoRA top-up), Q4_0' },
  'ft_T30_q4_0.gguf': { name: 'T30', what: 'Llama 3.2 3B domain agents (P2 candidate), Q4_0' },
  'qwen35_reasoner_q4_0.gguf': { name: 'rsn_v1', what: 'Qwen3.5-4B cross-domain reasoner, QLoRA merged, Q4_0', md5key: 'rsn_v1_q4_0.gguf' },
  'rsn_v1_q4_0.gguf': { name: 'rsn_v1', what: 'Qwen3.5-4B cross-domain reasoner, QLoRA merged, Q4_0' },
  'rsn_v2_q4_0.gguf': { name: 'rsn_v2', what: 'Qwen3.5-4B cross-domain reasoner, round 2, Q4_0' },
};
const KNOWN_GOOD_APP = { apk: '9d066495', ea: '8e1ae828', label: 'fast4 build (two-stage report, split decoding)' };
const FINAL_APP = { apk: '0deb016e', ea: 'c97afdeb', label: 'fast_early build (adds the critical fast path)' };

export default async function mount(ctx) {
  const { root, ui, data, h } = ctx;
  const $ = (s) => root.querySelector(`[data-slot="${s}"]`);
  $('next').append(ui.next('today', 'route'));

  let t;
  try { t = await data.json('today.json'); } catch (e) {
    $('banner').append(h('p.td-pending', { text: 'The status file is not in this build.' }));
    return;
  }
  const d = t.decisions || {}, f = t.final || {}, sp = t.split_post || {}, md5s = t.models_md5 || {};
  const built = String((t.meta && t.meta.generated_at) || '').replace('T', ' ').slice(0, 16);
  $('asof').textContent = `Today · read from the proof files at ${built} IST`;

  // ------------------------------------------------------------ state
  const pending = !f.present;
  const rolledBack = !!f.rolled_back || (f.present && !f.passed);
  const newLive = f.present && f.passed;
  const prof = (lines, key) => { const l = (lines || []).find((x) => x.startsWith(key + '=')); return l ? l.slice(key.length + 1) : null; };
  const base = (p) => String(p || '').split('/').pop();
  const kg = d.known_good_profile || [];
  const bs = f.board_state || [];
  const live = newLive ? bs : kg; // the profile that runs now
  const agentsFile = base(prof(live, 'model')) || (newLive ? d.agents : 'ft_B50_q4_0.gguf');
  const retry0 = t.rsn_v2_retry || {};
  // the retry deployed htpd_v8x3 with rsn_v1 kept: 'live' means the htpd fix is live, rsn_v2 only if the result names it alone
  const retry = { ...retry0, live: !!retry0.live && !/rsn_v1/.test(retry0.result || '') };
  const reasonerFile = retry.live ? 'rsn_v2_q4_0.gguf' : (base(prof(live, 'reasoner_model')) || 'qwen35_reasoner_q4_0.gguf');
  const binName = (t.morning && t.morning.live && t.morning.live.bin) || (retry0.live && retry0.bin) || base(prof(live, 'bin')) || 'htpd_v8x2';
  let split = prof(live, 'reasoner_split') || d.split || '3';
  const spRes = sp.result || d.split_post_result;
  if (newLive && spRes) split = String(spRes).trim().split(/\s+/)[0];
  const md5Of = (file) => { const m = MODEL[file] || {}; return md5s[m.md5key || file] || null; };
  const lineMd5 = (needle) => { const l = bs.find((x) => x.includes(needle) && /^[0-9a-f]{32}\b/.test(x)); return l ? l.slice(0, 32) : null; };
  const rag = t.rag || {};
  const earlyK = prof(live, 'ai_early_k'), earlyShapes = prof(live, 'ai_early_shapes');
  let app = newLive ? FINAL_APP : KNOWN_GOOD_APP;
  if (rag.live && rag.apk) app = { apk: rag.apk, ea: rag.edge_agent, label: 'fast_early + retrieval preliminary build' };
  const mlive = t.morning && t.morning.live;
  if (mlive) app = { apk: mlive.apk, ea: mlive.edge_agent, label: 'latest build (Campus Assistant chat, contract repairs, preliminary checklist, retrieval seeds)' };
  const ea = (mlive && mlive.edge_agent_md5) || (rag.live && rag.edge_agent) || (newLive && lineMd5('edge-agent')) || (d.known_good_edge_agent && !newLive ? d.known_good_edge_agent : null);
  const ragState = ragStatus(rag);
  const mo = t.morning || {}, ml = mo.live || null; // evaluation-morning deploy (improve*/STATUS.md), newest wins

  // ------------------------------------------------------------ banner
  const bn = $('banner');
  if (ml) {
    bn.classList.add('is-pass');
    const fc = ml.fastcheck || {};
    bn.append(h('span.label', { text: `Live now: edge-agent ${ml.edge_agent} · deployed ${String(ml.updated || '').replace('T', ' ').slice(5, 16)} IST` }),
      h('p', { text: `Domain agents B50, reasoner rsn_v1, ${ml.bin}, split ${ml.split}, retrieval library of 254 reference reports, and the Campus Assistant chat app. Checked through the app after the deploy: 2 chaos scenarios passed; a critical breach opened its incident by the fast path in ${fc.fast_s ?? '—'} s and the AI report landed on the same incident at ${fc.ai_update_s ?? '—'} s. Everything runs on the board, offline.` }));
  } else if (pending) {
    bn.classList.add('is-pending');
    bn.append(h('span.label', { text: 'Final deploy: in progress' }),
      h('p', { text: findStep(t, /F5 deployed/)
        ? 'The new build is deployed and is being checked through the app; if a check fails, the script restores the known-good build listed below. This page is rebuilt when the final status exists.'
        : 'The night\'s deploy script has not written its final status yet. The board shows the last known-good build, listed below; this page is rebuilt when the final status exists.' }));
  } else if (newLive) {
    bn.classList.add('is-pass');
    bn.append(h('span.label', { text: `Final deploy: passed · ${fmtZ(f.written)}` }), h('p', { text: short(f.result) }));
  } else {
    bn.classList.add('is-rollback');
    bn.append(h('span.label', { text: `Final deploy: rolled back · ${fmtZ(f.written)}` }),
      h('p', { text: 'The new build failed its check through the app, so the script restored the known-good build. What runs is the known-good build below. ' + short(f.result) }));
  }

  // ------------------------------------------------------------ parts table
  const am = MODEL[agentsFile] || { name: agentsFile, what: '' }, rm = MODEL[reasonerFile] || { name: reasonerFile, what: '' };
  const rows = [
    ['Domain agents', `${am.name}: ${am.what}`, md5Of(agentsFile), d.agents_why ? plainWhy(d.agents_why) : 'Accuracy first: the newer candidate lost head to head.'],
    ['Reasoner', `${rm.name}: ${rm.what}`, md5Of(reasonerFile), reasonerWhy(d, pending, newLive, rm.name, retry)],
    ['NPU daemon', `${binName} on llama.cpp 620d222 (our Hexagon patches); polling for NPU completions; reasoner leaves the NPU after 3 s idle`, lineMd5(binName) || (binName === 'htpd_v8x2' ? '22ec1278 (prefix)' : null), binName === 'htpd_v8x2' ? 'The Hexagon SDK route gave no net gain.' : '150 s wall-clock guard per report, bounded token picking, heartbeat stall log; overnight watchdog: 0 stalls.'],
    ['Split decoding', `${ml ? ml.split : split} parallel field groups after the headline`, null, splitWhy(sp, spRes, split) + (mo.split3r ? ` Split 3r (fork after the label) gave no gain this morning: ${mo.split3r.split3_s} vs ${mo.split3r.split3r_s} s.` : '')],
    ['Contract repairs', "Post-checks on the reasoner's answer: normal + needs_more_data becomes label unknown; a title location not in the input is replaced by one from the input", null, 'Replay on 386 board answers: label 83.2% → 87.6%, 0 new errors.'],
    ['App', `${app.label}; APK ${app.apk}`, ea || app.ea, ml ? 'Deployed this morning and checked through the app (chaos + fast-path check).' : newLive ? 'Deployed tonight and checked through the app.' : pending ? 'Running before the final deploy.' : 'Restored by the automatic rollback.'],
    ['Preliminary report', ragState.live ? 'Rules from the live values, worded like the most similar past report (254 seed reports + every live AI report); the checklist starts here' : 'Rules + the agents\' findings, then replaced by the reasoner', null, ragState.live ? 'Severity = the higher of rules and the retrieved report, so it never under-alerts; numbers never come from old reports.' : ragState.note],
    ['Critical fast path', newLive ? 'On' : 'Off (not in this build)', null, newLive ? '2 readings past a critical limit open the incident at once.' : 'Built and tested; it comes with the fast_early app.'],
    ['Early provisional AI', earlyK ? `On at ${earlyK} readings for: ${earlyShapes}` : 'Off', null, earlyK ? 'Cleared by the gate study.' : 'Built, off by default until the gate study clears shapes.'],
  ];
  $('parts').append(table(h, ['Part', 'What runs', 'md5', 'Why'], rows.map((r) => [r[0], r[1], r[2] ? h('code', { text: r[2] }) : '—', r[3]])));
  $('parts-note').textContent = ml
    ? `The edge-agent md5 is from the board after this morning's deploy (${ml.file}); model md5 values are the staged files pushed to the board.`
    : pending
    ? 'md5 values are the staged files pushed to the board; the board-side check is in the final status once written.'
    : 'Board md5 values are from the board after the run (FINAL_STATUS.md); model md5 values are the staged files pushed to the board.';
  if (!newLive) root.querySelectorAll('[data-fast]').forEach((li) => li.append(h('span.muted', { text: ' (in the final build only)' })));

  // ------------------------------------------------------------ latency
  const ch = t.chaos_tonight;
  const lat = $('latency');
  const rng = (a, u = ' s') => (a ? (a[0] === a[1] ? `${a[0]}${u}` : `${a[0]} to ${a[1]}${u}`) : null);
  const tonight = ch && ch.summary && ch.summary.n;
  const anchors = [
    { value: tonight && ch.summary.prelim_range ? rng(ch.summary.prelim_range) : '1 to 7 s', label: 'Event to preliminary report on screen.' },
    { value: tonight && ch.summary.title_range ? rng(ch.summary.title_range) : '9 to 17 s', label: 'Event to the reasoner\'s title and severity.' },
    { value: tonight && ch.summary.done_min ? rng([ch.summary.done_min, ch.summary.done_max]) : '28 to 39 s', label: 'Event to the full report.' },
    newLive ? { before: '40 to 55 min', after: '≈ 5 to 10 min', label: 'Real sensor time from a critical breach to the incident (one reading per 5 min).', ours: true } : { value: '40 to 55 min', label: 'Real sensor time from an event to the AI (8 readings, one per 5 min).', ours: false },
  ];
  if (rag.live && rag.prelim_max_s != null) anchors[0] = { value: `${rag.prelim_max_s} s`, label: 'Event to preliminary report on screen (retrieval build).', meta: `${rag.n_incidents || ''} incidents through the app, retrieval build` };
  const fcx = (ml && ml.fastcheck && ml.fastcheck.fast_s != null) ? ml.fastcheck : (f.fastcheck && f.fastcheck.fast_s != null) ? f.fastcheck : null;
  lat.append(h('div.span-12', null, ui.anchors(anchors.map((a) => ({ ...a, meta: a.meta || (tonight ? `overnight final deploy, ${ch.summary.n} scenarios through the app` : 'fast4 build, through the app') })).slice(0, 3).concat([{ ...anchors[3], meta: newLive ? (fcx ? `fast path: incident ${fcx.fast_s} s after the breach in the app (demo clock), AI update ${fcx.ai_update_s} s` : 'fast path: second reading past the limit') : 'the event gate in the running build' }]))));
  lat.append(ui.card({ span: 6, claim: 'Where the NPU time goes (board)', body: table(h, ['Step', 'Time'], [
    ['Domain agents, 10 in one batch (warm)', '11.0 s'],
    ['Domain agents, 4 in one batch (warm)', '3.3 to 3.7 s'],
    ['Model swap to the reasoner', '3.3 to 4.0 s'],
    ['Reasoner prefill (fixed prefix cached)', '1.6 to 2.8 s'],
    ['Reasoner report, split-3, 30 held-out incidents', '22.5 s mean'],
    ['Reasoner report, split-3, 10 incidents (29 Oct A/B)', mo.split3r ? `${mo.split3r.split3_s} s mean` : '—'],
    ['Reasoner ladder: base → polling → split decoding', '27.8 → 25.8 → 21.6 s'],
  ]), why: 'Decoding is bound by memory bandwidth: about 60 ms per token for the 4B reasoner.', source: { files: ['proofs/2026-10-27_reasoner_fast/RESULTS.md'] } }));
  lat.append(ui.card({ span: 6, claim: 'Latency levers, kept and dropped', body: table(h, ['Lever', 'Effect', 'Kept?'], [
    ['Poll for NPU completions', '27.8 → 25.8 s', 'yes'],
    ['Split decoding (3 groups)', '25.7 → 23.7 s', 'yes'],
    ['Two-stage report', 'first report 1 to 7 s', 'yes'],
    ['Speculative decoding (MTP, n-gram)', '+1% to +20%', 'no'],
    ['Hexagon SDK upstream / 32x4 kernel', 'net ≈ 0', 'no'],
    ['4-bit output layer', '−4%, changed a label', 'no'],
    ['Pruned output layer', '≈ −12% (estimate)', 'held: board reboot'],
    ['Split 4 / split 6', '+1% / does not fit the NPU session', 'no'],
    ['Split 3r (fork after the label)', mo.split3r ? `${mo.split3r.split3_s} → ${mo.split3r.split3r_s} s` : '22.2 → 22.2 s', 'no'],
    ['Reasoner on the GPU (measured 29 Oct)', '≈ 2.5x slower than the NPU', 'no'],
  ]), source: { files: ['proofs/2026-10-27_reasoner_fast/RESULTS.md', 'proofs/2026-10-28_master/gpu_bench_out/out.md', 'proofs/2026-10-28_master/split3r/result.txt'] } }));

  // ------------------------------------------------------------ accuracy
  const acc = $('accuracy');
  const f1 = findStep(t, /F1 split pick/);
  const sp3 = f1 && f1.match(/\|\s*sp3\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|/);
  const v2acc = findStep(t, /F3 rsn_v2 (board accuracy|accuracy gate)/g, true);
  const v2cons = findStep(t, /F3 rsn_v2 board consistency/);
  const rsnRows = [
    ['rsn_v1, laptop, 150 held-out incidents', 'severity 91.9%, root-cause label 87.8%, valid output 98.7%'],
    sp3 ? ['rsn_v1, board, 30 held-out incidents (split-3, tonight)', `severity ${sp3[3]}/${sp3[1]}, label ${sp3[4]}/${sp3[1]}, all ${sp3[2]} parse`] : null,
    ['Same prompt 5 times on the board (6 prompts)', 'severity agrees 97%; 100% with the light guard'],
    ['Contract repairs, replay on 386 board answers (29 Oct)', 'label 83.2% → 87.6%, 0 new errors'],
    ['rsn_v1 vs rsn_v2, same 106 held-out incidents (29 Oct)', 'severity 94.7% vs 87.6%: rsn_v1 kept'],
    ['Chat, 100 dev questions (laptop)', 'answered 100%, first tool right 100%, numbers exact 90%, ungrounded 0%'],
    ['Campus Assistant on the board, 3 questions (29 Oct)', '9 to 14 s per answer; refused "close them all"'],
    ...v2acc.filter((l) => /accuracy gate/.test(l)).map((l) => ['rsn_v2, board accuracy gate (tonight)', gateLine(l)]),
    v2cons ? ['rsn_v2, board consistency (tonight)', stripTs(v2cons).replace(/^F3 rsn_v2 board consistency: /, '')] : null,
  ].filter(Boolean);
  acc.append(ui.card({ span: 6, claim: `Reasoner (${rm.name} runs)`, body: table(h, ['Test', 'Result'], rsnRows), why: 'Gold = held-out answers the model never saw. Severity is what the operator acts on, so it is the gate.', source: { files: ['proofs/2026-10-25_reasoner_final/eval/results/summary_v3.json', 'proofs/2026-10-27_reasoner_fast/RESULTS.md'] } }));
  acc.append(ui.card({ span: 6, claim: `Domain agents (${am.name} runs)`, body: table(h, ['Test', 'Result'], [
    ['mixA50 (B50\'s parent), 400 test rows on the board', 'pattern 87.7%, status 86.5%, valid JSON 100%'],
    ['Post-rules, status, 1,148 test rows', '81.5% → 86.4%'],
    ['Post-rules, status, 318 real-world rows', '60.4% → 85.2%'],
    ['B50 vs mixA50, paired (wins − losses)', 'overall +1, severity-weighted +61, story suite +4'],
    ['T30 vs B50, paired (tonight\'s candidate)', 'overall +7 (CI −19 to +35), severity −13: B50 kept'],
    ['Through the app, 6 scenarios', ch && ch.summary ? `${ch.summary.done_valid}/${ch.summary.n} done and valid (tonight)` : '6/6 done and valid (27 Oct)'],
  ]), why: 'The host copy of the board model matches the board on 207 of 208 rows, so host tests stand in for the board.', source: { files: ['proofs/2026-10-24_v2t3g', 'proofs/2026-10-24_trackB/RESULTS.md', 'proofs/2026-10-25_domain_plan/PLAN.md'] } }));

  // ------------------------------------------------------------ this morning
  morningCards(ui, h, $('morning'), mo);

  // ------------------------------------------------------------ tonight
  const tn = $('tonight');
  const steps = ((t.final_log || {}).steps || []).filter((l) => /\bF\d|ROLLBACK|rollback/.test(l));
  tn.append(ui.card({ span: 12, claim: pending ? 'Final deploy: steps so far' : 'Final deploy: steps', body: steps.length
    ? h('ol.td-steps', null, steps.map((l) => h('li', null, h('span.label', { text: fmtZ(l.slice(0, 20)) }), h('span', { text: stripTs(l) }))))
    : h('p.td-pending', { text: 'pending' }), source: { files: [(t.final_log || {}).file || 'proofs/2026-10-28_master/final.log', 'proofs/2026-10-28_master/FINAL_STATUS.md'] } }));
  if (ch && ch.rows && ch.rows.length) {
    tn.append(ui.card({ span: 12, claim: 'Through the app: scenarios after the deploy', body: table(h, ['Scenario', 'Preliminary', 'Title', 'Full report', 'Reasoner', 'NPU calls', 'Severity', 'Valid'],
      ch.rows.map((r) => [String(r.scenario || '').replace(/_/g, ' '), sec(r.prelim_s), sec(r.title_s), sec(r.done_s), sec(r.reasoner_s), r.npu_calls ?? '—', r.severity || r.state || '—', r.valid ? 'yes' : 'no'])),
      why: 'Times count from the moment the event passes the gate on the board.', source: { files: [ch.dir] } }));
  } else tn.append(pendingCard(ui, h, 'Through the app: scenarios after the deploy', 'proofs/2026-10-28_master/final/chaos'));
  if (f.fastcheck) {
    const s = f.fastcheck;
    tn.append(ui.card({ span: 6, claim: 'Critical breach: fast path, then AI on the same incident', body: table(h, ['Check', 'Result'], [
      ['Fast-path incident opened', `${s.fast_s} s after the breach reading`], ['AI report on the same incident', `${s.ai_update_s} s`],
      ['Final report by', String(s.final_model || '—')], ['Severity', String(s.severity || '—')], ['Valid / pass', `${s.valid ? 'yes' : 'no'} / ${s.pass ? 'yes' : 'no'}`]]),
      why: 'Demo clock: one reading every 2 s. In the field a reading comes every 5 min.', source: { files: ['proofs/2026-10-28_master/FINAL_STATUS.md'] } }));
  } else if (t.fastcheck && t.fastcheck.summary) {
    const s = t.fastcheck.summary;
    tn.append(ui.card({ span: 6, claim: 'Critical breach: fast path, then AI on the same incident', body: table(h, ['Field', 'Value'], Object.entries(s).map(([k, v]) => [k.replace(/_/g, ' '), String(v)])), source: { files: [t.fastcheck.file] } }));
  } else tn.append(pendingCard(ui, h, 'Critical breach: fast path, then AI on the same incident', 'proofs/2026-10-27_reasoner_fast/raw/fastcheck_*.json', 6));
  tn.append(splitCard(ui, h, sp, spRes));
  tn.append(mdCard(ui, h, 'Retrieval preliminary report', rag, 12));
  tn.append(mdCard(ui, h, 'Reasoner rsn_v2 retry (htpd fix, board gates)', retry, 12, t.final && t.final.present ? null : null));
  tn.append(mdCard(ui, h, 'Overnight jobs (last snapshot)', t.overnight || {}, 12));
  tn.append(mdCard(ui, h, 'Gate study: can the agents read younger events?', t.gate_study || {}, 12, t.final && t.final.present ? 'Not run before the evaluation: the laptop GPU went back to the owner, so the gate study waits.' : null));
  tn.append(mdCard(ui, h, 'Reasoner round 2 (rsn_v2), laptop evaluation', t.rsn_v2_eval || {}, 12, t.final && t.final.present ? 'Not run on the laptop; rsn_v2 was judged by the board gate in the final deploy instead.' : null, true));
}

// ---------------------------------------------------------------- this morning (29 Oct)
// Deploy rows, split-3r and GPU numbers are read from the proof files; the texts quote proofs/2026-10-28_master/FACTS_2026-10-29.md
// and HANDBOOK 2.59 (closed results, no file to parse).
const FACTS = 'proofs/2026-10-28_master/FACTS_2026-10-29.md';
function bullets(h, items) { return h('ul.td-mdlist', null, items.map((x) => h('li', { text: x }))); }
function morningCards(ui, h, el, mo) {
  const deps = (mo && mo.deploys) || [];
  if (deps.length) {
    // improve4: the deploy script's readiness check failed falsely (htpd.log rotated); the board went back to the chat build, healthy
    const ok = (d) => d.failed ? (d.name === 'improve4' ? 'not kept: deploy-script false failure (log rotation), board back on the chat build; retried' : 'failed, rolled back') : d.deployed ? (d.fastcheck && d.fastcheck.pass ? 'pass' : 'deployed') : 'in progress';
    el.append(ui.card({ span: 12, claim: `${deps.length} deploys this morning, each checked through the app`, body: table(h, ['Build', 'APK', 'edge-agent', 'Fast path', 'AI report, same incident', 'Check'],
      deps.map((d) => [String(d.heading || '').replace(/\s*\(.*\)$/, ''), d.apk ? h('code', { text: d.apk }) : '—', d.deployed ? h('code', { text: d.deployed }) : '—',
        d.fastcheck ? `${d.fastcheck.fast_s} s` : '—', d.fastcheck ? `${d.fastcheck.ai_update_s} s` : '—', ok(d)])),
      why: `Every deploy runs 2 chaos scenarios and a critical-breach check through the real app; the previous build stays ready to roll back. Live now: edge-agent ${mo.live ? mo.live.edge_agent : '—'} with the Campus Assistant.`, source: { files: deps.map((d) => d.file) } }));
  } else el.append(pendingCard(ui, h, 'Deploys this morning', 'proofs/2026-10-28_master/improve2/STATUS.md', 12, 'not in this build'));
  el.append(ui.card({ span: 6, claim: 'Contract repairs: label 83.2% → 87.6%', body: bullets(h, [
    'A severity of normal with needs_more_data now gets the label unknown (the gold rule holds on 151 of 151 cases).',
    'A title location that is not in the input is replaced by one from the input (holds on 5,761 of 5,761 gold cases).',
    'Replayed on 386 real board answers: root-cause label 83.2% → 87.6%, 0 new errors.']),
    why: 'Cheap, rule-based fixes after the model; no retraining.', source: { files: [FACTS, 'HANDBOOK.md §2.59'] } }));
  el.append(ui.card({ span: 6, claim: 'Checklist from the preliminary report, merged with the AI', body: bullets(h, [
    'The checklist is built from the preliminary report, so the operator can acknowledge, tick and add steps while the AI writes.',
    'When the AI report arrives: ticked steps it repeats stay done, open steps it drops are withdrawn, new ones are marked "New since you acknowledged".',
    'Close, dismiss and approve-all wait for the AI report.']),
    why: 'The operator can start work in the first second instead of waiting for the AI report.', source: { files: [FACTS, 'HANDBOOK.md §2.59'] } }));
  el.append(ui.card({ span: 6, claim: 'rsn_v2 rejected on evidence; rsn_v1 stays', body: h('div', null,
    table(h, ['Same 106 held-out incidents', 'rsn_v1', 'rsn_v2'], [
      ['Severity', '94.7%', '87.6%'], ['Root-cause label', '88.4%', '85.6%'], ['Checklist recall', '0.90', '0.81'], ['Overall score (v3)', '0.938', '0.913']]),
    h('p.muted', { text: 'On the board (prompts q10 to q19) rsn_v2 also invented a title location (q19) and misread 324 > 300 ppm (q11).' })),
    why: 'Severity is what the operator acts on, so a 7-point severity drop rules it out.', source: { files: [FACTS, 'proofs/2026-10-28_master/improve/STATUS.md'] } }));
  const g = mo && mo.gpu;
  const pick = g ? g.rows.filter((r) => /^(pp1|pp3|tg64)$/.test(r[0])) : [];
  const nm = { pp1: 'pp1 (1 token at a time)', pp3: 'pp3 (3 tokens at once, like split 3)', tg64: 'tg64 (writing 64 tokens)' };
  el.append(ui.card({ span: 6, claim: 'GPU measured: about 2.5x slower than the NPU', body: g && pick.length
    ? table(h, ['Test (rsn_v1, Q4_0)', 'Tokens/s on the GPU'], pick.map((r) => [nm[r[0]] || r[0], r[1]]))
    : h('p.td-pending', { text: 'not in this build' }),
    why: 'Adreno 750, upstream llama.cpp OpenCL, GPU alone. Not a latency path; it may still help bursts (agents on the GPU while the NPU reasoner writes).', source: { files: [g ? g.file : 'proofs/2026-10-28_master/gpu_bench_out/out.md'] } }));
  const s3 = mo && mo.split3r;
  el.append(ui.card({ span: 6, claim: 'Split 3r (fork after the label): no gain', body: s3
    ? table(h, ['Variant', `Mean reasoner time, ${s3.n} incidents`], [['Split 3 (live)', `${s3.split3_s} s`], ['Split 3r', `${s3.split3r_s} s (${s3.delta})`]])
    : h('p.td-pending', { text: 'not in this build' }),
    why: 'Its first group became the longest stream, so nothing was saved. Split 3 stays; group rebalancing is exhausted.', source: { files: [s3 ? s3.file : 'proofs/2026-10-28_master/split3r/result.txt'] } }));
  el.append(ui.card({ span: 6, claim: 'Two-stage report with retrieval: live', body: bullets(h, [
    'Hybrid retrieval, no new model: a structured vector (role, metric, pattern, status, values) weighted 0.7 plus TF-IDF over the report text 0.3, same role and metric only.',
    'Preliminary = a rules report from the live values in the wording of the best match; severity = the higher of the two, so it never under-alerts.',
    'Label on screen: "Preliminary - based on N similar past incidents (best match X%, INC-...) - full AI report coming"; with no match, "Preliminary from the rules - full AI report coming".',
    'Library: every live AI report plus 254 seed reports written by rsn_v1 on the training split (320 generated, 254 passed the gate), ranked 3% below live reports.',
    'Deploy check: 4 of 4 incidents had the preliminary at 0 s and the AI report replaced it on the same incident; 2 of 4 used a retrieved match, the others the rules.',
    'After the AI report, it is compared with similar past incidents and any disagreement is logged.']),
    source: { files: ['proofs/2026-10-28_master/RAG_STATUS.md', FACTS] } }));
  const cc = (mo && mo.chat_checks) || [];
  el.append(ui.card({ span: 12, claim: 'Campus Assistant (conversational interface): live', body: h('div', null,
    bullets(h, [
      'A second app on the same backend: its own launcher icon "Campus Assistant", and the "✦ Ask AI" button in the dashboard.',
      'Model: rsn_v1 in the chat mode it was trained in (about 2,000 chat tool traces), with the exact trained prompt, through htpd on the NPU.',
      '9 read-only tools: count, find and get incidents, sensor faults, sensor history, list sensors, domain health, action history, documents. Up to 5 lookups per answer.',
      '"How I found this" shows every tool call behind an answer. Chat history is kept on the board.',
      'Alerts first: a question asked during an incident analysis is queued and answered automatically.',
      'It cannot act: asked to "close them all", it refused (its tools are read-only; an operator closes incidents after review).',
      'Known weak spot: "which are still open?" reused the plain count, because the tools have no open-only filter yet.',
      'Host chat dev set, 100 questions: answered 100%, first tool right 100%, numbers exact 90%, ungrounded 0%.']),
    cc.length ? table(h, ['Board check (question)', 'Time', 'Tools used'], cc.map((c) => [c.question, `${c.s} s`, c.tools.length ? c.tools.join(', ') : 'none'])) : null),
    why: 'Next: streaming, chat about the open incident, the 100-question chat set on the board, an open-only filter and maintenance tools.',
    source: { files: [mo && mo.chat_file ? mo.chat_file : 'proofs/2026-10-28_master/improve3/STATUS.md', 'HANDBOOK.md §2.60', FACTS] } }));
}

// ---------------------------------------------------------------- helpers
function table(h, head, rows) {
  return h('div.ptable', null, h('table', null,
    h('thead', null, h('tr', null, head.map((c) => h('th', { text: c })))),
    h('tbody', null, rows.map((r) => h('tr', null, r.map((c) => h('td', null, c == null ? '—' : c)))))));
}
function sec(v) { return v == null ? '—' : `${v} s`; }
function short(s) { return String(s || '').split(/:\s*\{/)[0].replace(/`/g, '').trim(); }
function stripTs(l) { return String(l).replace(/^\S+Z\s+/, ''); }
function fmtZ(z) {
  const m = String(z || '').match(/(\d{4}-\d\d-\d\d)T(\d\d):(\d\d)/);
  if (!m) return String(z || '');
  const dt = new Date(`${m[1]}T${m[2]}:${m[3]}:00Z`);
  dt.setUTCMinutes(dt.getUTCMinutes() + 330);
  return `${dt.toISOString().slice(5, 10)} ${dt.toISOString().slice(11, 16)} IST`;
}
function findStep(t, re, all) {
  const s = ((t.final_log || {}).steps || []);
  if (all) return s.filter((l) => l.match(new RegExp(re.source)));
  return s.slice().reverse().find((l) => re.test(l)) || null;
}
function gateLine(l) {
  const m = stripTs(l).match(/gate:\s*(PASS|FAIL)\s*(\{[^}]*\})?\s*(\{[^}]*\})?/);
  if (!m) return stripTs(l);
  const num = (o, k) => { const r = (o || '').match(new RegExp(`'${k}':\\s*([0-9.]+)`)); return r ? r[1] : '?'; };
  const v2 = m[3] || '';
  return `${m[1]}: ${num(v2, 'n')} of 30 prompts answered, ${num(v2, 'parse')} parsed, severity right on ${num(v2, 'sev')} (rsn_v1: ${num(m[2], 'sev')}/30). rsn_v1 stays.`;
}
function plainWhy(s) {
  if (/T30 fails/.test(s)) return 'The newer candidate (T30) lost head to head against B50; accuracy first.';
  return String(s).replace(/\s*\(.*?\)/g, '').replace(/;.*$/, '').replace(/gate2/g, 'the paired test').replace(/, owner rule accuracy first/, '; accuracy first') + '.';
}
function reasonerWhy(d, pending, newLive, name, retry) {
  if (retry && retry.md && !retry.live) return 'rsn_v1 kept: rsn_v2 lost on the same 106 held-out incidents (severity 94.7% vs 87.6%) and made errors on the board (see This morning).';
  if (retry && retry.md) return retry.live ? "rsn_v2 passed the retry gates on the board (see Tonight's run)." : 'rsn_v1 kept: ' + short(retry.result || 'rsn_v2 retry did not pass');
  if (name === 'rsn_v2' && d.reasoner_why) return 'rsn_v2 passed the board accuracy gate and the 92% severity-consistency gate.';
  if (d.reasoner_why && /accuracy FAIL/.test(d.reasoner_why)) return 'Kept: the second-round reasoner (rsn_v2) failed tonight\'s board accuracy gate.';
  if (d.reasoner_why) return short(String(d.reasoner_why).replace(/\s*\{.*$/, ''));
  return 'Deployed 27 Oct; a second round (rsn_v2) is gated on the board tonight.';
}
function splitWhy(sp, res, split) {
  if (res) return /fail/i.test(res) ? "Split 3 stays: the split-4/6 A/B after the deploy did not switch (see Tonight's run)." : `Set by the split-4/6 A/B after the deploy (split ${split}).`;
  if (sp.done) return 'The split-4/6 A/B after the deploy kept 3.';
  return 'Split-3 adopted 28 Oct; a split-4/6 A/B runs after the final deploy.';
}
function ragStatus(rag) {
  if (!rag || !rag.md) return { live: false, note: 'Retrieval of similar past incidents is built and waits for its deploy window.' };
  return { live: !!rag.live, note: rag.live ? "Retrieval preliminary deployed and checked through the app (see Tonight's run)." : `Retrieval preliminary not live: ${short(rag.result || "see Tonight's run")}` };
}
function pendingCard(ui, h, claim, file, span = 12, msg) {
  return ui.card({ span, claim, body: h('p.td-pending', { text: msg || 'pending: the file is written later tonight' }), source: { files: [file] } });
}
function splitCard(ui, h, sp, res) {
  if (!sp.present || !(sp.steps || []).length) return pendingCard(ui, h, 'Split-4/6 A/B after the deploy', 'proofs/2026-10-28_master/split_post.log', 6);
  const body = h('div');
  if (sp.acc_table && sp.acc_table.length > 1) body.append(table(h, sp.acc_table[0], sp.acc_table.slice(1)));
  body.append(h('ol.td-steps', null, sp.steps.slice(-6).map((l) => h('li', null, h('span.label', { text: fmtZ(l.slice(0, 20)) }), h('span', { text: stripTs(l) })))));
  if (res) body.append(h('p', { text: `Result: split ${res}` }));
  return ui.card({ span: 6, claim: 'Split-4/6 A/B after the deploy', body, source: { files: [sp.file] } });
}
function mdCard(ui, h, claim, o, span, missing, pre) {
  if (!o || !o.present || !o.md) return pendingCard(ui, h, claim, (o && o.file) || '', span, missing);
  const body = pre ? h('pre.td-pre', { text: o.md }) : renderMd(h, o.md);
  return ui.card({ span, claim, body: h('div.td-md', null, body), source: { files: [o.file] } });
}

/** Minimal Markdown: headings, tables, lists, code fences, **bold**, `code`. Text only (no HTML passes through). */
function renderMd(h, md) {
  const root = h('div');
  const inline = (s) => {
    const el = h('span');
    String(s).split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach((p) => {
      if (/^\*\*[^*]+\*\*$/.test(p)) el.append(h('b', { text: p.slice(2, -2) }));
      else if (/^`[^`]+`$/.test(p)) el.append(h('code', { text: p.slice(1, -1) }));
      else if (p) el.append(document.createTextNode(p));
    });
    return el;
  };
  const lines = String(md).split(/\r?\n/);
  let i = 0, list = null;
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      root.append(h('pre.td-pre', { text: buf.join('\n') })); i++; list = null; continue;
    }
    if (/^\s*\|.*\|\s*$/.test(l)) {
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        const c = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((x) => x.trim());
        if (!c.every((x) => /^:?-{2,}:?$/.test(x) || x === '')) rows.push(c);
        i++;
      }
      if (rows.length) root.append(table(h, rows[0], rows.slice(1).map((r) => r.map(inline))));
      list = null; continue;
    }
    const hm = l.match(/^(#{1,4})\s+(.*)/);
    if (hm) { root.append(h(hm[1].length <= 2 ? 'h3.td-h' : 'h4.td-h', null, inline(hm[2]))); list = null; i++; continue; }
    const lm = l.match(/^(\s*)([-*]|\d+\.)\s+(.*)/);
    if (lm) {
      if (!list) { list = h(/\d/.test(lm[2]) ? 'ol.td-mdlist' : 'ul.td-mdlist'); root.append(list); }
      list.append(h('li', { style: lm[1].length >= 2 ? 'margin-left:1.2em' : null }, inline(lm[3]))); i++; continue;
    }
    if (l.trim()) root.append(h('p', null, inline(l)));
    list = null; i++;
  }
  return root;
}
