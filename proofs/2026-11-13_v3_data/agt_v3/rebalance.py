#!/usr/bin/env python3
"""2026-11-13 owner decision: agt_v3 train fault share 22 % -> ~12 % (B50 raises 12 % false alarms on calm data).

  python3 rebalance.py DATA_DIR NEW_SHARDS_DIR [target_share]
- keeps train.jsonl as train_before_rebalance.jsonl (nothing deleted)
- drops X sensor_fault rows, deterministic, proportional per (family, fault_kind); never drops hole_calm_fault rows
  (calm vs fault contrast) and keeps every fault kind >= 300 rows
- adds X verified, deduplicated non-fault rows from NEW_SHARDS_DIR (gen_agt.py --seed 3031 --plan ...), stratified
  by family in the generated proportions
- report: reports/rebalance.json
"""
import glob
import hashlib
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import post as P  # noqa: E402

D, S = Path(sys.argv[1]), Path(sys.argv[2])
TARGET = float(sys.argv[3]) if len(sys.argv) > 3 else 0.12
out = D / "agt_v3"
rep = out / "reports"
tr = out / "train.jsonl"
bak = out / "train_before_rebalance.jsonl"
if not bak.exists():
    bak.write_bytes(tr.read_bytes())
rows = [json.loads(l) for l in open(bak, encoding="utf-8")]
isf = lambda r: r["gold"]["status"] == "sensor_fault"  # noqa: E731
N, F = len(rows), sum(map(isf, rows))
X = int(round((F - TARGET * N) / (1 - TARGET)))

# ---- choose fault rows to drop
groups = defaultdict(list)
kind_n = Counter()
for i, r in enumerate(rows):
    if isf(r):
        kind_n[r["meta"].get("fault_kind")] += 1
        if r["family"] != "hole_calm_fault":
            groups[(r["family"], r["meta"].get("fault_kind"))].append(i)
pool = sum(len(v) for v in groups.values())
drop = set()
rng = random.Random(1113)
kind_left = Counter(kind_n)
for (fam, kind), idx in sorted(groups.items(), key=lambda kv: str(kv[0])):
    want = int(round(X * len(idx) / pool))
    want = min(want, max(0, kind_left[kind] - 300))
    pick = rng.sample(idx, min(want, len(idx)))
    drop.update(pick)
    kind_left[kind] -= len(pick)
X = len(drop)

# ---- new rows: verify, non-fault, dedup vs refs/tests/train
raw = out / "_raw_rebalance.jsonl"
with open(raw, "w", encoding="utf-8") as o:
    for f in sorted(glob.glob(str(S / "shards" / "train__*.jsonl"))):
        o.write(open(f, encoding="utf-8").read())
ver = out / "_rebalance_verified.jsonl"
subprocess.run([sys.executable, str(HERE / "verify_agt.py"), str(raw), str(ver), str(rep / "verify_rebalance.json")], check=True)
seen = set()
sigs, lsh = [], defaultdict(list)


def add_sig(e):
    sg = P.minhash(e)
    k = len(sigs)
    sigs.append(sg)
    for bd in P.bands(sg):
        lsh[bd].append(k)


refs = [p for g in P.GATE_GLOBS for p in glob.glob(str(Path(g).expanduser()))]
refs += [str(out / f"{sp}.jsonl") for sp in P.SPLITS[1:]]
for p in refs:
    for l in open(p, encoding="utf-8"):
        try:
            pr = json.loads(l).get("prompt") or ""
        except Exception:  # noqa: BLE001
            continue
        if "EVIDENCE:" in pr:
            e = P.ev_block(pr)
            seen.add(hashlib.sha1(e.encode()).hexdigest())
            add_sig(e)
for r in rows:
    seen.add(hashlib.sha1(P.ev_block(r["prompt"]).encode()).hexdigest())
cand = defaultdict(list)
dup = Counter()
for l in open(ver, encoding="utf-8"):
    r = json.loads(l)
    if isf(r):
        dup["fault_skipped"] += 1
        continue
    e = P.ev_block(r["prompt"])
    h = hashlib.sha1(e.encode()).hexdigest()
    if h in seen:
        dup["exact"] += 1
        continue
    sg = P.minhash(e)
    near = any(sum(a == b for a, b in zip(sg, sigs[k])) / 64 >= 0.9 for bd in P.bands(sg) for k in lsh.get(bd, ()))
    if near:
        dup["near"] += 1
        continue
    seen.add(h)
    add_sig(e)
    r["id"] = "rb-" + r["id"]
    r["rebalance"] = "2026-11-13"
    cand[r["family"]].append(r)
avail = sum(len(v) for v in cand.values())
assert avail >= X, "not enough new non-fault rows: %d < %d" % (avail, X)
add = []
for fam, v in sorted(cand.items()):
    add += v[:int(round(X * len(v) / avail))]
got = {r["id"] for r in add}
extra = [r for fam, v in sorted(cand.items()) for r in v if r["id"] not in got]
add += extra[:max(0, X - len(add))]
add = add[:X]

final = [r for i, r in enumerate(rows) if i not in drop] + add
random.Random(1114).shuffle(final)
with open(str(tr) + ".part", "w", encoding="utf-8") as o:
    for r in final:
        o.write(json.dumps(r, ensure_ascii=False) + "\n")
Path(str(tr) + ".part").replace(tr)
rpt = {"before": {"rows": N, "faults": F, "share": round(F / N, 4)},
       "after": {"rows": len(final), "faults": sum(map(isf, final)), "share": round(sum(map(isf, final)) / len(final), 4)},
       "dropped_faults": X, "dropped_by_family_kind": Counter("%s/%s" % (rows[i]["family"], rows[i]["meta"].get("fault_kind")) for i in drop),
       "fault_kinds_after": Counter(r["meta"].get("fault_kind") for r in final if isf(r)),
       "added_by_family": Counter(r["family"] for r in add), "added_status": Counter(r["gold"]["status"] for r in add),
       "new_rows_filter": dict(dup), "status_after": Counter(r["gold"]["status"] for r in final),
       "family_after": Counter(r["family"] for r in final)}
json.dump(rpt, open(rep / "rebalance.json", "w"), indent=1, default=dict)
print(json.dumps({k: rpt[k] for k in ("before", "after", "dropped_faults", "added_by_family", "new_rows_filter")}, default=dict))
