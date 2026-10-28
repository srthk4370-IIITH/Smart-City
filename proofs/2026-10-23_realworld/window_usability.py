"""How often would the live gate get a usable 4 h window from the real SCRC 5-min series?
Rule mirrored from engine.go Window(): 48 buckets, >= 45 present (24 for weather/occupancy), first and
last within 3 buckets of the ends. Evaluated at every hourly window end inside each node's span."""
import csv, glob, json, os, sys
root = sys.argv[1]
out = {}
for dom in sorted(os.listdir(root)):
    p = os.path.join(root, dom)
    if not os.path.isdir(p): continue
    agg = {"windows": 0, "usable": 0, "usable_with_interp": 0, "fail_edge": 0, "fail_count": 0}
    for f in glob.glob(os.path.join(p, "*.csv")):
        with open(f) as fh:
            rd = csv.reader(fh); hdr = next(rd)
            col = 1
            have = set()
            for r in rd:
                if len(r) > col and r[col] != "":
                    have.add(int(r[0]))
        if not have: continue
        lo, hi = min(have), max(have)
        minHave = 24 if dom in ("weather", "occupancy") else 45
        end = lo + 47 * 300
        while end <= hi:
            n = sum(1 for i in range(48) if end - i * 300 in have)
            first = any(end - (47 - j) * 300 in have for j in range(4))
            last = any(end - j * 300 in have for j in range(4))
            agg["windows"] += 1
            if n >= minHave and first and last:
                agg["usable"] += 1
                if n < 48: agg["usable_with_interp"] += 1
            elif not (first and last): agg["fail_edge"] += 1
            else: agg["fail_count"] += 1
            end += 3600
    if agg["windows"]:
        agg["usable_frac"] = round(agg["usable"] / agg["windows"], 3)
        agg["interp_frac_of_usable"] = round(agg["usable_with_interp"] / max(1, agg["usable"]), 3)
    out[dom] = agg
    print(dom, agg, flush=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw_audit", "window_usability.json"), "w"), indent=1)
