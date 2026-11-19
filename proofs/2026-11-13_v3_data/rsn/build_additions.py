"""Owner decisions 2026-11-13: +440 'visible fault called normal' rows and +300 calm site incidents, appended to train_new.jsonl.
  python3 build_additions.py --out data/final [--seed 11114]
Same generators, verification (gen-time full_check) and dedup (all test/dev bans + existing train rows) as build_rsn.py.
Real windows: gold sensor_fault that passes the label audit AND shows a strong signature (absolute or > p99 of normal)."""
import argparse
import collections
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_rsn as B  # noqa: E402
G = B.G


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "data", "final"))
    ap.add_argument("--seed", type=int, default=11114)
    a = ap.parse_args()
    stats = collections.Counter()
    bu, be, bq, pool_ban = B.load_bans()
    aud = G._audit_ok()
    pool = [json.loads(l) for l in open(B.Q + "2026-10-25_reasoner_final/data/real_pool.jsonl")]
    ok = lambda p: p["split"] == "train" and aud[p["id"]]["supported"] == "y" and p["id"] not in pool_ban  # noqa: E731
    strong = lambda p: any("p97.5" not in s for s in aud[p["id"]]["signatures"])  # noqa: E731
    fault = [p for p in pool if ok(p) and p["gold"]["status"] == "sensor_fault" and strong(p)]
    fault_miss = [p for p in fault if (p.get("pred") or {}).get("status") == "normal"]
    normal = [p for p in pool if ok(p) and p["gold"]["status"] == "normal"]
    stats.update(pool_fault_strong=len(fault), pool_fault_real_miss=len(fault_miss), pool_normal=len(normal))
    seen = set()
    for l in open(os.path.join(a.out, "train_new.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        seen.add(B.h(B.user_of(r)) + B.h(r["messages"][-1].get("content", "")))
    tmp = os.path.join(a.out, "train_add.jsonl")
    sink = B.Sink(tmp)
    R = random.Random(a.seed)

    def until(fn, cond, cap=300):
        def f():
            for _ in range(cap):
                r = fn()
                if r is not None and cond(r):
                    return r
            stats["cap_hit"] += 1
            return None
        return f

    def sev(r):
        t = r["messages"][-1]["content"]
        return json.loads(t)["severity"]

    def agent_normal(r):
        import re
        m = re.search(r"agent: pattern=\S+ status=(\S+)", r["messages"][1]["content"])
        return m and m.group(1) == "normal"

    vfcn = lambda r: sev(r) == "sensor_fault" and agent_normal(r)  # noqa: E731
    # visible fault called normal: real misses as they happened (all available), the rest flipped real windows, then cards
    n_miss = len(fault_miss)
    if n_miss:
        it = iter(fault_miss * 3)
        B.gen_block("v4_vfcn_realmiss", min(n_miss * 2, 60), R, until(lambda: B.run_inc(R, "real", "train", stats, real_pool=[next(it)]), vfcn, 3),
                    sink, stats, (bu, be), seen)
    got = stats.get("rows:v4_vfcn_realmiss", 0)
    B.gen_block("v4_vfcn_realflip", 300 - got, R, until(lambda: B.run_inc(R, "real_flip", "train", stats, real_pool=fault), vfcn),
                sink, stats, (bu, be), seen)
    B.gen_block("v4_vfcn_card", 140, R, until(lambda: G.gen_card(R, "train", G.CD.TRAIN_TYPES, agt=R.random() < 0.75, want="fault", r_err=0.0)[0], lambda r: True),
                sink, stats, (bu, be), seen)
    # calm site incidents (gold normal), mixed sources
    calm = lambda r: sev(r) == "normal"  # noqa: E731
    B.gen_block("v4_calm_r4", 75, R, until(lambda: B.run_inc(R, "r4", "train", stats), calm), sink, stats, (bu, be), seen)
    B.gen_block("v4_calm_r1", 75, R, until(lambda: B.run_inc(R, "r1", "train", stats), calm), sink, stats, (bu, be), seen)
    B.gen_block("v4_calm_real", 75, R, until(lambda: B.run_inc(R, "real", "train", stats, real_pool=normal), calm), sink, stats, (bu, be), seen)
    B.gen_block("v4_calm_card", 75, R, until(lambda: G.gen_card(R, "train", G.CD.TRAIN_TYPES, agt=R.random() < 0.75, want="normal")[0], calm),
                sink, stats, (bu, be), seen)
    sink.close()
    # card rows come straight from gen_card: run the same row check + metadata as run_inc
    rows, bad = [], 0
    for l in open(tmp, encoding="utf-8"):
        r = json.loads(l)
        e = G.full_check(r)
        if e:
            bad += 1
            stats["fail_add:" + e[0].split(":")[0]] += 1
            continue
        r.setdefault("agent_format", "agt_v3" if "\n  agent data: " in r["messages"][1]["content"] else "B50")
        r.setdefault("reasoning_type", "none")
        r.setdefault("hops", 0)
        r["think"] = bool(r["messages"][-1].get("reasoning_content"))
        r["owner_add"] = "2026-11-13"
        rows.append(r)
    with open(os.path.join(a.out, "train_new.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.remove(tmp)
    stats["appended"] = len(rows)
    stats["dropped_check"] = bad
    json.dump(dict(sorted(stats.items())), open(os.path.join(a.out, "build_stats_additions.json"), "w"), indent=1)
    print(json.dumps(dict(sorted(stats.items()))))


if __name__ == "__main__":
    main()
