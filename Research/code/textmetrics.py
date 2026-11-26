"""textmetrics.py (item 7): BLEU / ROUGE-L / chrF of every reasoner GGUF on the frozen gate set (held-out free-text gold).
  slices: report (70 rows = report_all 40 + new_family 30; gold = gold JSON fields root_cause / explanation / causal_chain, scored per field and joined),
          chat_en (40 rows; gold = final assistant answer), tool_chain (20 rows; gold = final assistant answer).
  models: p2 (res/p2), fix60 = full_q4_0_prev (res/new_fix60), v5 = rep50 = full_q4_0 (res/new; md5-identical GGUFs), r3c1 (metrics_gen/res/r3c1, generated here).
  usage: textmetrics.py  -> results/textmetrics.json   (sacrebleu corpus BLEU / chrF, rouge_score ROUGE-L F mean; bootstrap 95% CI over rows)"""
import json, os, re, sys, numpy as np
import sacrebleu
from rouge_score import rouge_scorer
Q = "/mnt/c/Users/hp/Desktop/qidk"
GF = Q + "/proofs/2026-11-21_rsn_full/gate_full"; PAPER = Q + "/proofs/2026-11-26_paper"
MODELS = {"p2": GF + "/res/p2", "fix60 (full_q4_0_prev)": GF + "/res/new_fix60", "v5 = rep50 (full_q4_0, deployed)": GF + "/res/new", "r3c1": PAPER + "/metrics_gen/res/r3c1"}
extra = os.environ.get("EXTRA_MODELS")
if extra:
    MODELS.update(json.loads(extra))
gs = {}
for l in open(GF + "/gate_set.jsonl", encoding="utf-8"):
    r = json.loads(l); gs[r["id"]] = r
rs = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)
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


def score(h, g, boot=True):
    if not g:
        return None
    bl = sacrebleu.corpus_bleu(h, [g]).score; cf = sacrebleu.corpus_chrf(h, [g]).score
    rl = [rs.score(b, a)["rougeL"].fmeasure for a, b in zip(g, h)]
    out = dict(n=len(g), bleu=round(bl, 1), chrf=round(cf, 1), rougeL=round(100 * float(np.mean(rl)), 1))
    if boot:
        bb, cc, rr = [], [], []
        for _ in range(200):
            i = rng.integers(0, len(g), len(g)); hh = [h[j] for j in i]; gg = [g[j] for j in i]
            bb.append(sacrebleu.corpus_bleu(hh, [gg]).score); cc.append(sacrebleu.corpus_chrf(hh, [gg]).score); rr.append(100 * float(np.mean([rl[j] for j in i])))
        out["ci"] = dict(bleu=[round(float(np.percentile(bb, 2.5)), 1), round(float(np.percentile(bb, 97.5)), 1)], chrf=[round(float(np.percentile(cc, 2.5)), 1), round(float(np.percentile(cc, 97.5)), 1)],
                         rougeL=[round(float(np.percentile(rr, 2.5)), 1), round(float(np.percentile(rr, 97.5)), 1)])
    return out


res = {}
for name, d in MODELS.items():
    o = {}
    inc = load(d + "/inc.jsonl")
    fields = {"root_cause": ([], []), "explanation": ([], []), "causal_chain": ([], []), "joined": ([], [])}
    valid = 0
    for r in inc:
        gold = jparse(gs[r["id"]]["messages"][-1]["content"]) or {}
        hyp = jparse(((r.get("final") or {}).get("content")) or "")
        valid += hyp is not None
        hyp = hyp or {}
        for f in ("root_cause", "explanation", "causal_chain"):
            fields[f][0].append(str(hyp.get(f) or "")); fields[f][1].append(str(gold.get(f) or ""))
        fields["joined"][0].append(" ".join(str(hyp.get(f) or "") for f in ("root_cause", "causal_chain", "explanation")))
        fields["joined"][1].append(" ".join(str(gold.get(f) or "") for f in ("root_cause", "causal_chain", "explanation")))
    if inc:
        o["report"] = {f: score(h, g, boot=(f == "joined")) for f, (h, g) in fields.items()}
        o["report"]["valid_json"] = "%d/%d" % (valid, len(inc))
    for sl in ("chat_en", "tool_chain"):
        rows = load("%s/%s.jsonl" % (d, sl)); h, g = [], []
        for r in rows:
            h.append(((r.get("final") or {}).get("content")) or ""); g.append(str(gs[r["id"]]["messages"][-1].get("content") or ""))
        if rows:
            o[sl] = score(h, g)
    res[name] = o
json.dump(res, open(PAPER + "/results/textmetrics.json", "w"), indent=1)
print(json.dumps(res, indent=1)[:3500])
