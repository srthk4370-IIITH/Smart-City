"""Placement + window-ladder study for the v2 agent on the QIDK NPU, with features_v2 prompts.

Acceptance (RETRAIN_V2_SPEC #20): (a) pattern accuracy >= 65% at 40 min (d = 8 readings) and >= 88% at 3 h
(d = 36); (d) fewer false alarms on calm windows than today's 31%. Same design as
training/window_study/placement_study.py (2.39: 42% at 40 min, 88% at 3 h with the v1 agent), so the two are
directly comparable, but each case now carries a REAL 12 h test-month history (Nov-Dec) so E9/E10 are filled,
and the window can be any run-time length of the severity x stage ladder (48 / 96 / 144 = alert 4 h,
refine 8 h, refine 12 h).
  cases   calm 12 h base (last 4 h calm and whole 12 h without big range/slope, as window_study), the same
          event (same amplitude/shape parameters) placed with its onset d readings before the end, d in DELAYS;
          plus `clean` cases (no injection) = the false-alarm probe.
  truth   the injected pattern (status is not re-labelled here; `flag` = status != normal or pattern != stable).

  py placement_v2.py build   --out DIR [--lengths 48,96,144] [--per 7] [--clean 40]   # laptop, no device
  py placement_v2.py run     --out DIR       # htpd v2 on the QIDK (bash htpd_v2.sh start), resumable
  py placement_v2.py analyze --out DIR       # summary.json, tables.md, acceptance.json, placement_v2.svg
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common_v2 as C  # noqa: E402

sys.path.insert(0, str(C.TRAIN / "window_study"))
sys.path.insert(0, str(C.TRAIN / "export"))
import features_v2 as V  # noqa: E402
import window_study as W  # noqa: E402
import placement_study as PS  # noqa: E402
from window_study import F, G  # noqa: E402
from eval_htpd_v2 import board_c, call, pace  # noqa: E402

DELAYS = PS.DELAYS           # 4, 8, 12, 18, 24, 36 readings = 20 min .. 3 h
PATTERNS = PS.PATTERNS
HIST = V.HIST                # 144 = 12 h of history behind every prompt
QUIET = {"stable", "vacant", "occupied"}


def build(a):
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    V.NODE_LIMITS.update(json.loads((C.DATA / "node_limits.json").read_text()))
    lengths = tuple(int(x) for x in a.lengths.split(","))
    assert all(n in V.LENGTHS for n in lengths) and max(DELAYS) <= min(lengths)
    print("loading series ...", flush=True)
    series = G.load_series()
    # events: last 4 h calm (the v1 placement study's criterion, so the numbers compare); the 12 h history
    # before it is whatever really happened. clean probes: the whole 12 h calm too (as window_study "clean").
    calm, calm12 = defaultdict(list), defaultdict(list)
    for (role, node, metric), s in series.items():
        if role not in W.CONT_ROLES:
            continue
        for end, xs in W.windows_full(s, stride=12):
            if G.split_of(end) != "test" or G.is_zero_flat(xs[-48:]) or not G.is_calm(role, metric, xs[-48:]):
                continue
            calm[role].append((node, metric, end, xs))
            s0, st = G.scale_of(role, metric, xs)
            if st["range"] <= 10 * s0 and abs(st["slope_per_h"]) * 12 <= 4 * s0:
                calm12[role].append((node, metric, end, xs))
    print("calm 4 h:", {r: len(v) for r, v in calm.items()}, "calm 12 h:", {r: len(v) for r, v in calm12.items()}, flush=True)
    cases, prompts = [], []

    def add_prompts(cid, role, node, metric, end, y, d, truth):
        for n in lengths:
            pr = V.agent_prompt(role, node, G.describe(node), metric, y, n, end)[0]
            prompts.append({"id": cid, "d": d, "n": n, "prompt": pr, "truth": truth})

    for role in W.CONT_ROLES:
        pool = calm[role]
        if not pool:
            continue
        for node, metric, end, base in rng.sample(calm12[role], min(a.clean, len(calm12[role]))):
            cid = f"Q{len(cases):04d}"
            add_prompts(cid, role, node, metric, end, base, 0, {"pattern": "stable", "clean": True})
            cases.append({"id": cid, "role": role, "node": node, "metric": metric, "end_epoch": end, "pattern": "clean"})
        for p in PATTERNS:
            made = tries = 0
            while made < a.per and tries < a.per * 50:
                tries += 1
                node, metric, end, base = rng.choice(pool)
                m = F.METRICS[(role, metric)]
                s0, _ = G.scale_of(role, metric, base[-48:])
                ev = {"A": rng.uniform(5, 12) if p in ("spike", "dip") else rng.uniform(4, 10), "w": rng.randint(1, 3),
                      "r": rng.uniform(3.0, 5.0), "Ao": rng.uniform(3, 6), "P": rng.uniform(8, 16),
                      "ph": rng.uniform(0, 2 * math.pi), "Ae": rng.uniform(3, 6), "seed": rng.randint(0, 1 << 30)}
                ys = {d: PS.inject_at(p, base, s0, d, ev, m) for d in DELAYS}
                if p not in ("flatline", "erratic") and not G.verify(p, base[-48:], ys[max(DELAYS)][-48:], s0, m["dec"]):
                    continue
                cid = f"Q{len(cases):04d}"
                for d in DELAYS:
                    add_prompts(cid, role, node, metric, end, ys[d], d, {"pattern": p, "clean": False})
                cases.append({"id": cid, "role": role, "node": node, "metric": metric, "end_epoch": end, "pattern": p,
                              "event": ev})
                made += 1
    with open(out / "cases.jsonl", "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")
    with open(out / "prompts.jsonl", "w", encoding="utf-8") as fh:
        for p in prompts:
            fh.write(json.dumps(p) + "\n")
    man = {"created": datetime.now().isoformat(timespec="seconds"), "seed": a.seed, "delays": DELAYS, "lengths": lengths,
           "history_points": HIST, "events": sum(1 for c in cases if c["pattern"] != "clean"),
           "clean": sum(1 for c in cases if c["pattern"] == "clean"), "calls": len(prompts),
           "patterns": Counter(c["pattern"] for c in cases), "roles": Counter(c["role"] for c in cases),
           "prompts_sha256_16": hashlib.sha256((out / "prompts.jsonl").read_bytes()).hexdigest()[:16]}
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    print(json.dumps(man, indent=1))


def run(a):
    out = Path(a.out)
    prompts = [json.loads(l) for l in open(out / "prompts.jsonl", encoding="utf-8")]
    sp = out / "samples.jsonl"
    done = {(r["id"], r["d"], r["n"]) for r in map(json.loads, open(sp, encoding="utf-8"))} if sp.exists() else set()
    todo = [p for p in prompts if (p["id"], p["d"], p["n"]) not in done]
    by = defaultdict(list)
    for p in todo:
        by[p["n"]].append(p)
    batches = [ps[i:i + a.batch] for ps in by.values() for i in range(0, len(ps), a.batch)]
    random.Random(1).shuffle(batches)   # heat drifts equally over delays/lengths
    print(f"{len(todo)} prompts left in {len(batches)} batches", flush=True)
    with open(sp, "a", encoding="utf-8") as fh:
        for bi, b in enumerate(batches):
            c = pace(a.hot, a.cool)
            t0 = time.time()
            r = call({"kind": "agents", "prompts": [p["prompt"] + C.PREFILL for p in b]}, a.port)
            dt = time.time() - t0
            for p, o in zip(b, r["outputs"]):
                fh.write(json.dumps({"id": p["id"], "d": p["d"], "n": p["n"], "text": C.PREFILL + o["text"], "stop": o["stop"],
                                     "tokens": o["tokens"], "batch_s": round(dt, 2), "batch_size": len(b),
                                     "board_c_before": c}) + "\n")
            fh.flush()
            print(f"[{bi + 1}/{len(batches)}] n={b[0]['n']} x{len(b)} {dt:.1f}s", flush=True)


def analyze(a):
    out = Path(a.out)
    truth = {(p["id"], p["d"], p["n"]): p["truth"] for p in map(json.loads, open(out / "prompts.jsonl", encoding="utf-8"))}
    rows = [json.loads(l) for l in open(out / "samples.jsonl", encoding="utf-8")]
    R = defaultdict(list)
    for r in rows:
        t = truth[(r["id"], r["d"], r["n"])]
        p = C.parse_answer(r["text"])
        pat = C._norm(p.get("pattern", "")) if p else "INVALID"
        st = C._norm(p.get("status", "")) if p else "INVALID"
        r["ok"] = pat == t["pattern"]
        r["flag"] = st != "normal" or pat not in QUIET
        r["alarm"] = st != "normal"          # spec D3: a false alarm is status != normal
        r["called"] = pat
        key = "clean" if t["clean"] else t["pattern"]
        R[(key, r["d"], r["n"])].append(r)
        if not t["clean"]:
            R[("ALL", r["d"], r["n"])].append(r)
    rate = lambda v: {"rate": round(sum(v) / len(v), 3), "n": len(v), "ci95": C.wilson(sum(v), len(v))} if v else None
    S = {f"{k[0]}|d={k[1]}|n={k[2]}": {"pattern": rate([r["ok"] for r in v]), "flag": rate([r["flag"] for r in v]),
                                         "alarm": rate([r["alarm"] for r in v]), "called": Counter(r["called"] for r in v).most_common(3)}
         for k, v in sorted(R.items())}
    (out / "summary.json").write_text(json.dumps(S, indent=1))
    lengths = sorted({r["n"] for r in rows})
    acc = {}
    for n in lengths:
        g8, g36 = S.get(f"ALL|d=8|n={n}"), S.get(f"ALL|d=36|n={n}")
        cl = S.get(f"clean|d=0|n={n}")
        acc[f"n={n}"] = {"pattern_40min": g8 and g8["pattern"], "pattern_3h": g36 and g36["pattern"],
                         "false_alarm_clean": cl and cl["alarm"],
                         "pass_a_40min": bool(g8 and g8["pattern"]["rate"] >= 0.65),
                         "pass_a_3h": bool(g36 and g36["pattern"]["rate"] >= 0.88),
                         "pass_d_vs_31pct": bool(cl and cl["alarm"]["rate"] < 0.31),
                         "v1_reference": {"pattern_40min": 0.42, "pattern_3h": 0.88, "false_alarm": 0.31}}
    # latency per window length: every batch is one length, so batch wall time / batch size is per agent
    lat = {}
    for n in lengths:
        bs = {}
        for r in rows:
            if r["n"] == n:
                bs[(r["batch_s"], r["batch_size"])] = 1
        full = sorted(s for s, k in bs if k == max(k_ for _, k_ in bs))
        if full:
            med = full[len(full) // 2]
            lat[f"n={n}"] = {"batches": len(full), "batch_size": max(k_ for _, k_ in bs), "median_batch_s": med,
                             "per_agent_s": round(med / max(k_ for _, k_ in bs), 2),
                             "mean_out_tokens": round(sum(r["tokens"] for r in rows if r["n"] == n) /
                                                      max(1, sum(1 for r in rows if r["n"] == n)), 1)}
    acc["latency"] = lat
    (out / "acceptance.json").write_text(json.dumps(acc, indent=1))
    t = ["# v2 placement study on the QIDK NPU (features_v2 prompts, 12 h history)\n"]
    for n in lengths:
        t.append(f"\n## Window {n} x 5 min ({n * 5 / 60:g} h): pattern accuracy by readings since onset\n\n| pattern | "
                 + " | ".join(f"d={d} ({d * 5} min)" for d in DELAYS) + " |\n|---|" + "---|" * len(DELAYS))
        for p in ("ALL",) + PATTERNS:
            cells = [S.get(f"{p}|d={d}|n={n}") for d in DELAYS]
            t.append(f"| {p} | " + " | ".join(f"{100 * c['pattern']['rate']:.0f}" if c else "-" for c in cells) + " |")
        cl = S.get(f"clean|d=0|n={n}")
        if cl:
            t.append(f"\nclean windows: false alarm (status != normal) {100 * cl['alarm']['rate']:.1f}% "
                     f"(n={cl['alarm']['n']}), any flag {100 * cl['flag']['rate']:.1f}%; v1 agent: 31%")
    t.append("\n## Acceptance\n\n```\n" + json.dumps(acc, indent=1) + "\n```\n")
    (out / "tables.md").write_text("\n".join(t) + "\n", encoding="utf-8")
    print("\n".join(t))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 4.6))
        for n in lengths:
            v = [S.get(f"ALL|d={d}|n={n}") for d in DELAYS]
            ax.plot([d * 5 for d in DELAYS], [x["pattern"]["rate"] if x else None for x in v], marker="o", label=f"v2, {n * 5 / 60:g} h window")
        ax.plot([d * 5 for d in DELAYS], [None, 0.42, None, 0.67, None, 0.88], "k--", marker="x", label="v1 (2.39), 4 h")
        ax.axhline(0.65, c="grey", ls=":")
        ax.axhline(0.88, c="grey", ls=":")
        ax.set_xlabel("minutes since event onset (window end)")
        ax.set_ylabel("pattern accuracy (QIDK NPU)")
        ax.set_ylim(0, 1.02)
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / "placement_v2.svg")
    except Exception as e:  # noqa: BLE001
        print("plot skipped:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "analyze"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=23)          # same seed as the v1 placement study
    ap.add_argument("--per", type=int, default=7)
    ap.add_argument("--clean", type=int, default=40, help="clean (no event) windows per role")
    ap.add_argument("--lengths", default="48", help="comma list of window lengths, e.g. 48,96,144")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--hot", type=int, default=80)
    ap.add_argument("--cool", type=int, default=70)
    a = ap.parse_args()
    {"build": build, "run": run, "analyze": analyze}[a.cmd](a)


if __name__ == "__main__":
    main()
