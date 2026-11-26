"""bertscore_run.py: BERTScore (plan section 7 appendix) for every reasoner GGUF, the same hypothesis / reference pairs as textmetrics.py
(report joined root_cause + causal_chain + explanation, chat_en, tool_chain), plus the domain agent severity_reason (metrics_models.py pairs).
bert-score, roberta-large (layer 17, the package default for en), F1 raw and baseline-rescaled; bootstrap 95% CI over rows (1000).
Run in WSL venv rsn (GPU). Output results/bertscore.json."""
import json, os, re, numpy as np
from bert_score import BERTScorer
Q = "/mnt/c/Users/hp/Desktop/qidk"
GF = Q + "/proofs/2026-11-21_rsn_full/gate_full"; PAPER = Q + "/proofs/2026-11-26_paper"
MODELS = {"p2": GF + "/res/p2", "fix60": GF + "/res/new_fix60", "v5 (deployed)": GF + "/res/new", "r3c1": PAPER + "/metrics_gen/res/r3c1"}
gs = {}
for l in open(GF + "/gate_set.jsonl", encoding="utf-8"):
    r = json.loads(l); gs[r["id"]] = r
rng = np.random.default_rng(7)


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def jparse(t):
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t or "", re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except Exception:
            return None


raw = BERTScorer(lang="en", model_type="roberta-large", device="cuda", batch_size=32)
res_ = BERTScorer(lang="en", model_type="roberta-large", device="cuda", batch_size=32, rescale_with_baseline=True)


def sc(h, g):
    if not g:
        return None
    h = [x if x.strip() else "." for x in h]; g = [x if x.strip() else "." for x in g]
    out = {"n": len(g)}
    for k, s in (("f1", raw), ("f1_rescaled", res_)):
        f = s.score(h, g)[2].numpy() * 100
        b = [float(np.mean(f[rng.integers(0, len(f), len(f))])) for _ in range(1000)]
        out[k] = round(float(f.mean()), 1); out[k + "_ci"] = [round(float(np.percentile(b, 2.5)), 1), round(float(np.percentile(b, 97.5)), 1)]
    return out


res = {}
for name, d in MODELS.items():
    o = {}
    inc = load(d + "/inc.jsonl"); h, g = [], []
    for r in inc:
        gold = jparse(gs[r["id"]]["messages"][-1]["content"]) or {}
        hyp = jparse(((r.get("final") or {}).get("content")) or "") or {}
        h.append(" ".join(str(hyp.get(f) or "") for f in ("root_cause", "causal_chain", "explanation")))
        g.append(" ".join(str(gold.get(f) or "") for f in ("root_cause", "causal_chain", "explanation")))
    if inc:
        o["report"] = sc(h, g)
    for sl in ("chat_en", "tool_chain"):
        rows = load("%s/%s.jsonl" % (d, sl))
        if rows:
            o[sl] = sc([((r.get("final") or {}).get("content")) or "" for r in rows], [str(gs[r["id"]]["messages"][-1].get("content") or "") for r in rows])
    res[name] = o
    print(name, json.dumps(o), flush=True)
# domain agent severity_reason (same pairs as metrics_models.py)
G = PAPER + "/metrics_gen"
ao = G + "/agent_text_out.jsonl"
if os.path.exists(ao):
    gold_a = {json.loads(l)["id"]: json.loads(l) for l in open(G + "/agent_text_gold.jsonl", encoding="utf-8")}
    h, g = [], []
    for l in open(ao, encoding="utf-8"):
        r = json.loads(l); gd = gold_a.get(r["id"])
        if not gd:
            continue
        t = r.get("text") or ""
        hy = jparse(t) or jparse(t + ': "none"}') or {}
        gg = jparse(gd["completion"].replace("<|eot_id|>", "")) or {}
        h.append(str(hy.get("severity_reason") or "")); g.append(str(gg.get("severity_reason") or ""))
    res["domain agent agt3_s0450 (severity_reason)"] = {"severity_reason": sc(h, g)}
    print("agent", json.dumps(res["domain agent agt3_s0450 (severity_reason)"]), flush=True)
json.dump(res, open(PAPER + "/results/bertscore.json", "w"), indent=1)
