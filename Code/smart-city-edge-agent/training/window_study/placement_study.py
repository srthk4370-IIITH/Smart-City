"""Placement study: how many readings after an event's onset does the 4 h agent need to read it right?

The app calls the agent once a sensor has been abnormal for 8 readings (engine.go persistReadings), with the
4 h window ending at that moment, so the event sits in the window's last few readings. Training put events
earlier (e.g. steps 12-36 readings before the end). Here the SAME event (same real base window, same
amplitude) is placed with its onset d readings before the window end, d in DELAYS, and the agent's answer
is scored per d. This picks the moment for the "refined" re-analysis (HANDBOOK 2.38).

  python placement_study.py build   --out DIR     # laptop
  python placement_study.py run     --out DIR     # htpd on the QIDK (reuses window_study.run)
  python placement_study.py analyze --out DIR
"""
import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import window_study as W  # noqa: E402
from window_study import F, G  # noqa: E402

DELAYS = (4, 8, 12, 18, 24, 36)
N = 48
PATTERNS = ("spike", "dip", "step_increase", "step_decrease", "gradual_increase", "gradual_decrease",
            "exponential_increase", "oscillation", "flatline", "erratic")


def inject_at(p, xs, s0, d, ev, m):
    """Event with onset d readings before the end; ev holds the event's fixed random parameters."""
    n = len(xs)
    o = n - d
    y = list(xs)
    A = ev["A"] * s0
    if p in ("spike", "dip"):
        sgn = 1 if p == "spike" else -1
        w = ev["w"]
        for i in range(o, min(n, o + w)):
            y[i] += sgn * A * (1.0 if i == o + w // 2 else 0.7)
    elif p in ("step_increase", "step_decrease"):
        sgn = 1 if p == "step_increase" else -1
        for i in range(o, n):
            y[i] += sgn * A
    elif p in ("gradual_increase", "gradual_decrease"):
        sgn = 1 if p == "gradual_increase" else -1
        for i in range(o, n):
            y[i] += sgn * A * (i - o + 1) / d
    elif p == "exponential_increase":
        r = ev["r"]
        for i in range(o, n):
            y[i] += A * 1.4 * (math.exp(r * (i - o + 1) / d) - 1) / (math.exp(r) - 1)
    elif p == "oscillation":
        for i in range(o, n):
            y[i] += ev["Ao"] * s0 * math.sin(2 * math.pi * (i - o) / ev["P"] + ev["ph"])
    elif p == "flatline":
        for i in range(o, n):
            y[i] = y[o]
    elif p == "erratic":
        rng = random.Random(ev["seed"])
        for i in range(o, n):
            if rng.random() < 0.45:
                y[i] += rng.gauss(0, s0 * ev["Ae"])
    return [min(m["hi"], max(m["lo"], v)) for v in y]


def build(a):
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    series = G.load_series()
    calm = defaultdict(list)
    for (role, node, metric), s in series.items():
        if role not in W.CONT_ROLES:
            continue
        for end, xs in G.windows(s, stride=12, min_have=N - 3):
            if G.split_of(end) == "test" and not G.is_zero_flat(xs) and G.is_calm(role, metric, xs):
                calm[role].append((node, metric, end, xs))
    cases, prompts = [], []
    for role in W.CONT_ROLES:
        pool = calm[role]
        if not pool:
            continue
        for p in PATTERNS:
            made = tries = 0
            while made < a.per and tries < a.per * 50:
                tries += 1
                node, metric, end, base = rng.choice(pool)
                m = F.METRICS[(role, metric)]
                s0, bst = G.scale_of(role, metric, base)
                ev = {"A": rng.uniform(5, 12) if p in ("spike", "dip") else rng.uniform(4, 10), "w": rng.randint(1, 3),
                      "r": rng.uniform(3.0, 5.0), "Ao": rng.uniform(3, 6), "P": rng.uniform(8, 16),
                      "ph": rng.uniform(0, 2 * math.pi), "Ae": rng.uniform(3, 6), "seed": rng.randint(0, 1 << 30)}
                ys = {d: inject_at(p, base, s0, d, ev, m) for d in DELAYS}
                # the event must survive clamping/rounding at the shortest delay that the training check covers
                if p not in ("flatline", "erratic") and not G.verify(p, base, ys[max(DELAYS)], s0, m["dec"]):
                    continue
                cid = f"P{len(cases):04d}"
                for d in DELAYS:
                    y = ys[d]
                    truth = W.label(role, node, metric, y, end, p, ev["A"] * s0, s0, bst["mean"], random.Random(1))
                    truth["pattern"] = p  # the injected pattern IS the truth, whatever its age
                    pr, rule = W.agent_prompt_n(role, node, G.describe(node), metric, y, end)
                    prompts.append({"id": cid, "n": d, "prompt": pr, "rule": rule, "prompt_tokens": None, "truth": truth})
                cases.append({"id": cid, "role": role, "node": node, "metric": metric, "end_epoch": end, "pattern": p,
                              "event": ev, "base": [round(v, 6) for v in base]})
                made += 1
    with open(out / "cases.jsonl", "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")
    with open(out / "prompts.jsonl", "w", encoding="utf-8") as fh:
        for p in prompts:
            fh.write(json.dumps(p) + "\n")
    man = {"created": datetime.now().isoformat(timespec="seconds"), "seed": a.seed, "delays": DELAYS, "window": N,
           "events": len(cases), "calls": len(prompts), "per_pattern_per_role": a.per,
           "patterns": Counter(c["pattern"] for c in cases), "roles": Counter(c["role"] for c in cases),
           "cases_sha256_16": hashlib.sha256((out / "cases.jsonl").read_bytes()).hexdigest()[:16]}
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    print(json.dumps(man, indent=1))


def analyze(a):
    out = Path(a.out)
    truth = {(p["id"], p["n"]): p["truth"] for p in map(json.loads, open(out / "prompts.jsonl", encoding="utf-8"))}
    pat = {c["id"]: c["pattern"] for c in map(json.loads, open(out / "cases.jsonl", encoding="utf-8"))}
    rows = [json.loads(l) for l in open(out / "samples.jsonl", encoding="utf-8")]
    R = defaultdict(lambda: defaultdict(list))  # pattern -> d -> rows
    for r in rows:
        t = truth[(r["id"], r["n"])]
        pr = W.parse(r["text"])
        r["ok_pat"] = bool(pr and pr["pattern"] == t["pattern"])
        r["ok_status"] = bool(pr and pr["status"] == t["status"])
        r["flag"] = W.flagged(pr)
        r["rule_ok"] = r.get("rule") == t["pattern"]
        r["called"] = pr["pattern"] if pr else "INVALID"
        R[pat[r["id"]]][r["n"]].append(r)
        R["ALL"][r["n"]].append(r)
    S = {}
    for p, byd in R.items():
        S[p] = {str(d): {"pattern": W.rate([r["ok_pat"] for r in byd[d]]), "status": W.rate([r["ok_status"] for r in byd[d]]),
                         "flag": W.rate([r["flag"] for r in byd[d]]), "rules_pattern": W.rate([r["rule_ok"] for r in byd[d]]),
                         "called": Counter(r["called"] for r in byd[d]).most_common(3)} for d in DELAYS if byd[d]}
    (out / "summary.json").write_text(json.dumps(S, indent=1))
    hdr = "| pattern | " + " | ".join(f"d={d} ({d * 5} min)" for d in DELAYS) + " |\n|---|" + "---|" * len(DELAYS) + "\n"
    t = ["# Placement study - agent pattern accuracy vs readings since onset (4 h window, QIDK NPU)\n\n", hdr]
    order = ["ALL"] + list(PATTERNS)
    for p in order:
        if p in S:
            t.append(f"| {p} | " + " | ".join(W.pct(S[p].get(str(d), {}).get("pattern")) for d in DELAYS) + " |\n")
    t.append("\n## Status accuracy\n\n" + hdr)
    for p in order:
        if p in S:
            t.append(f"| {p} | " + " | ".join(W.pct(S[p].get(str(d), {}).get("status")) for d in DELAYS) + " |\n")
    t.append("\n## Flagged at all (status not normal or pattern not stable)\n\n" + hdr)
    for p in order:
        if p in S:
            t.append(f"| {p} | " + " | ".join(W.pct(S[p].get(str(d), {}).get("flag")) for d in DELAYS) + " |\n")
    t.append("\n## Rules (Mode 1) pattern accuracy\n\n" + hdr)
    for p in order:
        if p in S:
            t.append(f"| {p} | " + " | ".join(W.pct(S[p].get(str(d), {}).get("rules_pattern")) for d in DELAYS) + " |\n")
    t.append("\n## What the agent called it (top 3)\n\n")
    for p in PATTERNS:
        if p in S:
            t.append(f"- **{p}**: " + "; ".join(f"d={d}: {S[p][str(d)]['called']}" for d in DELAYS if str(d) in S[p]) + "\n")
    (out / "tables.md").write_text("".join(t), encoding="utf-8")
    # paired: d vs 8 (the current call moment)
    lines = []
    by = defaultdict(dict)
    for r in rows:
        by[r["id"]][r["n"]] = r["ok_pat"]
    for d in DELAYS:
        if d == 8:
            continue
        b = sum(1 for v in by.values() if v.get(8) and not v.get(d))
        c = sum(1 for v in by.values() if v.get(d) and not v.get(8))
        n_ = b + c
        pv = min(1.0, 2 * sum(math.comb(n_, i) for i in range(min(b, c) + 1)) / 2 ** n_) if n_ else 1.0
        lines.append(f"pattern correct: only d=8: {b:3d}  only d={d:2d}: {c:3d}  McNemar p={pv:.4f}")
    (out / "paired_tests.txt").write_text("\n".join(lines) + "\n")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 4.6))
        for p in order:
            if p not in S:
                continue
            v = [S[p][str(d)]["pattern"]["rate"] for d in DELAYS]
            ax.plot([d * 5 for d in DELAYS], v, marker="o", lw=3 if p == "ALL" else 1.2, color="k" if p == "ALL" else None, label=p)
        ax.axvline(40, ls="--", c="grey")
        ax.text(41, 0.03, "current call (8 readings)", fontsize=7, color="grey")
        ax.set_xlabel("minutes since event onset (window end)")
        ax.set_ylabel("agent pattern accuracy")
        ax.set_ylim(0, 1.02)
        ax.grid(alpha=.3)
        ax.legend(fontsize=7, ncol=2)
        ax.set_title("When does the 4 h agent read the event right? (QIDK NPU)")
        fig.tight_layout()
        fig.savefig(out / "placement.svg")
    except Exception as e:  # noqa: BLE001
        print("plot skipped:", e)
    print("".join(t))
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "analyze"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--per", type=int, default=7, help="events per pattern per role")
    ap.add_argument("--batch", type=int, default=13)
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--hot", type=int, default=85)
    ap.add_argument("--cool", type=int, default=72)
    a = ap.parse_args()
    if a.cmd == "run":
        W.run(a)
    else:
        {"build": build, "analyze": analyze}[a.cmd](a)


if __name__ == "__main__":
    main()
