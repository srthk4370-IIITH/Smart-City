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
  const reasonerFile = base(prof(live, 'reasoner_model')) || 'qwen35_reasoner_q4_0.gguf';
  let split = prof(live, 'reasoner_split') || d.split || '3';
  const spRes = sp.result || d.split_post_result;
  if (newLive && spRes) split = String(spRes).trim().split(/\s+/)[0];
  const md5Of = (file) => { const m = MODEL[file] || {}; return md5s[m.md5key || file] || null; };
  const lineMd5 = (needle) => { const l = bs.find((x) => x.includes(needle) && /^[0-9a-f]{32}\b/.test(x)); return l ? l.slice(0, 32) : null; };
  const rag = t.rag || {};
  const earlyK = prof(live, 'ai_early_k'), earlyShapes = prof(live, 'ai_early_shapes');
  let app = newLive ? FINAL_APP : KNOWN_GOOD_APP;
  if (rag.live && rag.apk) app = { apk: rag.apk, ea: rag.edge_agent, label: 'fast_early + retrieval preliminary build' };
  const ea = (rag.live && rag.edge_agent) || (newLive && lineMd5('edge-agent')) || (d.known_good_edge_agent && !newLive ? d.known_good_edge_agent : null);
  const ragState = ragStatus(rag);

  // ------------------------------------------------------------ banner
  const bn = $('banner');
  if (pending) {
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
    ['Reasoner', `${rm.name}: ${rm.what}`, md5Of(reasonerFile), reasonerWhy(d, pending, newLive, rm.name)],
    ['NPU daemon', 'htpd_v8x2 on llama.cpp 620d222 (our Hexagon patches); polling for NPU completions; reasoner leaves the NPU after 3 s idle', lineMd5('htpd_v8x2') || '22ec1278 (prefix)', 'The Hexagon SDK route gave no net gain.'],
    ['Split decoding', `${split} parallel field groups after the headline`, null, splitWhy(sp, spRes, split)],
    ['App', `${app.label}; APK ${app.apk}`, ea || app.ea, newLive ? 'Deployed tonight and checked through the app.' : pending ? 'Running before the final deploy.' : 'Restored by the automatic rollback.'],
    ['Preliminary report', ragState.live ? 'Rules + agents + retrieval of similar past incidents' : 'Rules + the agents\' findings, then replaced by the reasoner', null, ragState.note],
    ['Critical fast path', newLive ? 'On' : 'Off (not in this build)', null, newLive ? '2 readings past a critical limit open the incident at once.' : 'Built and tested; it comes with the fast_early app.'],
    ['Early provisional AI', earlyK ? `On at ${earlyK} readings for: ${earlyShapes}` : 'Off', null, earlyK ? 'Cleared by the gate study.' : 'Built, off by default until the gate study clears shapes.'],
  ];
  $('parts').append(table(h, ['Part', 'What runs', 'md5', 'Why'], rows.map((r) => [r[0], r[1], r[2] ? h('code', { text: r[2] }) : '—', r[3]])));
  $('parts-note').textContent = pending
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
  lat.append(h('div.span-12', null, ui.anchors(anchors.map((a) => ({ ...a, meta: tonight ? `tonight, ${ch.summary.n} scenarios through the app` : 'fast4 build, through the app' })).slice(0, 3).concat([{ ...anchors[3], meta: newLive ? 'fast path: second reading past the limit' : 'the event gate in the running build' }]))));
  lat.append(ui.card({ span: 6, claim: 'Where the NPU time goes (board)', body: table(h, ['Step', 'Time'], [
    ['Domain agents, 10 in one batch (warm)', '11.0 s'],
    ['Domain agents, 4 in one batch (warm)', '3.3 to 3.7 s'],
    ['Model swap to the reasoner', '3.3 to 4.0 s'],
    ['Reasoner prefill (fixed prefix cached)', '1.6 to 2.8 s'],
    ['Reasoner report, split-3, 30 held-out incidents', '22.5 s mean'],
  ]), why: 'Decoding is bound by memory bandwidth: about 60 ms per token for the 4B reasoner.', source: { files: ['proofs/2026-10-27_reasoner_fast/RESULTS.md'] } }));
  lat.append(ui.card({ span: 6, claim: 'Latency levers, kept and dropped', body: table(h, ['Lever', 'Effect', 'Kept?'], [
    ['Poll for NPU completions', '27.8 → 25.8 s', 'yes'],
    ['Split decoding (3 groups)', '25.7 → 23.7 s', 'yes'],
    ['Two-stage report', 'first report 1 to 7 s', 'yes'],
    ['Speculative decoding (MTP, n-gram)', '+1% to +20%', 'no'],
    ['Hexagon SDK upstream / 32x4 kernel', 'net ≈ 0', 'no'],
    ['4-bit output layer', '−4%, changed a label', 'no'],
    ['Pruned output layer', '≈ −12% (estimate)', 'held: board reboot'],
    ['Reasoner on the GPU', '≈ 19 to 20 s (estimate)', 'not built'],
  ]), source: { files: ['proofs/2026-10-27_reasoner_fast/RESULTS.md', 'proofs/2026-10-28_master/GPU_RESEARCH.md'] } }));

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
  if (t.fastcheck && t.fastcheck.summary) {
    const s = t.fastcheck.summary;
    tn.append(ui.card({ span: 6, claim: 'Critical breach: fast path, then AI on the same incident', body: table(h, ['Field', 'Value'], Object.entries(s).map(([k, v]) => [k.replace(/_/g, ' '), String(v)])), source: { files: [t.fastcheck.file] } }));
  } else tn.append(pendingCard(ui, h, 'Critical breach: fast path, then AI on the same incident', 'proofs/2026-10-27_reasoner_fast/raw/fastcheck_*.json', 6));
  tn.append(splitCard(ui, h, sp, spRes));
  tn.append(mdCard(ui, h, 'Retrieval preliminary report', rag, 12));
  tn.append(mdCard(ui, h, 'Gate study: can the agents read younger events?', t.gate_study || {}, 12, t.final && t.final.present ? 'Not run before the evaluation: the laptop GPU went back to the owner, so the gate study waits.' : null));
  tn.append(mdCard(ui, h, 'Reasoner round 2 (rsn_v2), laptop evaluation', t.rsn_v2_eval || {}, 12, t.final && t.final.present ? 'Not run on the laptop; rsn_v2 was judged by the board gate in the final deploy instead.' : null, true));
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
function reasonerWhy(d, pending, newLive, name) {
  if (name === 'rsn_v2' && d.reasoner_why) return 'rsn_v2 passed the board accuracy gate and the 92% severity-consistency gate.';
  if (d.reasoner_why && /accuracy FAIL/.test(d.reasoner_why)) return 'Kept: the second-round reasoner (rsn_v2) failed tonight\'s board accuracy gate.';
  if (d.reasoner_why) return short(String(d.reasoner_why).replace(/\s*\{.*$/, ''));
  return 'Deployed 27 Oct; a second round (rsn_v2) is gated on the board tonight.';
}
function splitWhy(sp, res, split) {
  if (res) return /fail/i.test(res) ? `Split ${res.match(/split (\d)/)?.[1] || ''} failed the app check; back to 3.` : `Set by the split-4/6 A/B after the deploy (split ${split}).`;
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
