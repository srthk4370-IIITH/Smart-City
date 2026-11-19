#!/usr/bin/env python3
"""2026-11-13 owner: card jitter 14.7 % -> 30 % of existing-metric train rows (the agent must READ the card).

  python3 jitter_swap.py DATA_DIR NEW_DIR [target]
Swaps non-jittered existing-metric rows for new jittered rows (gen_agt.py AGT_JX=1.0, seed 4041) like for like: same
family AND same gold status, so family counts and the status mix stay unchanged. New rows are verified (verify_agt.py)
and deduplicated (exact + MinHash 0.9 on the evidence block vs gate refs, held-out splits and train).
Keeps train.jsonl as train_before_jitter.jsonl. Report: reports/jitter_swap.json
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
TARGET = float(sys.argv[3]) if len(sys.argv) > 3 else 0.30
out = D / "agt_v3"
rep = out / "reports"
tr = out / "train.jsonl"
bak = out / "train_before_jitter.jsonl"
if not bak.exists():
    bak.write_bytes(tr.read_bytes())
rows = [json.loads(l) for l in open(bak, encoding="utf-8")]
exist = [i for i, r in enumerate(rows) if not r["card_synthetic"]]
jit0 = sum(bool(rows[i]["jittered"]) for i in exist)
need = int(round(TARGET * len(exist))) - jit0

raw = out / "_raw_jitter.jsonl"
with open(raw, "w", encoding="utf-8") as o:
    for f in sorted(glob.glob(str(S / "shards" / "train__*.jsonl"))):
        o.write(open(f, encoding="utf-8").read())
ver = out / "_jitter_verified.jsonl"
subprocess.run([sys.executable, str(HERE / "verify_agt.py"), str(raw), str(ver), str(rep / "verify_jitter.json")], check=True)

seen, sigs, lsh = set(), [], defaultdict(list)


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

new = defaultdict(list)
filt = Counter()
for l in open(ver, encoding="utf-8"):
    r = json.loads(l)
    if not r["jittered"] or r["card_synthetic"]:
        filt["not_jittered"] += 1
        continue
    e = P.ev_block(r["prompt"])
    h = hashlib.sha1(e.encode()).hexdigest()
    if h in seen:
        filt["exact"] += 1
        continue
    sg = P.minhash(e)
    if any(sum(a == b for a, b in zip(sg, sigs[k])) / 64 >= 0.9 for bd in P.bands(sg) for k in lsh.get(bd, ())):
        filt["near"] += 1
        continue
    seen.add(h)
    add_sig(e)
    r["id"] = "jx-" + r["id"]
    r["jitter_swap"] = "2026-11-13"
    new[(r["family"], r["gold"]["status"])].append(r)

slots = defaultdict(list)
for i in exist:
    r = rows[i]
    if not r["jittered"]:
        slots[(r["family"], r["gold"]["status"])].append(i)
rng = random.Random(4042)
for v in slots.values():
    rng.shuffle(v)
pairs = []
keys = sorted(new, key=str)
while len(pairs) < need:
    moved = False
    for k in keys:
        if len(pairs) >= need:
            break
        if new[k] and slots.get(k):
            pairs.append((slots[k].pop(), new[k].pop()))
            moved = True
    if not moved:
        break
for i, r in pairs:
    rows[i] = r
with open(str(tr) + ".part", "w", encoding="utf-8") as o:
    for r in rows:
        o.write(json.dumps(r, ensure_ascii=False) + "\n")
Path(str(tr) + ".part").replace(tr)
ex2 = [r for r in rows if not r["card_synthetic"]]
rpt = {"existing_rows": len(ex2), "jittered_before": jit0, "jittered_after": sum(bool(r["jittered"]) for r in ex2),
       "share_after": round(sum(bool(r["jittered"]) for r in ex2) / len(ex2), 4), "wanted_swaps": need, "swapped": len(pairs),
       "swapped_by_family_status": Counter("%s/%s" % k for k in (( r["family"], r["gold"]["status"]) for _, r in pairs)),
       "new_filter": dict(filt), "status_after": Counter(r["gold"]["status"] for r in rows),
       "jitter_by_family_after": Counter(r["family"] for r in ex2 if r["jittered"])}
json.dump(rpt, open(rep / "jitter_swap.json", "w"), indent=1, default=dict)
print(json.dumps({k: rpt[k] for k in ("jittered_before", "jittered_after", "share_after", "wanted_swaps", "swapped", "new_filter",
                                      "status_after")}, default=dict))
