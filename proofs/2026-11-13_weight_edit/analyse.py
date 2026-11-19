"""Step 1: proxy check + per-layer think direction (diff of means) and its separation. Writes analysis/dirs.npz, analysis/A1.json"""
import json, numpy as np, os
W = os.path.expanduser("~/we_work"); OUT = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_weight_edit/analysis"
G = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/gate_r3/chat_test_r3_4b.jsonl"
def load(n):
    R = [json.loads(l) for l in open(f"{W}/{n}.jsonl")]
    return R, np.load(f"{W}/{n}.npz")["H"].astype(np.float32)
tr, Ht = load("test_r3"); fr, Hf = load("fit")
gen = {}
for l in open(G):
    o = json.loads(l); gen[o["id"]] = o
res = {}
# proxy: easy test points after the last tool; generation said think if think_tokens of that turn > 0
ez = [(i, r) for i, r in enumerate(tr) if not r["hard"] and r["after"] == "tool"]
tp = fp = fn = tn = 0
for i, r in ez:
    g = gen.get(r["id"]); 
    if not g: continue
    real = sum(g["think_tokens"] or [0]) > 0
    pred = r["p_close"] < 0.5
    tp += real and pred; fn += real and not pred; fp += pred and not real; tn += (not real) and (not pred)
res["proxy_easy_after_tool"] = dict(n=len(ez), gen_think_and_proxy_think=tp, gen_think_proxy_close=fn, proxy_think_gen_close=fp, both_close=tn)
hz = [r for r in tr if r["hard"] and r["after"] == "user"]
res["test_hard_first_turn_think_rate"] = float(np.mean([r["p_close"] < 0.5 for r in hz])) if hz else None
# fit: labels = gold think
y = np.array([bool(r["gold_think"]) for r in fr]); pc = np.array([r["p_close"] for r in fr])
res["fit"] = dict(n=len(fr), gold_think=int(y.sum()),
                  easy_after_tool_n=sum((not r["hard"]) and r["after"] == "tool" for r in fr),
                  easy_after_tool_model_thinks=sum((not r["hard"]) and r["after"] == "tool" and r["p_close"] < 0.5 for r in fr),
                  gold_think_model_closes=int(((pc >= 0.5) & y).sum()), gold_nothink_model_thinks=int(((pc < 0.5) & ~y).sum()))
# direction per layer: mean(think-behaviour) - mean(close-behaviour) on fit (model behaviour, not gold)
th = pc < 0.5
U = np.zeros((32, Hf.shape[2]), np.float32); sep = []
def auc(a, b):
    s = np.concatenate([a, b]); r = s.argsort().argsort(); ra = r[:len(a)].sum()
    return (ra - len(a) * (len(a) - 1) / 2) / (len(a) * len(b))
for L in range(32):
    d = Hf[th, L].mean(0) - Hf[~th, L].mean(0); u = d / (np.linalg.norm(d) + 1e-9); U[L] = u
    # held-out separation on test: projection of easy-after-tool vs hard-first-turn
    pt = Ht[:, L] @ u
    ezi = [i for i, r in ez]; hzi = [i for i, r in enumerate(tr) if r["hard"] and r["after"] == "user"]
    tt = np.array([tr[i]["p_close"] < 0.5 for i in range(len(tr))])
    sep.append(dict(L=L, auc_fit=float(auc(Hf[th, L] @ u, Hf[~th, L] @ u)), auc_test_behaviour=float(auc(pt[tt], pt[~tt])),
                    norm=float(np.linalg.norm(d)), mean_resid_norm=float(np.linalg.norm(Hf[:, L], axis=1).mean())))
res["layers"] = sep
np.savez(f"{OUT}/dirs.npz", u=U)
json.dump(res, open(f"{OUT}/A1.json", "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "layers"}, indent=1))
for s in sep: print("L%02d aucfit %.3f auctest %.3f |d| %.1f |h| %.1f" % (s["L"], s["auc_fit"], s["auc_test_behaviour"], s["norm"], s["mean_resid_norm"]))
