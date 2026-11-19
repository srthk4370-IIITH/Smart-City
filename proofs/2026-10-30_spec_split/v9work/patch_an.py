import re
p='/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-30_spec_split/analyze_host.py'
s=open(p).read()
s=s.replace("""    i = 0
    for r in res:""","""    i = 0
    seen = {}
    for r in res:
        r['occ'] = seen.get(r['req'], 0); seen[r['req']] = r['occ'] + 1""")
s=s.replace("""def texts(r):""","""def find(rs, r):
    for x in rs or []:
        if x['req'] == r['req'] and x['occ'] == r['occ']: return x
    return None


def texts(r):""")
s=s.replace("""            if 'base' in data and k < len(data['base']) and data['base'][k]['req'] == r['req']:
                same_b = 'yes' if texts(data['base'][k]) == texts(r) else 'NO'
            if ref and k < len(ref) and ref[k]['req'] == r['req']:
                same_r = 'yes' if texts(ref[k]) == texts(r) else 'NO'""","""            xb, xr = find(data.get('base'), r), find(ref, r)
            if xb: same_b = 'yes' if texts(xb) == texts(r) else 'NO'
            if xr: same_r = 'yes' if texts(xr) == texts(r) else 'NO'""")
s=s.replace("""            pairs = [(a, b) for a, b in zip(ref, data[c]) if a['req'] == b['req'] and a['req'] != 'a2' and a.get('log') and b.get('log')]
            pairs = [p for p in pairs if not (p[0]['req'] == 'q10' and p[0].get('k') == 1)]""","""            pairs = [(find(ref, b), b) for b in data[c] if b['req'] != 'a2' and b.get('log') and not (b['req'] == 'q10' and b['occ'] == 0)]
            pairs = [(a, b) for a, b in pairs if a and a.get('log')]""")
s=s.replace("L.append(f\"| {r['req']}#{k} |","L.append(f\"| {r['req']}#{r['occ']} |")
open(p,'w').write(s)
