"""check_data.py: what may leave the laptop, checked before every upload (V3_DESIGN.md §4.1 / owner round 4).
  python check_data.py TRAIN GENDEV CALIB_STATS GEN_N OUT_DIR
- every train / gen-dev row parses (rows.norm), ids unique, no train/dev id overlap;
- provenance: synthetic only (no source real* / heldout / campus, no synthetic=false; file names must not say real/heldout/campus);
- calib_stats.json is aggregates only: no key that looks like samples/windows/series/rows, no list longer than 400 numbers;
- writes OUT_DIR/train.jsonl, OUT_DIR/gendev.jsonl (first GEN_N dev rows), OUT_DIR/calib_stats.json, OUT_DIR/data_report.json.
exit 0 ok | 1 refused (reason printed)."""
import collections
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kaggle"))
import rows as RW  # noqa: E402

train, gendev, calib, gen_n, out = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
BAD_NAME = re.compile(r"real|heldout|held_out|campus", re.I)
BAD_KEY = re.compile(r"^(samples?|windows?|series|rows?|values|readings|raw)$", re.I)


def refuse(m):
    print("REFUSED: " + m)
    sys.exit(1)


for p in (train, gendev, calib):
    if not os.path.exists(p):
        refuse("missing " + p)
    if BAD_NAME.search(os.path.basename(p)):
        refuse("file name suggests real data: " + p)
rep = {}
ids = {}
for name, p, lim in (("train", train, None), ("gendev", gendev, gen_n)):
    raw = RW.read_jsonl(p)[:lim] if lim else RW.read_jsonl(p)
    seen = set()
    fam, role, st = collections.Counter(), collections.Counter(), collections.Counter()
    for r in raw:
        bad = RW.provenance_problem(r, name)
        if bad:
            refuse(bad)
        try:
            n = RW.norm(r)
        except Exception as e:  # noqa: BLE001
            refuse("%s: %s" % (name, e))
        if n["id"] in seen:
            refuse("%s: duplicate id %s" % (name, n["id"]))
        seen.add(n["id"])
        fam[n["family"]] += 1
        role[n["role"]] += 1
        st[RW.fields(n["gold"])["status"]] += 1
    ids[name] = seen
    rep[name] = {"n": len(raw), "family": dict(fam), "role": dict(role), "status": dict(st)}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, name + ".jsonl"), "w", encoding="utf-8") as f:
        for r in raw:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
ov = ids["train"] & ids["gendev"]
if ov:
    refuse("%d ids in both train and gen-dev (e.g. %s)" % (len(ov), sorted(ov)[:3]))
c = json.load(open(calib))


def walk(x, path):
    if isinstance(x, dict):
        for k, v in x.items():
            if BAD_KEY.match(str(k)) and isinstance(v, (list, dict)) and len(v) > 50:
                refuse("calib_stats key %s/%s looks like per-sample data" % (path, k))
            walk(v, path + "/" + str(k))
    elif isinstance(x, list):
        if len(x) > 400:
            refuse("calib_stats list %s has %d entries (> 400: not an aggregate)" % (path, len(x)))
        for i, v in enumerate(x):
            walk(v, "%s[%d]" % (path, i))


walk(c, "")
shutil.copy(calib, os.path.join(out, "calib_stats.json"))
json.dump(rep, open(os.path.join(out, "data_report.json"), "w"), indent=1)
print(json.dumps({k: v["n"] for k, v in rep.items()}))
