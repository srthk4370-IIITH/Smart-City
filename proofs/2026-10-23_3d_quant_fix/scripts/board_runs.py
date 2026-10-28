"""All board host400 runs of v2 and 3d, on the full set and the weak slices; run-to-run agreement."""
import json, pathlib, itertools, sys
P = pathlib.Path(__file__).resolve().parents[1]; REPO = P.parents[1]
RUNS = {"v2_1020": "proofs/2026-10-20_v2_post/device/host400", "v2_1021k8": "proofs/2026-10-21_v2_confirm/host400_k8",
        "v2_1023app": "proofs/2026-10-23_app_ab_v2_vs_3d/v2/host400", "3d_1022": "proofs/2026-10-22_v2t3d_device/host400",
        "3d_1023app": "proofs/2026-10-23_app_ab_v2_vs_3d/v2t3d/host400"}
D = {k: {json.loads(l)["id"]: json.loads(l) for l in open(REPO / v / "samples.jsonl", encoding="utf-8")} for k, v in RUNS.items()}
ids = json.loads((P / "post_diag/eval_set.json").read_text())["ids"]
SL = {"ALL400": lambda r: True, "a<=40m": lambda r: r["age"] == "a<=40min", "1.5h": lambda r: r["age"] == "b<=1.5h", "3h": lambda r: r["age"] == "c<=3h",
      "compound": lambda r: r["family"] == "compound"}
out = {}
print("| run | n | json | " + " | ".join(f"pattern {s}" for s in SL) + " |")
for k, d in D.items():
    rs = list(d.values()); row = {"n": len(rs), "json_fail": sum(not r["json"] for r in rs)}
    for s, f in SL.items():
        x = [r for r in rs if f(r)]; row[s] = (sum(r["pattern"] for r in x), len(x))
    out[k] = row
    print(f"| {k} | {len(rs)} | {len(rs)-row['json_fail']}/{len(rs)} | " + " | ".join(f"{row[s][0]}/{row[s][1]} ({row[s][0]/max(1,row[s][1]):.3f})" for s in SL) + " |")
print("\npairwise: same pattern prediction (and same pattern-correctness) on the 400 rows")
for a, b in itertools.combinations(D, 2):
    c = [i for i in D[a] if i in D[b]]
    pa = lambda r: (r.get("pred") or {}).get("pattern")
    same = sum(pa(D[a][i]) == pa(D[b][i]) for i in c); flip = sum(D[a][i]["pattern"] != D[b][i]["pattern"] for i in c)
    print(f"  {a:11s} vs {b:11s}: same pattern {same}/{len(c)}, correctness flips {flip}")
    out[f"{a}|{b}"] = {"same_pattern": same, "n": len(c), "flips": flip}
(P / "board_runs.json").write_text(json.dumps(out, indent=1))
