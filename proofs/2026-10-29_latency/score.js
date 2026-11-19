// Lab A/B scorer: node score.js <dir> <baseCfg> <cfg>...  (files <dir>/<cfg>_q<N>_<k>.json; k=0 is the warm-up, skipped)
// Per prompt: time, parse, severity/label vs the base config, and whether the whole answer text is identical.
const fs = require('fs'), path = require('path');
const [dir, ...cfgs] = process.argv.slice(2);
function load(dirs, name) {
  const o = {};
  for (const d of dirs) for (const f of fs.readdirSync(d)) {
    const m = f.match(new RegExp('^' + name + '_q(\\d+)_(\\d+)\\.json$'));
    if (!m || m[2] === '0') continue;
    for (const line of fs.readFileSync(path.join(d, f), 'utf8').split('\n')) {
      if (!line.includes('"outputs"')) continue;
      const x = JSON.parse(line), text = x.outputs[0].text;
      let j = null; try { j = JSON.parse(text.slice(text.indexOf('{"title"'))); } catch (e) { /* unparsed */ }
      o[m[1]] = { t: (x.total_ms || 0) / 1000, j, text, swap: x.swap_ms, prefill: x.prefill_ms };
    }
  }
  return o;
}
const dirs = dir.split(',');
const runs = cfgs.map((c) => [c, load(dirs, c)]);
const [bn, base] = runs[0];
for (const [name, r] of runs) {
  const qs = Object.keys(r).sort((a, b) => a - b);
  const mean = qs.reduce((s, q) => s + r[q].t, 0) / Math.max(1, qs.length);
  let parse = 0, same = 0, ident = 0;
  for (const q of qs) {
    const a = r[q], b = base[q];
    if (a.j) parse++;
    if (a.j && b && b.j && a.j.severity === b.j.severity && a.j.label === b.j.label) same++;
    if (b && a.text === b.text) ident++;
  }
  console.log(`${name}: n=${qs.length} parse=${parse} sev+label same as ${bn}=${same} identical text=${ident} mean ${mean.toFixed(1)} s  [${qs.map((q) => 'q' + q + ' ' + r[q].t.toFixed(1)).join(', ')}]`);
}
