"""Phase-2 diagnosis A2 (label learnability of early rows, teacher consistency) and A3 (data mix vs the original).

  python diag_data.py --out <proofs dir>
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as stt
from collections import Counter, defaultdict
from pathlib import Path

import gen_topup as T
from gen_topup import GV, G, V

R = Path.home() / "smartcity_runs"


def rd(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def visibility(r):
    """amplitude of the last d readings vs the pre-onset part, in the generator's own noise unit (scale_of)."""
    n, d = r["n"], r.get("d")
    xs = r["hist"][-n:]
    if not d or d >= n - 6:
        return None
    pre, post = xs[: n - d], xs[n - d:]
    s0, _ = G.scale_of(r["role"], r["metric"], pre)
    med = stt.median(pre)
    amp = max(abs(v - med) for v in post) / s0 if s0 else None
    shift = abs(stt.mean(post) - med) / s0 if s0 else None
    flat = max(len(list(g)) for _, g in __import__("itertools").groupby(post))
    rule = GV.rule_pattern_n(r["role"], r["metric"], xs, r["end_epoch"])
    return {"amp": amp, "shift": shift, "flat_run_post": flat, "rule": rule}


def visible(r, v):
    p = r["pattern"]
    if p == "flatline":
        return v["flat_run_post"] >= 6
    if p in ("erratic", "oscillation"):
        return v["amp"] is not None and v["amp"] >= 3 and r["d"] >= 6
    return v["amp"] is not None and v["amp"] >= 3


def a2(rows):
    early = [r for r in rows if r.get("stage") == "early" and r["role"] in ("power", "water", "air_quality", "weather")
             and r["pattern"] != "stable"]
    by = defaultdict(lambda: [0, 0, 0])  # (not visible, rule disagrees, n)
    byd = defaultdict(lambda: [0, 0])
    groups = defaultdict(Counter)
    out_rows = []
    for r in early:
        v = visibility(r)
        if v is None:
            continue
        vis = visible(r, v)
        by[r["pattern"]][0] += not vis
        by[r["pattern"]][1] += v["rule"] != r["pattern"]
        by[r["pattern"]][2] += 1
        byd[r["d"]][0] += not vis
        byd[r["d"]][1] += 1
        ab = "<2" if v["amp"] < 2 else "2-3" if v["amp"] < 3 else "3-5" if v["amp"] < 5 else ">=5"
        groups[(r["role"], v["rule"], ab, r["d"] // 3)][r["pattern"]] += 1
        out_rows.append({"id": r["id"], "pattern": r["pattern"], "d": r["d"], "amp": round(v["amp"], 2), "rule": v["rule"], "visible": vis})
    tot = sum(x[2] for x in by.values())
    nv = sum(x[0] for x in by.values())
    multi = [g for g in groups.values() if sum(g.values()) >= 3]
    maj = sum(max(g.values()) for g in multi) / max(1, sum(sum(g.values()) for g in multi))
    return {"early_rows": tot, "not_visible": nv, "not_visible_share": round(nv / max(1, tot), 3),
            "by_pattern": {p: {"n": x[2], "not_visible": x[0], "share": round(x[0] / x[2], 3), "rule_disagrees": round(x[1] / x[2], 3)}
                           for p, x in sorted(by.items())},
            "by_d": {d: {"n": x[1], "not_visible_share": round(x[0] / x[1], 3)} for d, x in sorted(byd.items())},
            "teacher_consistency": {"groups_ge3": len(multi), "majority_label_share": round(maj, 3),
                                    "note": "groups = (role, v1 rule pattern, amplitude bin, d//3); share of rows carrying their group's majority label"},
            "rows": out_rows}


def a3(named):
    res = {}
    for name, rows in named.items():
        n = len(rows)
        sh = lambda c: {k: round(v / n, 3) for k, v in sorted(c.items(), key=lambda x: -x[1])}
        comp = [len(r["completion"]) for r in rows]
        prm = [len(r["prompt"]) for r in rows]
        res[name] = {"n": n, "roles": sh(Counter(r["role"] for r in rows)),
                     "status": sh(Counter(r["status"] for r in rows)),
                     "stable_pattern_share": round(sum(r["pattern"] == "stable" for r in rows) / n, 3),
                     "normal_share": round(sum(r["status"] == "normal" for r in rows) / n, 3),
                     "families": sh(Counter(r["family"] for r in rows)),
                     "window_n": {k: round(v / n, 3) for k, v in sorted(Counter(r["n"] for r in rows).items())},
                     "d": sh(Counter("none" if r.get("d") is None else "3-9" if r["d"] <= 9 else "10-21" if r["d"] <= 21 else "22-39" if r["d"] <= 39 else ">39" for r in rows)),
                     "completion_chars_mean": round(sum(comp) / n, 1), "prompt_chars_mean": round(sum(prm) / n, 1),
                     "event_active_true": round(sum(bool(r["event_active"]) for r in rows) / n, 3)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    V.NODE_LIMITS.update(json.loads((T.SRC / "node_limits.json").read_text()))
    t3 = rd(R / "agents_v2_topup3/data/train.jsonl") + rd(R / "agents_v2_topup3/data/dev_target.jsonl")
    res2 = a2([r for r in t3 if r.get("topup_bucket") != "replay"])
    rows2 = res2.pop("rows")
    (out / "a2_learnability.json").write_text(json.dumps(res2, indent=1))
    with open(out / "a2_rows.jsonl", "w") as f:
        for x in rows2:
            f.write(json.dumps(x) + "\n")
    print(json.dumps({k: v for k, v in res2.items() if k != "by_d"}, indent=1))
    print(json.dumps(res2["by_d"]))
    orig = rd(T.SRC / "train.jsonl")
    t2 = rd(R / "agents_v2_topup2/data/train.jsonl")
    t3t = rd(R / "agents_v2_topup3/data/train.jsonl")
    named = {"original_train": orig, "phase1_train": t2, "phase2_train": t3t,
             "phase1_targeted": [r for r in t2 if r.get("topup_bucket") != "replay"],
             "phase2_targeted": [r for r in t3t if r.get("topup_bucket") != "replay"]}
    res3 = a3(named)
    (out / "a3_data_mix.json").write_text(json.dumps(res3, indent=1))
    for k, v in res3.items():
        print(k, json.dumps({x: v[x] for x in ("n", "stable_pattern_share", "normal_share", "completion_chars_mean", "prompt_chars_mean", "event_active_true", "d")}))


if __name__ == "__main__":
    main()
