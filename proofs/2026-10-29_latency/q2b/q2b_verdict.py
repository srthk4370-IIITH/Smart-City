#!/usr/bin/env python3
# q2b verdict: python3 -I q2b_verdict.py <window dir> <out VERDICT.md> <extra md lines file>
# Speed + execution correctness only (2B is the BASE model: accuracy is not measured).
import json, os, re, sys, statistics as S

D, OUT, EXTRA = sys.argv[1], sys.argv[2], sys.argv[3]
STEP = re.compile(r'reason step profile: (\d+) steps, rows ([\d.]+)/step.*?decode ([\d.]+)')
LOAD = re.compile(r'reasoner load phases: (.*)')
ERR = re.compile(r'error|fail|abort|assert|segv|signal|fatal|panic|nan', re.I)


def reqs(cfg):
    out = []
    for f in sorted(os.listdir(D)):
        m = re.match(r'^%s_q(\d+)_(\d+)\.json$' % re.escape(cfg), f)
        if not m:
            continue
        r = dict(q=int(m.group(1)), k=int(m.group(2)), file=f, ok=False)
        try:
            raw = open(os.path.join(D, f), encoding='utf-8', errors='replace').read()
        except OSError:
            raw = ''
        r['bytes'] = len(raw)
        for line in raw.splitlines():
            if '"outputs"' not in line:
                continue
            try:
                x = json.loads(line)
            except ValueError:
                r['err'] = 'response line is not JSON'
                continue
            o = x['outputs'][0]
            text = o.get('text', '')
            r.update(ok=True, total=x.get('total_ms', 0), prefill=x.get('prefill_ms', 0), ttft=o.get('ttft_ms', 0),
                     tokens=sum((y.get('tokens') or 0) for y in x['outputs']), forced=sum((y.get('forced') or 0) for y in x['outputs']),
                     stop='/'.join(str(y.get('stop')) for y in x['outputs']), text=text, load=(x.get('reason') or {}).get('load_ms'))
            j = None
            i = text.find('{"title"')
            if i < 0:
                i = text.find('{')
            try:
                j = json.loads(text[i:]) if i >= 0 else None
            except ValueError:
                j = None
            r['parse'] = isinstance(j, dict)
            r['keys'] = sorted(j.keys()) if isinstance(j, dict) else []
            r['sev'] = j.get('severity') if isinstance(j, dict) else None
        if not r['ok'] and 'err' not in r:
            r['err'] = 'no outputs (empty/timeout: %d bytes)' % r['bytes']
        out.append(r)
    out.sort(key=lambda r: r['k'])
    return out


def htpd(cfg):
    p = os.path.join(D, 'htpd_%s.log' % cfg)
    if not os.path.exists(p):
        return dict(missing=True, steps=[], loads=[], errs=[], ready='')
    L = open(p, encoding='utf-8', errors='replace').read().splitlines()
    steps = [tuple(float(v) for v in m.groups()) for m in (STEP.search(l) for l in L) if m]
    loads = [m.group(1) for m in (LOAD.search(l) for l in L) if m]
    benign = re.compile(r'step profile|FASTRPC_GET_DOMAINS|set_abort_callback|json_abort|\b0 aborted')
    errs = [l for l in L if ERR.search(l) and not benign.search(l)][:15]
    ready = next((l for l in L if 'htpd: ready in' in l), '')
    return dict(missing=False, steps=steps, loads=loads, errs=errs, ready=ready, tail=L[-6:])


def model_ms(loads):
    v = [float(m.group(1)) for m in (re.search(r'model (\d+) ms', l) for l in loads) if m]
    return S.mean(v) if v else None


C = {c: dict(r=reqs(c), h=htpd(c)) for c in ('4b', '2b')}
for c in C:  # pair the step-profile lines with the requests in order (one line per reasoner request)
    rs, st = C[c]['r'], C[c]['h']['steps']
    for i, r in enumerate(rs):
        if r['ok'] and i < len(st):
            r['steps'], r['rows'], r['msstep'] = int(st[i][0]), st[i][1], st[i][2]


def agg(c):
    rs = [r for r in C[c]['r'] if r['k'] >= 1 and r['ok'] and 'steps' in r]
    if not rs:
        return None
    n = sum(r['steps'] for r in rs)
    return dict(n=len(rs), ms=sum(r['steps'] * r['msstep'] for r in rs) / n, steps=S.mean(r['steps'] for r in rs),
                total=S.mean(r['total'] for r in rs) / 1000, prefill=S.mean(r['prefill'] for r in rs),
                rows=S.mean(r['rows'] for r in rs), tokens=S.mean((r['tokens'] or 0) for r in rs))


A4, A2 = agg('4b'), agg('2b')
r2 = C['2b']['r']
runs = bool(C['2b']['h']['ready']) and any(r['ok'] for r in r2)
crash = [l for l in open(os.path.join(D, 'ab.log'), errors='replace').read().splitlines() if 'ABORT' in l or 'HEAT' in l] \
    if os.path.exists(os.path.join(D, 'ab.log')) else ['ab.log missing']
W = []
w = W.append
w('# q2b verdict: Qwen3.5-2B (base, Q4_0) on the QIDK NPU via htpd_v8x5 vs the live 4B reasoner')
w('')
w('Speed and execution correctness only. The 2B is the untrained BASE model, so answer quality/accuracy is NOT measured.')
w('Same window, same split requests (/data/local/tmp/rfast/rreq_split/qN.json), same htpd env (lab_ab.sh); k=0 (q10) is the warm-up and is excluded from means.')
w('')
w('## Answer')
v = 'YES' if runs and all(r['ok'] for r in r2) and not crash else ('PARTLY' if runs else 'NO')
w('- **Does the 2B run on the NPU through htpd? %s**%s' % (v, '' if v == 'YES' else ' (see errors below)'))
if A4 and A2:
    w('- **Decode ms/step: 2B %.1f vs 4B %.1f (x%.2f)**; prefill %.0f vs %.0f ms; mean total %.1f s vs %.1f s (2B steps/request %.0f vs 4B %.0f)'
      % (A2['ms'], A4['ms'], A2['ms'] / A4['ms'], A2['prefill'], A4['prefill'], A2['total'], A4['total'], A2['steps'], A4['steps']))
m4, m2 = model_ms(C['4b']['h']['loads']), model_ms(C['2b']['h']['loads'])
w('- Reasoner load (model phase, mean): 2B %s ms vs 4B %s ms' % ('%.0f' % m2 if m2 else '?', '%.0f' % m4 if m4 else '?'))
w('')
w('## Projection: 2B at the 4B\'s own step counts')
w('projected = 2B prefill(q) + 4B steps(q) x 2B ms/step(mean) + 4B non-step overhead(q). Base-model step counts differ, so this is the fair speed number.')
w('')
w('| q | 4B total s | 4B steps | 2B total s (actual) | 2B steps | 2B projected s |')
w('|---|---|---|---|---|---|')
pt, at = [], []
for r4 in C['4b']['r']:
    if r4['k'] < 1 or not r4['ok'] or 'steps' not in r4:
        continue
    b = next((x for x in r2 if x['k'] == r4['k']), None)
    proj = None
    if A2 and b and b['ok']:
        over = r4['total'] - r4['prefill'] - r4['steps'] * r4['msstep']
        proj = (b['prefill'] + r4['steps'] * A2['ms'] + max(0.0, over)) / 1000
        pt.append(proj); at.append(r4['total'] / 1000)
    w('| q%d#%d | %.1f | %d | %s | %s | %s |' % (r4['q'], r4['k'], r4['total'] / 1000, r4['steps'],
      '%.1f' % (b['total'] / 1000) if b and b['ok'] else 'FAILED', b.get('steps', '?') if b and b['ok'] else '-', '%.1f' % proj if proj else '-'))
if pt:
    w('')
    w('**Projected mean reasoner time: 2B %.1f s vs 4B %.1f s (%.0f%% saved per request).**' % (S.mean(pt), S.mean(at), 100 * (1 - S.mean(pt) / S.mean(at))))
w('')
w('## Per request')
w('| cfg | q#k | ok | stop | total ms | prefill ms | tokens | forced | steps | rows/step | ms/step | parses | keys |')
w('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for c in ('4b', '2b'):
    for r in C[c]['r']:
        if r['ok']:
            w('| %s | q%d#%d | yes | %s | %.0f | %.0f | %s | %s | %s | %s | %s | %s | %s |' % (c, r['q'], r['k'], r['stop'], r['total'], r['prefill'], r['tokens'],
              r['forced'], r.get('steps', '?'), r.get('rows', '?'), r.get('msstep', '?'), 'yes' if r['parse'] else 'NO', len(r['keys'])))
        else:
            w('| %s | q%d#%d | NO: %s | | | | | | | | | | |' % (c, r['q'], r['k'], r.get('err')))
w('')
w('Parse = the answer JSON loads. The JSON forcer forces the schema keys ("forced" = forced tokens), so a parse is execution correctness, not base-model quality.')
for c in ('2b',):
    ex = next((r for r in C[c]['r'] if r['ok'] and r['k'] >= 1), None)
    if ex:
        w('')
        w('2B sample answer (q%d, first 600 chars, for the record only):' % ex['q'])
        w('```')
        w(ex['text'][:600])
        w('```')
w('')
w('## htpd')
for c in ('4b', '2b'):
    h = C[c]['h']
    w('- %s: %s' % (c, h['ready'] or 'NO "ready" line (htpd did not start)'))
    for l in h['loads']:
        w('  - load phases: %s' % l)
    if h['errs']:
        w('  - error-like lines:')
        for l in h['errs']:
            w('    - `%s`' % l.strip()[:220])
    if c == '2b' and not runs:
        w('  - log tail: ' + ' / '.join('`%s`' % l.strip()[:200] for l in h.get('tail', [])))
w('- window ABORT/HEAT lines: %s' % ('; '.join(crash) if crash else 'none'))
w('')
w(open(EXTRA).read() if os.path.exists(EXTRA) else '')
open(OUT, 'w').write('\n'.join(W) + '\n')
print('\n'.join(W[:12]))
