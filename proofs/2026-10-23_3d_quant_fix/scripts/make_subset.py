"""Eval subset for the 3d quantisation diagnosis: every host400 row in the weak slices (age b<=1.5h, c<=3h,
family=compound) + a deterministic stratified ~60 of the remaining rows (early a<=40min, >3h, no_event).
Writes post_diag/eval_set.json (format of host_eval_v2) + subset_manifest.json."""
import json, random, collections, pathlib, sys
P = pathlib.Path(__file__).resolve().parents[1]
REPO = P.parents[1]
host400 = [json.loads(l) for l in open(REPO / "proofs/2026-10-23_app_ab_v2_vs_3d/v2/host400/samples.jsonl", encoding="utf-8")]
weak = [r for r in host400 if r["age"] in ("b<=1.5h", "c<=3h") or r["family"] == "compound"]
rest = [r for r in host400 if r not in weak]
rng = random.Random(2026)
by = collections.defaultdict(list)
for r in rest:
    by[(r["age"], r["role"])].append(r)
pick = []
# early rows first (all of a<=40min not already weak), then a stratified fill to ~60
early = [r for r in rest if r["age"] == "a<=40min"]
rng.shuffle(early); pick += early[:30]
others = [r for r in rest if r["age"] != "a<=40min"]
by = collections.defaultdict(list)
for r in others: by[r["role"]].append(r)
for k in sorted(by): rng.shuffle(by[k])
while len(pick) < 60:
    for k in sorted(by):
        if by[k] and len(pick) < 60: pick.append(by[k].pop())
ids = [r["id"] for r in weak] + [r["id"] for r in pick]
assert len(set(ids)) == len(ids)
out = P / "post_diag"; out.mkdir(exist_ok=True)
man = {"n": len(ids), "n_weak": len(weak), "n_other": len(pick), "source": "host400 (proofs/2026-10-20_v2_post/eval_set.json)",
       "weak_rule": "age in (b<=1.5h, c<=3h) or family == compound", "seed": 2026,
       "by_age": collections.Counter(r["age"] for r in weak + pick), "by_family": collections.Counter(r["family"] for r in weak + pick),
       "by_role": collections.Counter(r["role"] for r in weak + pick), "ids": ids}
(out / "eval_set.json").write_text(json.dumps(man, indent=1))
print(json.dumps({k: v for k, v in man.items() if k != "ids"}, indent=1))
