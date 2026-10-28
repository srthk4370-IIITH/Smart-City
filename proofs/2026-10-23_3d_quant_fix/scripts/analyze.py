"""Tables for RESULTS.md: per tag (host evals in post_diag/eval/) and the two board runs, on the diagnosis subset:
pattern/status/cause/json per slice; paired diffs vs a reference; host-vs-board agreement for the same model."""
import json, sys, pathlib, itertools
P = pathlib.Path(__file__).resolve().parents[1]; REPO = P.parents[1]
sys.path.insert(0, str(REPO / "Code/smart-city-edge-agent/training/v2/post"))
import common_v2 as C
ids = json.loads((P / "post_diag/eval_set.json").read_text())["ids"]; S = set(ids)
other = set(ids[148:])
def load(p): return {json.loads(l)["id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}
runs = {}
for d in sorted((P / "post_diag/eval").glob("*/samples.jsonl")):
    runs[d.parent.name] = {k: v for k, v in load(d).items() if k in S}
runs["BOARD_v2"] = {k: v for k, v in load(REPO / "proofs/2026-10-23_app_ab_v2_vs_3d/v2/host400/samples.jsonl").items() if k in S}
runs["BOARD_3d"] = {k: v for k, v in load(REPO / "proofs/2026-10-23_app_ab_v2_vs_3d/v2t3d/host400/samples.jsonl").items() if k in S}
SL = {"weak148": lambda r: r["id"] not in other, "1.5h": lambda r: r["age"] == "b<=1.5h", "3h": lambda r: r["age"] == "c<=3h",
      "compound": lambda r: r["family"] == "compound", "other60": lambda r: r["id"] in other, "ALL": lambda r: True}
def rate(rs, k):
    x = [r[k] for r in rs if r.get(k) is not None]; return sum(x), len(x)
lines = ["| model | n | json | pattern weak148 | pattern 1.5h | pattern 3h | pattern compound | pattern other60 | pattern ALL | status ALL | cause ALL |", "|---|---|---|---|---|---|---|---|---|---|---|"]
res = {}
for t, d in runs.items():
    rs = list(d.values()); row = {}
    for s, f in SL.items():
        k, n = rate([r for r in rs if f(r)], "pattern"); row[s] = [k, n]
    for m in ("status", "cause", "json"):
        row[m] = list(rate(rs, m))
    res[t] = row
    fmt = lambda v: f"{v[0]}/{v[1]} ({v[0]/max(1,v[1]):.3f})"
    lines.append(f"| {t} | {len(rs)} | {fmt(row['json'])} | " + " | ".join(fmt(row[s]) for s in SL if s != "ALL") + f" | {fmt(row['ALL'])} | {fmt(row['status'])} | {fmt(row['cause'])} |")
pairs = [x.split(":") for x in sys.argv[1:]]  # "ref:cand"
lines += ["", "| ref -> cand | n | pattern ref | pattern cand | cand wins | cand losses | McNemar p | same (pattern,status,cause) |", "|---|---|---|---|---|---|---|---|"]
for a, b in pairs:
    if a not in runs or b not in runs: continue
    c = [i for i in ids if i in runs[a] and i in runs[b]]
    x = [runs[a][i]["pattern"] for i in c]; y = [runs[b][i]["pattern"] for i in c]
    w = sum(1 for p, q in zip(x, y) if q and not p); l = sum(1 for p, q in zip(x, y) if p and not q)
    pr = lambda r: tuple((r.get("pred") or {}).get(k) for k in ("pattern", "status", "likely_cause"))
    same = sum(pr(runs[a][i]) == pr(runs[b][i]) for i in c)
    mc = C.mcnemar(x, y)
    res[f"{a}->{b}"] = {"n": len(c), "wins": w, "losses": l, "mcnemar": mc, "same": same}
    lines.append(f"| {a} -> {b} | {len(c)} | {sum(x)} | {sum(y)} | {w} | {l} | {mc['p']} | {same}/{len(c)} |")
(P / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8"); (P / "tables.json").write_text(json.dumps(res, indent=1))
print("\n".join(lines))
