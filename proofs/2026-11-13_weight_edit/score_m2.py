"""Score MEMIT eval configs vs base. Targets: decisions after a tool result (gold no think). Protected: gold-think decisions
(must keep thinking), decisions after a user message with gold no-think (must stay closed), gold-answer NLL/token."""
import json, sys, numpy as np
S = json.load(open(sys.argv[1]))
lg = lambda p: np.log(max(p, 1e-9)) - np.log(max(1 - p, 1e-9))
key = lambda r: (r["id"], r["turn"])
B = {key(r): r for r in S["base"]["rows"]}
out = []
for tag, v in S.items():
    R = [r for r in v["rows"] if key(r) in B]
    tgt = [r for r in R if r["after"] == "tool" and r["gold_think"] is False]
    thk = [r for r in R if r["gold_think"]]
    usr = [r for r in R if r["after"] == "user" and r["gold_think"] is False]
    sh = lambda rs: float(np.mean([lg(r["p_close"]) - lg(B[key(r)]["p_close"]) for r in rs])) if rs else float("nan")
    low = lambda rs, src: float(np.mean([lg(src[key(r)]["p_close"] if src is B else r["p_close"]) < 2.5 for r in rs])) if rs else float("nan")
    o = dict(cfg=tag, n_tgt=len(tgt), tgt_margin_shift=round(sh(tgt), 2), tgt_low_margin=round(low(tgt, None), 3),
             tgt_low_margin_base=round(low(tgt, B), 3), think_kept=round(float(np.mean([r["p_close"] < 0.5 for r in thk])), 3),
             think_base=round(float(np.mean([B[key(r)]["p_close"] < 0.5 for r in thk])), 3), user_closed_shift=round(sh(usr), 2),
             nll=round(v["nll_per_tok"], 4), nll_base=round(S["base"]["nll_per_tok"], 4))
    o["PASS"] = bool(o["tgt_margin_shift"] >= 3 and o["think_kept"] >= o["think_base"] - 0.02 and o["nll"] <= o["nll_base"] + 0.01)
    out.append(o); print(o)
json.dump(out, open(sys.argv[1].replace(".json", "_score.json"), "w"), indent=1)
