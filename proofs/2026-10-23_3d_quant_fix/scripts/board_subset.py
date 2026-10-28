import json, pathlib, collections
P = pathlib.Path(__file__).resolve().parents[1]; REPO = P.parents[1]
ids = json.loads((P / "post_diag/eval_set.json").read_text())["ids"]
for arm in ("v2", "v2t3d"):
    rows = {json.loads(l)["id"]: json.loads(l) for l in open(REPO / f"proofs/2026-10-23_app_ab_v2_vs_3d/{arm}/host400/samples.jsonl", encoding="utf-8")}
    sub = [rows[i] for i in ids]
    def acc(rs, k="pattern"): rs = [r for r in rs if r.get(k) is not None]; return f"{sum(r[k] for r in rs)}/{len(rs)}={sum(r[k] for r in rs)/max(1,len(rs)):.3f}"
    sl = {"ALL": sub, "1.5h": [r for r in sub if r["age"] == "b<=1.5h"], "3h": [r for r in sub if r["age"] == "c<=3h"],
          "compound": [r for r in sub if r["family"] == "compound"], "other": sub[148:]}
    print(arm, {k: (acc(v), acc(v, "status"), acc(v, "json")) for k, v in sl.items()})
