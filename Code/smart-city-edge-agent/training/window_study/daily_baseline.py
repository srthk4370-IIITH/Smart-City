"""Daily-baseline long-range detectors: the 12 h detectors of longrange.py run on (today - same clock time
yesterday) instead of the raw series, so a sensor's normal daily routine (loads switching, tanks
cycling, the day/night swing) cancels and only what is unusual for that hour remains.

Plain 12 h detectors could not tell real events from routine (dev: 15% false alarms on piecewise-calm
windows while catching 15-30%; HANDBOOK 2.38). Same honest protocol: tune on DEV months, evaluate once
on TEST months, events injected only into TODAY's last 12 h; yesterday stays real.

  python daily_baseline.py build --split dev  --out DIR
  python daily_baseline.py build --split test --out DIR
  python daily_baseline.py tune     --dev DIR --out DIR
  python daily_baseline.py evaluate --test DIR --params P --out DIR
"""
import argparse
import hashlib
import itertools
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import longrange as L  # noqa: E402
import window_study as W  # noqa: E402
from window_study import F, G  # noqa: E402

DAY = 288          # 24 h of 5-min points
TODAY = 144        # the 12 h judged
SPAN = DAY + TODAY  # 36 h of history needed


def diff_series(xs):
    """today's last 12 h minus the same 12 h yesterday (xs: SPAN points, oldest first)."""
    today = xs[-TODAY:]
    yday = xs[-TODAY - DAY:-DAY]
    return [a - b for a, b in zip(today, yday)]


def windows_span(series, stride):
    old = F.WINDOW
    F.WINDOW = SPAN
    try:
        yield from G.windows(series, stride, min_have=SPAN - 12)
    finally:
        F.WINDOW = old


def build(a):
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    series = G.load_series()
    pool = defaultdict(list)
    for (role, node, metric), s in series.items():
        if role not in W.CONT_ROLES:
            continue
        for end, xs in windows_span(s, stride=24):
            if G.split_of(end) == a.split and not G.is_zero_flat(xs[-TODAY:]):
                pool[role].append((node, metric, end, xs))
    calm = {r: [w for w in v if all(G.is_calm(r, w[1], w[3][-TODAY:][i:i + 48]) for i in (0, 48, 96))] for r, v in pool.items()}
    stats = {"windows_36h": {r: len(v) for r, v in pool.items()}, "piecewise_calm_today": {r: len(v) for r, v in calm.items()}}
    print(json.dumps(stats), flush=True)
    cases = []

    def add(fam, role, node, metric, end, xs, extra=None):
        c = {"id": f"D{len(cases):04d}", "family": fam, "role": role, "node": node, "metric": metric, "end_epoch": end,
             "xs": [round(v, 6) for v in xs]}
        c.update(extra or {})
        cases.append(c)

    for role in W.CONT_ROLES:
        cp = calm.get(role, [])
        if not cp:
            continue
        for node, metric, end, xs in rng.sample(cp, min(a.clean, len(cp))):
            add("clean", role, node, metric, end, xs)
        for fam in ("step_old", "drift_long", "subthr_spikes"):
            made = tries = 0
            while made < a.per and tries < a.per * 40:
                tries += 1
                node, metric, end, xs = rng.choice(cp)
                m = F.METRICS[(role, metric)]
                today = xs[-TODAY:]
                s0, _ = G.scale_of(role, metric, today[-48:])
                y = list(today)
                if fam == "step_old":
                    k = rng.randint(30, 100); sgn = rng.choice((1, -1)); A = s0 * rng.uniform(4, 10)
                    y = [v + (sgn * A if i >= TODAY - k else 0) for i, v in enumerate(y)]
                    extra = {"step_age_pts": k}
                elif fam == "drift_long":
                    Ld = rng.randint(72, TODAY); sgn = rng.choice((1, -1)); A = s0 * rng.uniform(4, 8)
                    y = [v + (sgn * A * (i - (TODAY - Ld)) / (Ld - 1) if i >= TODAY - Ld else 0) for i, v in enumerate(y)]
                    extra = {"drift_len_pts": Ld}
                else:
                    kk = rng.randint(3, 5); T = rng.randint(24, TODAY - 2)
                    pos = sorted({TODAY - 1 - rng.randint(0, 5)} | {TODAY - 1 - rng.randint(6, T) for _ in range(kk - 1)})
                    for p_ in pos:
                        y[p_] += s0 * rng.uniform(2.0, 3.5)
                    if m["warn"] is not None and m["dir"] == "high" and max(y) >= m["warn"]:
                        continue
                    extra = {"spike_idx": pos}
                y = [min(m["hi"], max(m["lo"], v)) for v in y]
                add(fam, role, node, metric, end, xs[:-TODAY] + y, extra)
                made += 1
        # real windows (no injection, not filtered for calm): how often would it fire in practice?
        for node, metric, end, xs in rng.sample(pool[role], min(a.real, len(pool[role]))):
            add("real", role, node, metric, end, xs)
    with open(out / "cases.jsonl", "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")
    man = {"created": datetime.now().isoformat(timespec="seconds"), "split": a.split, "seed": a.seed, "span_pts": SPAN,
           "families": Counter(c["family"] for c in cases), "roles": Counter(c["role"] for c in cases), "pool": stats,
           "cases_sha256_16": hashlib.sha256((out / "cases.jsonl").read_bytes()).hexdigest()[:16]}
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    print(json.dumps(man, indent=1))


def feats(c):
    """Statistics for both variants: raw 12 h (longrange as before) and daily-differenced 12 h."""
    raw = c["xs"][-TODAY:]
    return {"raw": L.stats(c["role"], c["metric"], raw), "daily": L.stats(c["role"], c["metric"], diff_series(c["xs"]))}


TARGET = {"level_shift": "step_old", "slow_drift": "drift_long", "recurring_excursions": "subthr_spikes"}


def grid_eval(cases, pre, variant, P):
    fp, tp = [], defaultdict(list)
    for c in cases:
        f = {x["kind"] for x in L.decide(pre[c["id"]][variant], P)}
        if c["family"] == "clean":
            fp.append(bool(f))
        elif c["family"] in TARGET.values():
            k = next(k for k, v in TARGET.items() if v == c["family"])
            tp[k].append(k in f)
    return sum(fp) / max(1, len(fp)), {k: sum(v) / len(v) for k, v in tp.items()}


GRID = {"kL": [4, 5, 6, 8, 10, 12], "kD": [4, 5, 6, 8, 10], "rD": [0.5, 0.6, 0.7, 0.8], "kE": [2.0, 2.5, 3.0, 4.0],
        "cE": [3, 4, 5, 6], "kQ": [0, 0.5, 1.0, 2.0]}


def tune(a):
    cases = [json.loads(l) for l in open(Path(a.dev) / "cases.jsonl", encoding="utf-8") if '"real"' not in l[:60]]
    cases = [c for c in cases if c["family"] != "real"]
    pre = {c["id"]: feats(c) for c in cases}
    res = {"split": "dev", "n_clean": sum(1 for c in cases if c["family"] == "clean"), "variants": {}}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for variant in ("raw", "daily"):
        rows = []
        for vals in itertools.product(*GRID.values()):
            P = dict(zip(GRID, vals))
            fp, tp = grid_eval(cases, pre, variant, P)
            rows.append({**P, "fp": round(fp, 3), **{f"tp_{k}": round(v, 3) for k, v in tp.items()}})
        (out / f"tune_grid_{variant}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        front = {}
        for b in (0.02, 0.05, 0.10, 0.15):
            ok = [r for r in rows if r["fp"] <= b]
            if ok:
                front[str(b)] = max(ok, key=lambda r: (sum(r[f"tp_{k}"] for k in TARGET), -r["fp"]))
        res["variants"][variant] = {"min_fp": min(r["fp"] for r in rows), "best_at_fp_budget": front}
    # chosen: daily variant at the 5% budget (else the smallest budget that has one)
    d = res["variants"]["daily"]["best_at_fp_budget"]
    pick = d.get("0.05") or next((d[k] for k in sorted(d, key=float)), None)
    res["best_params"] = {k: pick[k] for k in GRID} if pick else None
    res["chosen_variant"] = "daily"
    (out / "params.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


def evaluate(a):
    tuned = json.loads(Path(a.params).read_text())
    P = tuned["best_params"]
    Praw = tuned["variants"]["raw"]["best_at_fp_budget"]
    Praw = Praw.get("0.05") or Praw.get("0.10") or Praw.get("0.15")
    Praw = {k: Praw[k] for k in GRID} if Praw else P
    cases = [json.loads(l) for l in open(Path(a.test) / "cases.jsonl", encoding="utf-8")]
    out = {"params_daily": P, "params_raw": Praw, "per_family": {}}
    fams = ["clean", "step_old", "drift_long", "subthr_spikes", "real"]
    for f in fams:
        C = [c for c in cases if c["family"] == f]
        fr, fd, kinds = [], [], Counter()
        for c in C:
            pf = feats(c)
            r = L.decide(pf["raw"], Praw)
            d = L.decide(pf["daily"], P)
            fr.append(bool(r)); fd.append(bool(d))
            kinds.update(x["kind"] for x in d)
        out["per_family"][f] = {"raw_12h": W.rate(fr), "daily_baseline": W.rate(fd), "daily_kinds": kinds.most_common()}
    od = Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    (od / "evaluate_test.json").write_text(json.dumps(out, indent=1))
    t = ["| family (test months) | raw 12 h detectors | daily-baseline detectors |\n|---|---|---|\n"]
    for f in fams:
        e = out["per_family"][f]
        t.append(f"| {f} | {W.pct(e['raw_12h'])} | {W.pct(e['daily_baseline'])} |\n")
    (od / "evaluate_test.md").write_text("".join(t), encoding="utf-8")
    print("".join(t))
    print(json.dumps({f: out["per_family"][f]["daily_kinds"] for f in fams}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "tune", "evaluate"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--dev")
    ap.add_argument("--test")
    ap.add_argument("--params")
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--clean", type=int, default=40)
    ap.add_argument("--per", type=int, default=25)
    ap.add_argument("--real", type=int, default=40)
    a = ap.parse_args()
    {"build": build, "tune": tune, "evaluate": evaluate}[a.cmd](a)


if __name__ == "__main__":
    main()
