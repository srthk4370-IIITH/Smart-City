import json, numpy as np, os
W = os.path.expanduser("~/we_work")
G = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/gate_r3/chat_test_r3_4b.jsonl"
gen = {json.loads(l)["id"]: json.loads(l) for l in open(G)}
tr = [json.loads(l) for l in open(f"{W}/test_r3.jsonl")]
a, b = [], []
for r in tr:
    if r["hard"] or r["after"] != "tool" or r["id"] not in gen: continue
    lg = np.log(max(r["p_close"], 1e-9)) - np.log(max(1 - r["p_close"], 1e-9))
    (a if sum(gen[r["id"]]["think_tokens"] or [0]) > 0 else b).append(lg)
a, b = np.array(a), np.array(b)
q = lambda x: [round(float(np.percentile(x, p)), 2) for p in (5, 25, 50, 75, 95)]
print("logit(close) failing-73 pctl", q(a)); print("logit(close) fine easy  pctl", q(b))
s = np.concatenate([a, b]); r = s.argsort().argsort(); print("AUC low-margin predicts failure %.3f" % (1 - (r[:len(a)].sum() - len(a)*(len(a)-1)/2) / (len(a)*len(b))))
