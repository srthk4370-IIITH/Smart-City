"""Diagnosis numbers for TOPUP_WHY.md. CPU only; reads existing host/board eval outputs + test gold."""
import json, math, collections as C, sys
Q = "C:/Users/hp/Desktop/qidk/"
gold = {}
for l in open(Q + "Code/smart-city-edge-agent/data/sft_v2/test.jsonl", encoding="utf-8"):
    r = json.loads(l); g = json.loads(r["completion"].replace("<|eot_id|>", ""))
    gold[r["id"]] = dict(r, g=g)
def load(p): return {json.loads(l)["id"]: json.loads(l) for l in open(Q + p, encoding="utf-8")}
def mcn(b, c):
    n = b + c
    if n == 0: return 1.0
    k = min(b, c); p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)
out = {}
sets = {"host400_v2_board": "proofs/2026-10-23_app_ab_v2_vs_3d/v2/host400/samples.jsonl",
        "host400_3d_board": "proofs/2026-10-23_app_ab_v2_vs_3d/v2t3d/host400/samples.jsonl",
        "w208_v2_q8": "proofs/2026-10-23_3d_quant_fix/post_diag/eval/v2_q8_0/samples.jsonl",
        "w208_3d_q8": "proofs/2026-10-23_3d_quant_fix/post_diag/eval/3d_q8_0/samples.jsonl"}
S = {k: load(v) for k, v in sets.items()}
# 1. error chain (exposure): status/cause accuracy conditioned on own pattern being right/wrong
for k in ("host400_v2_board", "w208_v2_q8"):
    rows = [r for r in S[k].values() if r["json"]]
    pr = [r for r in rows if r["pattern"]]; pw = [r for r in rows if not r["pattern"]]
    ps = [r for r in pr if r["status"]]
    out[k + "_chain"] = dict(n=len(rows), pattern=len(pr) / len(rows),
        status_given_pat_ok=sum(r["status"] for r in pr) / len(pr), status_given_pat_wrong=sum(r["status"] for r in pw) / max(1, len(pw)),
        cause_given_pat_status_ok=sum(r["cause"] for r in ps) / len(ps), cause_given_pat_wrong=sum(r["cause"] for r in pw) / max(1, len(pw)),
        all3=sum(r["pattern"] and r["status"] and r["cause"] for r in rows) / len(rows))
# 2. where v2's errors are (host400 board)
v2 = S["host400_v2_board"]
def br(key):
    d = C.defaultdict(lambda: [0, 0, 0])
    for i, r in v2.items():
        kk = key(r, gold[i]); d[kk][0] += 1; d[kk][1] += (not r["pattern"]); d[kk][2] += not (r["pattern"] and r["status"] and r["cause"])
    return {str(a): f"n={b[0]} pat_err={b[1]} any_err={b[2]}" for a, b in sorted(d.items(), key=lambda x: str(x[0]))}
out["err_by_seen"] = br(lambda r, g: r["seen"])
out["err_by_size"] = br(lambda r, g: "none" if g.get("size") is None else ("<3" if g["size"] < 3 else "3-4.5" if g["size"] < 4.5 else "4.5-8" if g["size"] < 8 else ">=8"))
out["err_by_small"] = br(lambda r, g: g.get("small"))
conf = C.Counter((r["gold_pattern"], (r["pred"] or {}).get("pattern")) for r in v2.values() if not r["pattern"])
out["top_confusions_gold_to_pred"] = conf.most_common(12)
sc = C.Counter((gold[i]["g"]["likely_cause"], (r["pred"] or {}).get("likely_cause")) for i, r in v2.items() if r["pattern"] and r["status"] and not r["cause"])
out["cause_errors_when_pat_status_ok"] = sc.most_common(10)
stc = C.Counter((r["gold_status"], (r["pred"] or {}).get("status")) for r in v2.values() if r["pattern"] and not r["status"])
out["status_errors_when_pat_ok"] = stc.most_common(10)
# 3. paired v2 vs 3d (board host400, valid rows only; 208 host Q8)
for a, b in (("host400_v2_board", "host400_3d_board"), ("w208_v2_q8", "w208_3d_q8")):
    ids = [i for i in S[a] if i in S[b] and S[a][i]["json"] and S[b][i]["json"]]
    for f in ("pattern", "status", "cause"):
        w = sum((not S[a][i][f]) and S[b][i][f] for i in ids); l = sum(S[a][i][f] and not S[b][i][f] for i in ids)
        out[f"paired_{a}_vs_3d_{f}"] = dict(n=len(ids), wins_3d=w, losses_3d=l, mcnemar_p=round(mcn(w, l), 3))
# 4. eval noise / power
def ci(p, n): s = math.sqrt(p * (1 - p) / n); return round(1.96 * s * 100, 1)
out["ci95_pts"] = {f"n={n} p={p}": ci(p, n) for n, p in ((68, .85), (77, .72), (208, .875), (400, .875), (1000, .875))}
# rows needed (McNemar, alpha .05, power .8) for a net gain delta with discordance rate pd
out["rows_needed"] = {f"delta={d} pd={pd}": math.ceil((1.96 + 0.84) ** 2 * pd / d ** 2) for d in (.01, .02, .03) for pd in (.03, .06, .10)}
json.dump(out, open(Q + "proofs/2026-10-23_topup_research/analysis.json", "w"), indent=1, default=str)
for k, v in out.items(): print(k, json.dumps(v, default=str))
