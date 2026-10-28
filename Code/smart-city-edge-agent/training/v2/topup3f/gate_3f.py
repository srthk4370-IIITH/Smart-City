"""Compact gate view of host_eval3e tables.json: per candidate, key slices (pattern/status/cause %, W/L) and every
slice with n >= MIN where pattern or status is down > 1 pt vs v2.   python gate_3f.py TABLES.json [MIN]"""
import json, sys
T = json.load(open(sys.argv[1])); MIN = int(sys.argv[2]) if len(sys.argv) > 2 else 20
KEY = ["ALL", "stage_early", "stage_1.5h", "stage_3h", "compound", "calm_or_routine", "routine", "role_power", "role_water",
       "sensor_fault", "seen_seen", "seen_unseen", "set_realworld", "set_weak", "set_host400", "set_testrest"]
def f(v, k):
    if k not in v: return "-"
    x = v[k]; return f"{100*x['ref']/x['n']:.1f}->{100*x['cand']/x['n']:.1f} ({x['wins']}/{x['losses']})"
for c, row in T.items():
    print(f"\n## {c}\n| slice | n | pattern | status | cause | json |\n|---|---|---|---|---|---|")
    for s in KEY:
        if s in row:
            v = row[s]; print(f"| {s} | {v['n']} | {f(v,'pattern')} | {f(v,'status')} | {f(v,'cause')} | {v.get('json',{}).get('cand','')}/{v.get('json',{}).get('n','')} |")
    bad = []
    for s, v in row.items():
        for k in ("pattern", "status"):
            x = v.get(k)
            if x and x["n"] >= MIN and (x["cand"] - x["ref"]) / x["n"] < -0.01:
                bad.append(f"{s}.{k} {100*x['ref']/x['n']:.1f}->{100*x['cand']/x['n']:.1f} ({x['wins']}/{x['losses']}, p {x['p']:.2f})")
    print("\nslices down >1 pt (n>=%d): " % MIN + ("; ".join(bad) if bad else "none"))
