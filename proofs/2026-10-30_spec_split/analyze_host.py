#!/usr/bin/env python3
"""Tables for the v9 host tests: host/<cfg>/results.json + htpd.log -> host/host_tables.md, host/host_summary.json.
usage: python3 analyze_host.py [host dir] [ref cfg for identity, default v9k0]"""
import json, os, re, sys

H = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host')
REF = sys.argv[2] if len(sys.argv) > 2 else 'v9k0'


def parse_log(path):
    """per reason request (in order): dict(steps, rows, decode_ms, spec fields...)"""
    out, cur = [], {}
    for l in open(path, errors='replace'):
        m = re.search(r'reason step profile: (\d+) steps, rows ([\d.]+)/step \(max (\d+)\); ms/step build ([\d.]+) decode ([\d.]+) pick ([\d.]+)', l)
        if m:
            cur.update(steps=int(m.group(1)), rows=float(m.group(2)), rows_max=int(m.group(3)), decode_ms=float(m.group(5)), pick_ms=float(m.group(6)))
            for k, pat in [('drafted', r'drafted (\d+)'), ('kept', r'kept (\d+)'), ('dsteps', r'draft stream-steps (\d+)'),
                           ('src_p', r'prompt (\d+)'), ('src_c', r'corpus (\d+)\)'), ('full', r'all kept (\d+)'), ('partial', r'partial (\d+)'),
                           ('extra', r'extra cert rows (\d+)'), ('ub', r'ubatches ([\d.]+)/step'), ('cp_ms', r'seq_cp\+rm ([\d.]+) ms/step'),
                           ('fork_ms', r'fork ([\d.]+) ms'), ('draft_ms', r'draft ([\d.]+) ms/call'), ('draft_max', r'\(max ([\d.]+)\), kv'),
                           ('pad', r'pad rows (\d+)')]:
                mm = re.search(pat, l)
                if mm: cur[k] = float(mm.group(1)) if '.' in mm.group(1) else int(mm.group(1))
            continue
        m = re.search(r'split at (\d+) tokens', l)
        if m: cur['split_at'] = int(m.group(1)); continue
        m = re.search(r'reason (\d+) streams, (\d+) decode steps, prefill (\d+) ms', l)
        if m:
            cur.update(streams=int(m.group(1)), steps2=int(m.group(2)), prefill_ms=int(m.group(3)))
            out.append(cur); cur = {}
    return out


def load(cfg):
    d = os.path.join(H, cfg)
    if not os.path.exists(os.path.join(d, 'results.json')): return None
    res = json.load(open(os.path.join(d, 'results.json')))
    logs = parse_log(os.path.join(d, 'htpd.log'))
    i = 0
    seen = {}
    for r in res:
        r['occ'] = seen.get(r['req'], 0); seen[r['req']] = r['occ'] + 1
        r['log'] = None
        if r['req'] != 'a2' and r.get('resp') and 'outputs' in r['resp']:
            r['log'] = logs[i] if i < len(logs) else None; i += 1
    return res


def find(rs, r):
    for x in rs or []:
        if x['req'] == r['req'] and x['occ'] == r['occ']: return x
    return None


def texts(r):
    return [o.get('text') for o in ((r.get('resp') or {}).get('outputs') or [])]


def main():
    cfgs = [c for c in ['base', 'v9k0', 'v9k8', 'v9k8s', 'v9k0b', 'v9k8n', 'v9k8a'] if load(c) is not None]
    data = {c: load(c) for c in cfgs}
    L = ['# v9 host test tables (WSL CPU)', '']
    summ = {}
    ref = data.get(REF)
    for c in cfgs:
        rows = []
        L += [f'## {c}', '', '| req | wall s | stop | tokens | steps | rows/step | decode ms/step | ubatch/step | drafted | kept % | partial % | extra rows | seq_cp ms/step | draft ms/call | RSS MB | same text as base | same as ' + REF + ' |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
        for k, r in enumerate(data[c]):
            lg = r.get('log') or {}
            o = (r.get('resp') or {}).get('outputs') or [{}]
            same_b = same_r = '-'
            xb, xr = find(data.get('base'), r), find(ref, r)
            if xb: same_b = 'yes' if texts(xb) == texts(r) else 'NO'
            if xr: same_r = 'yes' if texts(xr) == texts(r) else 'NO'
            dr = lg.get('drafted', 0)
            row = dict(req=r['req'], wall_s=r['wall_s'], stop=[x.get('stop') for x in o], tokens=[x.get('tokens') for x in o],
                       steps=lg.get('steps'), rows=lg.get('rows'), decode_ms=lg.get('decode_ms'), ub=lg.get('ub'), drafted=dr,
                       kept=lg.get('kept'), kept_pct=round(100 * lg.get('kept', 0) / dr, 1) if dr else None,
                       partial_pct=round(100 * lg.get('partial', 0) / lg['dsteps'], 1) if lg.get('dsteps') else None,
                       extra=lg.get('extra'), cp_ms=lg.get('cp_ms'), draft_ms=lg.get('draft_ms'), draft_max=lg.get('draft_max'),
                       prefill_ms=lg.get('prefill_ms'), split_at=lg.get('split_at'), rss_mb=r['rss_kb'] // 1024, same_base=same_b, same_ref=same_r)
            rows.append(row)
            f = lambda x: '-' if x is None else x
            L.append(f"| {r['req']}#{r['occ']} | {r['wall_s']} | {','.join(map(str, row['stop']))} | {','.join(map(str, row['tokens']))} | {f(row['steps'])} | {f(row['rows'])} | "
                     f"{f(row['decode_ms'])} | {f(row['ub'])} | {dr or '-'} | {f(row['kept_pct'])} | {f(row['partial_pct'])} | {f(row['extra'])} | {f(row['cp_ms'])} | "
                     f"{f(row['draft_ms'])} | {row['rss_mb']} | {same_b} | {same_r} |")
        summ[c] = rows
        L.append('')
    # paired comparison vs REF on the same reason requests (warm-up q10#1 excluded from means)
    if ref:
        for c in cfgs:
            if c == REF: continue
            pairs = [(find(ref, b), b) for b in data[c] if b['req'] != 'a2' and b.get('log') and not (b['req'] == 'q10' and b['occ'] == 0)]
            pairs = [(a, b) for a, b in pairs if a and a.get('log')]
            if not pairs: continue
            n = len(pairs)
            st0 = sum(a['log']['steps'] for a, b in pairs) / n; st1 = sum(b['log']['steps'] for a, b in pairs) / n
            w0 = sum(a['wall_s'] for a, b in pairs) / n; w1 = sum(b['wall_s'] for a, b in pairs) / n
            same = sum(texts(a) == texts(b) for a, b in pairs)
            L += [f'**{c} vs {REF}** ({n} reason requests, warm-up excluded): identical text {same}/{n}; steps {st0:.1f} -> {st1:.1f} ({100 * (st1 / st0 - 1):+.1f}%); '
                  f'wall {w0:.1f} -> {w1:.1f} s ({100 * (w1 / w0 - 1):+.1f}%)', '']
            summ[f'{c}_vs_{REF}'] = dict(n=n, identical=same, steps_ref=st0, steps=st1, wall_ref=w0, wall=w1)
    open(os.path.join(H, 'host_tables.md'), 'w').write('\n'.join(L) + '\n')
    json.dump(summ, open(os.path.join(H, 'host_summary.json'), 'w'), indent=1)
    print('\n'.join(L))


if __name__ == '__main__':
    main()
