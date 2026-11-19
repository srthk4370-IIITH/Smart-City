"""Why does agt_v3 lose dev_paired / E1 to B50? CPU only, raw gate samples.
1) each model vs BOTH gold sets (v3 teacher gold vs v2 gold) on the same windows
2) how often the two golds disagree, by role / status
3) prompt check: v3 dev_paired prompt features vs agt_v3 training prompts (header lines, window length, card kind)"""
import json, collections, sys, os, re
G = os.path.expanduser("~/smartcity_runs/agt_v3/post/gate/final_snap_1750")
GD = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/agt_v3/gate"
TR = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/agt_v3/train.jsonl"
rd = lambda p: [json.loads(l) for l in open(p, encoding="utf-8")]
for setname, fv, fb in (("dev_paired", "dev3f_v3.jsonl", "dev3f_b50.jsonl"), ("e1", "e1_v3.jsonl", "e1_b50.jsonl")):
    rv, rb = {r["pair_id"]: r for r in rd(f"{GD}/{fv}")}, {r["pair_id"]: r for r in rd(f"{GD}/{fb}")}
    sv = {s["id"]: s for s in rd(f"{G}/{setname}_v3.jsonl")}; sb = {s["id"]: s for s in rd(f"{G}/{setname}_b50.jsonl")}
    gold_b = {p: json.loads(r["completion"].replace("<|eot_id|>", "")) for p, r in rb.items()}
    n = agree = 0; c = collections.Counter(); dis = collections.Counter()
    for p, r in rv.items():
        a, b = sv.get(r["id"]), sb.get(rb.get(p, {}).get("id"))
        if not a or not b or p not in gold_b:
            continue
        gv, g2 = r["gold"]["status"], gold_b[p]["status"]
        n += 1; agree += gv == g2
        if gv != g2: dis["%s:%s(v3)/%s(v2)" % (r["role"], gv, g2)] += 1
        c["v3_on_v3gold"] += a["pred_status"] == gv; c["v3_on_v2gold"] += a["pred_status"] == g2
        c["b50_on_v2gold"] += b["pred_status"] == g2; c["b50_on_v3gold"] += b["pred_status"] == gv
        c["v3_eq_b50"] += a["pred_status"] == b["pred_status"]
        c["pat_v3gold_eq_v2gold"] += r["gold"]["pattern"] == gold_b[p]["pattern"]
    print("== %s: %d pairs | status golds agree %.1f%% | pattern golds agree %.1f%%" % (setname, n, 100 * agree / n, 100 * c["pat_v3gold_eq_v2gold"] / n))
    for k in ("v3_on_v3gold", "v3_on_v2gold", "b50_on_v2gold", "b50_on_v3gold", "v3_eq_b50"):
        print("   %-14s %.1f%%" % (k, 100 * c[k] / n))
    print("   top gold disagreements:", dis.most_common(8))
# prompt check
tr = rd(TR)[:3000]
def feats(p):
    u = p.split("user<|end_header_id|>")[1]
    return {"has_SERIES": "SERIES" in u, "has_GAPS": "GAPS:" in u, "n_lines": u.count("\n"), "window": (re.search(r"WINDOW: .*?(\d+) x 5 min", u) or [0, "?"])[1],
            "E9": "E9 " in u, "E10": "E10 " in u, "card_first": u.lstrip().startswith("CARD:")}
dv = rd(f"{GD}/dev3f_v3.jsonl")
for nm, rows in (("train", tr), ("dev3f_v3", dv)):
    f = [feats(r["prompt"]) for r in rows]
    print("== prompts %s: SERIES %.2f GAPS %.2f E9 %.2f E10 %.2f card_first %.2f mean lines %.1f windows %s" % (
        nm, *(sum(x[k] for x in f) / len(f) for k in ("has_SERIES", "has_GAPS", "E9", "E10", "card_first")), sum(x["n_lines"] for x in f) / len(f),
        collections.Counter(x["window"] for x in f).most_common(4)))
