"""Score we_neuron eval configs vs base: think margin after tool (+), think kept on gold-think, trust gap (bad-good lp, want toward 0),
calm lp (normal incidents, must not drop), NLL/token (hallucination guard)."""
import json, sys, numpy as np
S = json.load(open(sys.argv[1])); B = S["base"]
lg = lambda p: np.log(max(p, 1e-9)) - np.log(max(1 - p, 1e-9))
k = lambda r: (r["id"], r["turn"])
bt = {k(r): r for r in B["think"]}; btr = {r["id"]: r for r in B["trust"]}; bc = {r["id"]: r for r in B["calm"]}
for tag, v in S.items():
    T = [r for r in v["think"] if r["after"] == "tool" and r["gold_think"] is False and k(r) in bt]
    H = [r for r in v["think"] if r["gold_think"] and k(r) in bt]
    sh = np.mean([lg(r["p_close"]) - lg(bt[k(r)]["p_close"]) for r in T])
    low = np.mean([lg(r["p_close"]) < 2.5 for r in T]); low0 = np.mean([lg(bt[k(r)]["p_close"]) < 2.5 for r in T])
    keep = np.mean([r["p_close"] < 0.5 for r in H]); keep0 = np.mean([bt[k(r)]["p_close"] < 0.5 for r in H])
    gap = np.mean([r["good"] - r["bad"] for r in v["trust"]]); gap0 = np.mean([btr[r["id"]]["good"] - btr[r["id"]]["bad"] for r in v["trust"]])
    badlp = np.mean([r["bad"] - btr[r["id"]]["bad"] for r in v["trust"]]); goodlp = np.mean([r["good"] - btr[r["id"]]["good"] for r in v["trust"]])
    nf = v["trust"][:60]; uf = v["trust"][60:]          # eval order: 60 'normal' flips, then 'under' flips
    gn = np.mean([r["good"] - r["bad"] for r in nf]); gn0 = np.mean([btr[r["id"]]["good"] - btr[r["id"]]["bad"] for r in nf])
    gu = np.mean([r["good"] - r["bad"] for r in uf]) if uf else 0; gu0 = np.mean([btr[r["id"]]["good"] - btr[r["id"]]["bad"] for r in uf]) if uf else 0
    print("   trust split: normal-flip gap %.2f->%.2f | under-flip gap %.2f->%.2f | frac pairs where wrong claim lowers gold lp: %.2f" % (
        gn0, gn, gu0, gu, np.mean([r["good"] - r["bad"] > 0 for r in v["trust"]])))
    calm = np.mean([r["lp"] - bc[r["id"]]["lp"] for r in v["calm"]])
    print("%-20s think: shift %+.2f low %.2f->%.2f kept %.3f/%.3f | trust gap %.2f->%.2f (bad %+.2f good %+.2f) | calm %+.2f | nll %.4f (%+.4f)" % (
        tag, sh, low0, low, keep, keep0, gap0, gap, badlp, goodlp, calm, v["nll_per_tok"], v["nll_per_tok"] - B["nll_per_tok"]))
