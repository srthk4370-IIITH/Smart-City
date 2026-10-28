"""Gate with track-B post-rules on (what runs live, post_rules=all): candidate+rules vs v2+rules, paired, per slice.
  python cmp_rules.py CAND [--ref v2cuda] [--sets test rw5test] [--min-n 25] [--out f.json]
One line per set: ALL / stages / compound / calm pattern & status (ref>cand (W/L)), JSON, and every slice with
n >= min-n whose pattern / status / cause drops > 1 pt."""
import argparse, json, sys
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-24_trackB/scripts")
import trackb_lib as L  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("cand"); ap.add_argument("--ref", default="v2cuda")
ap.add_argument("--sets", nargs="+", default=["test", "rw5test"]); ap.add_argument("--min-n", type=int, default=25)
ap.add_argument("--keys", default="pattern,status,cause"); ap.add_argument("--out")
a = ap.parse_args(); RULES = list(L.RULES); res = {}
for ds in a.sets:
    R = {r["id"]: s for r, s in [(r, L.apply(r, s, RULES)[0]) for r, s in L.load(ds, a.ref)]}
    C = {r["id"]: s for r, s in [(r, L.apply(r, s, RULES)[0]) for r, s in L.load(ds, a.cand)]}
    pairs = [(R[i], C[i]) for i in R if i in C]
    for b, c in pairs:
        c["slices"] = b["slices"]
    t = L.slice_table(pairs)
    res[ds] = t
    f = lambda s, k: (lambda n, x, y, w, l: f"{100*x/n:.1f}>{100*y/n:.1f}({w}/{l})")(*t[s][k]) if s in t and k in t[s] else "-"
    keys = [s for s in ("ALL", "stage_early", "stage_1.5h", "stage_3h", "compound", "calm_or_routine") if s in t]
    bad = [f"{s}.{k}({100*(t[s][k][2]-t[s][k][1])/t[s][k][0]:+.1f},n{t[s][k][0]})" for s in t for k in a.keys.split(",")
           if k in t[s] and t[s][k][0] >= a.min_n and (t[s][k][2] - t[s][k][1]) / t[s][k][0] < -0.01]
    js = t["ALL"].get("json"); js = f"{js[2]}/{js[0]}" if js else "-"
    print(f"[{ds}] {a.cand}+R vs {a.ref}+R n={len(pairs)}: " + " | ".join(f"{s.replace('stage_','')} p{f(s,'pattern')} s{f(s,'status')}" for s in keys)
          + f" | json {js} || down>1pt: {bad}")
if a.out:
    json.dump(res, open(a.out, "w"), default=str)
