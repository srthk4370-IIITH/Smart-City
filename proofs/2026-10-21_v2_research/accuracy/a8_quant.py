"""Paired host bf16 (HF, partial run) vs QIDK Q4_0 (htpd) on the same eval ids -> Q4_0 + NPU-runtime loss estimate."""
import json, math
from collections import Counter
from pathlib import Path
P = Path(__file__).resolve().parents[2] / "2026-10-20_v2_post"
h = {r["id"]: r for r in map(json.loads, open(P / "eval/hf_bf16/samples.jsonl", encoding="utf-8"))}
d = {}
for f in ("device/host400/samples.jsonl", "device/test_all/samples.jsonl"):
    for r in map(json.loads, open(P / f, encoding="utf-8")):
        d.setdefault(r["id"], r)
ids = [i for i in h if i in d]
print("paired rows:", len(ids), "of host", len(h))
M = ["json", "pattern", "status", "cause", "action", "event_active", "onset_15", "policy", "false_alarm"]
def mcn(b, c):
    n = b + c
    if n == 0: return 1.0
    k = min(b, c); return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
lines = ["| metric | n | host bf16 | device Q4_0 | delta | host-only right | device-only right | exact McNemar p |", "|---|---|---|---|---|---|---|---|"]
for m in M:
    pr = [(h[i][m], d[i][m]) for i in ids if h[i].get(m) is not None and d[i].get(m) is not None]
    if not pr: continue
    a = sum(x for x, _ in pr); b = sum(y for _, y in pr)
    ho = sum(1 for x, y in pr if x and not y); do = sum(1 for x, y in pr if y and not x)
    lines.append(f"| {m} | {len(pr)} | {a/len(pr):.3f} | {b/len(pr):.3f} | {(b-a)/len(pr)*100:+.1f} | {ho} | {do} | {mcn(ho, do):.3f} |")
same_text = sum(h[i]["text"].strip() == d[i]["text"].strip() for i in ids)
same_pat = sum(h[i]["pred"]["pattern"] == d[i]["pred"]["pattern"] for i in ids if h[i].get("pred") and d[i].get("pred"))
lines.append(f"\nidentical text {same_text}/{len(ids)}; identical pattern label {same_pat}/{len(ids)}")
lines.append("roles: " + str(Counter(h[i]["role"] for i in ids)) + "; families: " + str(Counter(h[i]["family"] for i in ids)))
dis = [(i, h[i]["gold_pattern"], h[i]["pred"]["pattern"], d[i]["pred"]["pattern"] if d[i].get("pred") else None) for i in ids if h[i].get("pred") and (not d[i].get("pred") or h[i]["pred"]["pattern"] != d[i]["pred"]["pattern"])]
lines.append("pattern disagreements (id, gold, host, device): " + "; ".join(map(str, dis)))
open(Path(__file__).parent / "quant_loss_paired.md", "w", encoding="utf-8").write("# Host bf16 vs device Q4_0, paired\n\n" + "\n".join(lines))
print("\n".join(lines))
