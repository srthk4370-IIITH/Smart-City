import json, glob, os, sys
D = sys.argv[1]; cfgs = ["base", "f", "base2"]; R = {}
for c in cfgs:
    for f in sorted(glob.glob(f"{D}/{c}_c*_*.json")):
        r = os.path.basename(f)[len(c) + 1:].split("_")[0]
        last = None
        for l in open(f, errors="replace"):
            try: d = json.loads(l)
            except Exception: continue
            if "outputs" in d: last = d
        if last: o = last["outputs"][0]; R.setdefault(r, {})[c] = (last.get("total_ms") or o.get("ms"), o.get("tokens"), o.get("text"))
print("| req | base ms | v9f ms | base2 ms | tokens | v9f text = base | base2 = base |\n|---|---|---|---|---|---|---|")
tot = {c: 0 for c in cfgs}; same_f = same_b2 = n = 0
for r in sorted(R, key=lambda x: int(x[1:])):
    x = R[r]
    if not all(c in x for c in cfgs): continue
    n += 1; sf = x["f"][2] == x["base"][2]; sb = x["base2"][2] == x["base"][2]; same_f += sf; same_b2 += sb
    for c in cfgs: tot[c] += x[c][0] or 0
    print(f"| {r} | {x['base'][0]:.0f} | {x['f'][0]:.0f} | {x['base2'][0]:.0f} | {x['base'][1]} | {sf} | {sb} |")
print(f"\nmean ms: " + ", ".join(f"{c} {tot[c]/max(n,1):.0f}" for c in cfgs) + f"; identical text: v9f {same_f}/{n}, base2 {same_b2}/{n}")
for r in sorted(R, key=lambda x: int(x[1:])):
    x = R[r]
    if "f" in x and "base" in x and x["f"][2] != x["base"][2]:
        print(f"\n{r} base: {x['base'][2][:300]!r}\n{r} v9f : {x['f'][2][:300]!r}")
