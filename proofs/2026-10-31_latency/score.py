#!/usr/bin/env python3
"""Score a lab window (lab_ab.sh output dir): per config and request: reasoner total s, decode steps, kept %, severity,
label, title; text identity and sev+label match vs the first config. Warm-up (#0) excluded from the means.
usage: python3 score.py <window dir> [ref config]   -> prints a markdown table, writes <dir>/score.json"""
import glob, json, os, re, sys

d = sys.argv[1]
res = {}
for f in sorted(glob.glob(os.path.join(d, '*_q*_*.json'))):
    m = re.match(r'(.+)_q(\d+)_(\d+)\.json$', os.path.basename(f))
    if not m:
        continue
    cfg, q, k = m.group(1), int(m.group(2)), int(m.group(3))
    last = None
    for l in open(f, encoding='utf-8', errors='replace'):
        l = l.strip()
        if l.startswith('{"outputs"'):
            try:
                last = json.loads(l)
            except Exception:
                pass
    if not last:
        res.setdefault(cfg, []).append(dict(q=q, k=k, ok=False))
        continue
    t = last['outputs'][0].get('text', '')
    try:
        j = json.loads(t)
    except Exception:
        j = {}
    res.setdefault(cfg, []).append(dict(q=q, k=k, ok=True, s=round(last.get('total_ms', 0) / 1000, 2), text=t,
                                        sev=j.get('severity'), label=j.get('label'), title=j.get('title')))
# per-config htpd step stats in order of requests
for cfg in res:
    lg = os.path.join(d, f'htpd_{cfg}.log')
    st = []
    if os.path.exists(lg):
        for l in open(lg, errors='replace'):
            m = re.search(r'reason step profile: (\d+) steps.*?decode ([\d.]+) .*?kept \d+ \(([\d.]+)%\)', l)
            if m:
                st.append((int(m.group(1)), float(m.group(2)), float(m.group(3))))
    rs = sorted(res[cfg], key=lambda r: r['k'])
    for r, s in zip(rs, st):
        r['steps'], r['ms_step'], r['kept'] = s
ref = sys.argv[2] if len(sys.argv) > 2 else list(res)[0]
refq = {}
for r in res[ref]:
    if r['ok'] and r['k'] > 0:
        refq.setdefault(r['q'], r)
print(f"| config | req | s | steps | ms/step | kept % | sev | label | same sev+label as {ref} | same text as {ref} |")
print("|---|---|---|---|---|---|---|---|---|---|")
summ = {}
for cfg, rs in res.items():
    rs = sorted(rs, key=lambda r: r['k'])
    for r in rs:
        b = refq.get(r['q'])
        r['same_sl'] = bool(b) and r.get('sev') == b.get('sev') and r.get('label') == b.get('label')
        r['same_text'] = bool(b) and r.get('text') == b.get('text')
        print(f"| {cfg} | q{r['q']}#{r['k']} | {r.get('s')} | {r.get('steps')} | {r.get('ms_step')} | {r.get('kept')} | {r.get('sev')} | {r.get('label')} | "
              f"{'yes' if r['same_sl'] else 'NO'} | {'yes' if r['same_text'] else 'no'} |")
    w = [r for r in rs if r['k'] > 0 and r['ok']]
    if w:
        summ[cfg] = dict(n=len(w), mean_s=round(sum(r['s'] for r in w) / len(w), 2),
                         mean_steps=round(sum(r.get('steps', 0) for r in w) / len(w), 1),
                         sl=f"{sum(r['same_sl'] for r in w)}/{len(w)}", text=f"{sum(r['same_text'] for r in w)}/{len(w)}")
print()
print("| config | n | mean s | mean steps | sev+label | text |")
print("|---|---|---|---|---|---|")
for c, s in summ.items():
    print(f"| {c} | {s['n']} | {s['mean_s']} | {s['mean_steps']} | {s['sl']} | {s['text']} |")
for rs in res.values():
    for r in rs:
        r.pop('text', None)
json.dump(dict(per_request=res, summary=summ, ref=ref), open(os.path.join(d, 'score.json'), 'w'), indent=1)
