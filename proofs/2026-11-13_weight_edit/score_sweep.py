"""Score sweep configs vs base: margin shift after a tool result (want +), gold-think kept (want = base), gold-no-think closed."""
import json, numpy as np, sys
S = json.load(open(sys.argv[1]))
lg = lambda p: np.log(max(p, 1e-9)) - np.log(max(1 - p, 1e-9))
def key(r): return (r["id"], r["turn"])
base = {key(r): r for r in S["base"]["rows"]}
out = []
for name, v in S.items():
    rows = v["rows"]
    at = [r for r in rows if r["gold_think"] is False and not r["hard"]]           # easy (all after tool)
    hat = [r for r in rows if r["hard"] and r["gold_think"] is False]               # hard turns gold no-think (mostly after tool)
    th = [r for r in rows if r["gold_think"]]                                       # must think
    d_easy = np.mean([lg(r["p_close"]) - lg(base[key(r)]["p_close"]) for r in at])
    d_hnt = np.mean([lg(r["p_close"]) - lg(base[key(r)]["p_close"]) for r in hat]) if hat else float("nan")
    keep = np.mean([r["p_close"] < 0.5 for r in th]); keep0 = np.mean([base[key(r)]["p_close"] < 0.5 for r in th])
    d_th = np.median([lg(r["p_close"]) - lg(base[key(r)]["p_close"]) for r in th])
    low = np.mean([lg(r["p_close"]) < 2.5 for r in at])
    out.append(dict(cfg=name, easy_margin_shift=round(float(d_easy), 2), hard_nothink_shift=round(float(d_hnt), 2),
                    think_kept=round(float(keep), 3), think_base=round(float(keep0), 3), think_logit_shift_med=round(float(d_th), 2),
                    easy_low_margin_share=round(float(low), 3), n_easy=len(at), n_think=len(th)))
for o in out: print(o)
json.dump(out, open(sys.argv[1].replace(".json", "_score.json"), "w"), indent=1)
