"""Gate-length study analysis: per shape x k accuracy (pattern / status / cause / all-3, live P1 post-rules applied) with Wilson
95% CIs, and the paired difference vs k=8 (same events, bootstrap over groups). Recommended gate per shape = the smallest k whose
all-3 accuracy is NOT significantly below k=8 (paired 95% CI of the difference includes 0) and within 5 points of it.
  python gate_analyze.py TAG  -> results_TAG.json + table_TAG.md + 6 lines"""
import json, math, random, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
import dp_lib as D  # noqa: E402
import p1_rules as P  # noqa: E402

G = Path(__file__).resolve().parent
tag = sys.argv[1]
rows = D.load_rows(G / "eval3e.jsonl"); P.regold(rows)
S = D.ruled(rows, D.load_samples(G / "eval" / tag / "samples.jsonl"), D.expand("ALL_P1"))
KS = (3, 4, 5, 6, 7, 8)
by = defaultdict(dict)  # (shape, group) -> k -> {key: bool}
for i, (s, _) in S.items():
    r = rows[i]
    by[(r["shape"], r["group"])][r["k"]] = {"pattern": bool(s["pattern"]), "status": bool(s["status"]), "cause": bool(s["cause"]),
                                            "all3": bool(s["pattern"] and s["status"] and s["cause"])}


def wilson(x, n, z=1.96):
    if n == 0:
        return (None, None)
    p = x / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(100 * (c - h), 1), round(100 * (c + h), 1))


rng = random.Random(3)
res, lines = {}, []
for shape in ("spike", "step", "trend", "flatline", "noisy", "fault"):
    groups = [g for (sh, g), v in by.items() if sh == shape and all(k in v for k in KS)]
    if not groups:
        continue
    R = {}
    for k in KS:
        row = {}
        for key in ("pattern", "status", "cause", "all3"):
            x = sum(by[(shape, g)][k][key] for g in groups)
            row[key] = {"acc": round(100 * x / len(groups), 1), "ci": wilson(x, len(groups))}
        d = [by[(shape, g)][k]["all3"] - by[(shape, g)][8]["all3"] for g in groups]
        bs = sorted(sum(d[rng.randrange(len(d))] for _ in d) / len(d) for _ in range(2000))
        row["diff_vs_k8"] = {"pts": round(100 * sum(d) / len(d), 1), "ci": (round(100 * bs[50], 1), round(100 * bs[1949], 1))}
        R[k] = row
    gate = next(k for k in KS if R[k]["diff_vs_k8"]["ci"][1] >= 0 and R[k]["diff_vs_k8"]["pts"] >= -5)
    res[shape] = {"n_events": len(groups), "per_k": R, "recommended_gate": gate}
    lines.append(f"{shape:8s} n{len(groups):3d} all3 " + " ".join(f"k{k}:{R[k]['all3']['acc']:.0f}({R[k]['diff_vs_k8']['pts']:+.0f})" for k in KS) + f" -> gate k={gate}")
json.dump(res, open(G / f"results_{tag}.json", "w"), indent=1)
md = ["| shape | n | " + " | ".join(f"k={k} all-3 (vs k=8, 95% CI)" for k in KS) + " | gate |", "|---" * (len(KS) + 3) + "|"]
for sh, v in res.items():
    md.append(f"| {sh} | {v['n_events']} | " + " | ".join(f"{v['per_k'][k]['all3']['acc']:.0f} ({v['per_k'][k]['diff_vs_k8']['pts']:+.0f}, {v['per_k'][k]['diff_vs_k8']['ci'][0]:+.0f}..{v['per_k'][k]['diff_vs_k8']['ci'][1]:+.0f})" for k in KS) + f" | {v['recommended_gate']} |")
(G / f"table_{tag}.md").write_text("\n".join(md) + "\n")
print("\n".join(lines))
