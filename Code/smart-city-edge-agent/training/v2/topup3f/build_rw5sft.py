"""3f SFT file for the REALWORLD section-5 cases: every rw5_train row (gold teacher / section-5 label) + gold replay
(random rows of the original v2 train set, ratio --replay). No preference pairs (owner: no DPO on these labels).
  python build_rw5sft.py --rw5 rw5_train.jsonl --out train3f_rw5sft.jsonl [--replay 1.5]"""
import argparse, hashlib, json, random
from collections import Counter
from pathlib import Path
SRC = Path(__file__).resolve().parents[3] / "data" / "sft_v2"
ap = argparse.ArgumentParser(); ap.add_argument("--rw5", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--replay", type=float, default=1.5)
ap.add_argument("--event-share", type=float, default=0.0, help="share of the replay taken from stage-placed event / status rows "
                "of the 3e train-month pool that v2 answered fully right (not mdev): counters a drift to 'stable'")
a = ap.parse_args()
rd = lambda p: [json.loads(l) for l in open(p, encoding="utf-8")]
rw = rd(a.rw5); rng = random.Random("3f-rw5sft")
n_rep = int(round(len(rw) * a.replay)); n_ev = int(round(n_rep * a.event_share))
ev = []
if n_ev:
    D = Path.home() / "smartcity_runs" / "agents_v2_topup3e" / "data"
    pool = {r["id"]: r for r in rd(D / "pool.jsonl")}
    ok = [pool[m["id"]] for m in rd(D / "mined.jsonl") if m["id"] in pool and "wrong_field" not in m and all(m["ok"].values())
          and hashlib.md5(m["id"].encode()).hexdigest()[0] not in "01"
          and (pool[m["id"]].get("topup_bucket", "").startswith(("stage_", "status_", "exp_", "power_drop")))]
    ev = rng.sample(ok, min(n_ev, len(ok)))
rep = ev + rng.sample(rd(SRC / "train.jsonl"), n_rep - len(ev))
items = [{"type": "sft", "id": r["id"], "prompt": r["prompt"], "completion": r["completion"]} for r in rw + rep]
rng.shuffle(items)
with open(a.out, "w", encoding="utf-8") as fh:
    for x in items:
        fh.write(json.dumps(x, ensure_ascii=False) + "\n")
man = {"rows": len(items), "rw5": len(rw), "replay": len(rep), "rw5_cases": Counter(r["rw5_case"] for r in rw), "replay_events": len(ev),
       "sha256_16": hashlib.sha256(Path(a.out).read_bytes()).hexdigest()[:16], "args": vars(a)}
Path(a.out).with_suffix(".manifest.json").write_text(json.dumps(man, indent=1))
print(json.dumps(man))
