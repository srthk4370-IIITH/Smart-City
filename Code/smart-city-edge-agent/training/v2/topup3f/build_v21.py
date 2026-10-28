"""v2.1 (track A) continued-SFT file: >= 50 % replay of v2's ORIGINAL training mix + every weakness set, after
deterministic teacher-consistency filters (rows are DROPPED, never relabelled: a relabel would need a rewritten
completion = a new label rule).

Consistency rules (continuous roles power / water / air_quality / weather, rows with a stored history; DD = diag_data):
  C1 invisible_event : event pattern (not stable / flatline / erratic / oscillation) with an onset d, but the post-onset
                       amplitude < 3 noise units (DD.visibility amp) -> the window looks stable (event/stable confusion).
  C2 short_flatline  : pattern flatline (not a sensor_fault stuck row with a flat run) whose longest flat run after the
                       onset is < 6 readings -> not a flatline (gradual/flatline confusion).
  C3 flat_gradual    : pattern gradual_increase / gradual_decrease whose post-onset part is one flat run >= 80 % of d
                       -> reads as flatline (gradual/flatline confusion).
  C4 3e learnable    : rows the 3e generator flagged learnable=false (same visibility rule) are dropped.
Sources (sizes set by args): v2 train (sft_v2/train.jsonl, random, all families incl. HVAC / occupancy), 3e pool
(weakness-prioritised), 3e realworld_train, rw5_train, v21_weak, v21_aug (unseen-sensor augmentation), v21_rw5.
De-duplicated by prompt against dev3f, the 1,148-row test, rw5 dev/test, and each other.
  python build_v21.py --out ~/smartcity_runs/agents_v21/data/train_v21.jsonl [--replay 5000 --pool 1800 ...] [--dry]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "topup"))
sys.path.insert(0, str(HERE.parent))
import diag_data as DD  # noqa: E402

H = Path.home() / "smartcity_runs"
SRC = HERE.parents[2] / "data" / "sft_v2"
D3E = H / "agents_v2_topup3e" / "data"
R3F = H / "agents_v2_topup3f"
V21 = H / "agents_v21" / "data"
CONT = ("power", "water", "air_quality", "weather")
NONEVENT = ("stable", "flatline", "erratic", "oscillation", None)
rd = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
hsh = lambda p: hashlib.sha256(p.encode()).hexdigest()


def hist(r):
    h = r.get("hist")
    return json.loads(h) if isinstance(h, str) else h


def check(r):
    """-> None (keep) or the rule id that drops the row."""
    if r.get("learnable") is False:
        return "C4_3e_unlearnable"
    if r.get("role") not in CONT or not hist(r) or not r.get("n"):
        return None
    p, d = r.get("pattern"), r.get("d")
    try:
        d = int(d) if d not in (None, "None") else None
        n = int(r["n"])
        if not d or d >= n - 6:
            return None
        rr = dict(r, hist=hist(r), n=n, d=d)
        v = DD.visibility(rr)
    except Exception:  # noqa: BLE001
        return None
    if v is None:
        return None
    if p not in NONEVENT and v["amp"] is not None and v["amp"] < 3:
        return "C1_invisible_event"
    if p == "flatline" and v["flat_run_post"] < 6:
        return "C2_short_flatline"
    if p in ("gradual_increase", "gradual_decrease") and v["flat_run_post"] >= 0.8 * d:
        return "C3_flat_gradual"
    return None


def prio(r):
    s = set(r.get("slices") or [])
    w = 0
    w += 3 * bool(s & {"status_power_water", "erratic", "water_cause", "compound"})
    w += 2 * bool(s & {"exp_vs_gradual", "stage_1.5h", "stage_3h", "stage_early"})
    w += 1 * bool(s & {"calm", "routine"})
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--replay", type=int, default=5000)
    ap.add_argument("--pool", type=int, default=1800)
    ap.add_argument("--rw3e", type=int, default=400)
    ap.add_argument("--weak", type=int, default=1500)
    ap.add_argument("--aug", type=int, default=900)
    ap.add_argument("--rw5", type=int, default=1100)
    ap.add_argument("--seed", default="v21")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    block = set()
    for f in [R3F / "dev" / "dev3f.jsonl", H / "agents_v2_topup3e" / "eval" / "eval3e.jsonl", R3F / "rw5" / "rw5_dev.jsonl", R3F / "rw5" / "rw5_test.jsonl"]:
        block |= {hsh(x["prompt"]) for x in rd(f)}
    drops, used, man_src = Counter(), set(), {}

    def take(name, rows, k, key=None):
        ok = []
        for r in rows:
            hp = hsh(r["prompt"])
            if hp in block or hp in used:
                drops[f"{name}:dup_or_eval"] += 1
                continue
            c = check(r)
            if c:
                drops[f"{name}:{c}"] += 1
                continue
            ok.append(r)
        rng.shuffle(ok)
        if key:
            ok.sort(key=lambda r: -key(r))
        sel = ok[:k]
        for r in sel:
            used.add(hsh(r["prompt"]))
        man_src[name] = {"available": len(ok), "taken": len(sel), "roles": Counter(r["role"] for r in sel),
                         "status": Counter(r.get("status") for r in sel)}
        return [{"type": "sft", "id": r["id"], "prompt": r["prompt"], "completion": r["completion"], "src": name,
                 "slices": r.get("slices") or []} for r in sel]

    items = []
    items += take("v21_rw5", rd(V21 / "v21_rw5.jsonl"), a.rw5)
    items += take("rw5_train", rd(R3F / "rw5" / "rw5_train.jsonl"), max(0, a.rw5 - len(items)) + 600)
    items += take("v21_aug", rd(V21 / "v21_aug.jsonl"), a.aug)
    items += take("v21_weak", rd(V21 / "v21_weak.jsonl"), a.weak, prio)
    items += take("pool3e", rd(D3E / "pool.jsonl"), a.pool, prio)
    items += take("rw3e", rd(D3E / "realworld_train.jsonl"), a.rw3e)
    weak_n = len(items)
    items += take("v2_replay", rd(SRC / "train.jsonl"), max(a.replay, weak_n))
    rng.shuffle(items)
    man = {"rows": len(items), "replay_share": round(sum(x["src"] == "v2_replay" for x in items) / max(1, len(items)), 3),
           "sources": man_src, "drops": dict(sorted(drops.items())), "args": vars(a),
           "rules": __doc__.split("Consistency rules")[1].split("Sources")[0].strip()}
    if not a.dry:
        with open(a.out, "w", encoding="utf-8") as fh:
            for x in items:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
        man["sha256_16"] = hashlib.sha256(Path(a.out).read_bytes()).hexdigest()[:16]
        Path(a.out).with_suffix(".manifest.json").write_text(json.dumps(man, indent=1, default=str))
    print(json.dumps({"rows": man["rows"], "replay_share": man["replay_share"], "taken": {k: v["taken"] for k, v in man_src.items()},
                      "drops": man["drops"]}))


if __name__ == "__main__":
    main()
