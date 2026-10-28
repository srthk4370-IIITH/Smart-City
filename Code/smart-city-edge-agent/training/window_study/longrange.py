"""Long-range detectors: cheap CPU checks over the last 12 h of one sensor, for what the 4 h agent misses
(window study, HANDBOOK 2.38): a level shift that happened hours ago, a slow drift, and recurring small
excursions that never cross a limit. Mirrored exactly in app/backend/longrange.go (cross-checked by
longrange_test.go against fixtures written by `python longrange.py fixtures`).

  python longrange.py tune     --dev DIR --out DIR   # grid search on DEV-month cases only
  python longrange.py evaluate --test DIR --params P --out DIR   # once, on the test cases + agent outputs
  python longrange.py fixtures --out FILE
"""
import argparse
import itertools
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import window_study as W  # noqa: E402
from window_study import F  # noqa: E402

MIN_POINTS = 96  # at least 8 h of history, else no long-range verdict


def median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def noise_scale(role, metric, xs):
    """Robust 5-min noise (MAD of first differences), floored per metric like the rules' window scale."""
    m = F.METRICS[(role, metric)]
    d = [xs[i] - xs[i - 1] for i in range(1, len(xs))]
    md = median(d)
    mad = median([abs(v - md) for v in d])
    noise = 1.4826 * mad / math.sqrt(2)
    floor = m["floor"] if m["floor"] > 0 else max(0.03 * abs(median(xs)), 0.05)
    return max(noise, 0.5 * floor, 1e-6)


def linfit(xs):
    n = len(xs)
    mx = (n - 1) / 2
    my = sum(xs) / n
    sxx = sum((i - mx) ** 2 for i in range(n))
    sxy = sum((i - mx) * (x - my) for i, x in enumerate(xs))
    b = sxy / sxx
    ss = sum((x - my) ** 2 for x in xs)
    res = sum((x - (my + b * (i - mx))) ** 2 for i, x in enumerate(xs))
    return b, (1 - res / ss) if ss > 0 else 0.0


def stats(role, metric, xs):
    """Threshold-free statistics the detectors compare against P (computed once per window)."""
    s = noise_scale(role, metric, xs)
    ref = sorted(xs[:36])
    iqr = ref[27] - ref[9]  # spread of the first 3 h: how much this sensor normally moves (switching loads)
    n = len(xs)
    M = [median(xs[i:i + 6]) for i in range(n - 5)]  # rolling 30-min medians: robust to single spikes
    steep = max(abs(M[i + 6] - M[i]) for i in range(len(M) - 6))
    base, now = median(xs[:36]), median(xs[-12:])
    delta = now - base
    half = base + delta / 2
    k = next((i for i, v in enumerate(M) if (v - half) * delta > 0), 0)
    b, r2 = linfit(xs)
    total = b * (n - 1)
    res = [xs[i] - median(xs[max(0, i - 6):min(n, i + 7)]) for i in range(n)]
    res_abs = [abs(r) for r in res]
    return {"s": s, "iqr": iqr, "res_abs": res_abs, "n": n, "steep": steep, "delta": delta, "ago_pts": n - 1 - (k + 5), "total": total, "r2": r2}


def clusters(res_abs, thr, s):
    c, last, peak = 0, -10, 0.0
    for i, r in enumerate(res_abs):
        if r >= thr:
            if i - last > 2:
                c += 1
            last = i
            peak = max(peak, r / s)
    return c, peak


def decide(st, P):
    out = []
    s = max(st["s"], P.get("kQ", 0) * st["iqr"])
    delta, total, steep = st["delta"], st["total"], st["steep"]
    if abs(delta) >= P["kL"] * s and steep >= 0.5 * abs(delta):
        out.append({"kind": "level_shift", "delta": delta, "ago_pts": st["ago_pts"], "sigma": abs(delta) / s})
    if abs(total) >= P["kD"] * s and st["r2"] >= P["rD"] and steep < 0.5 * abs(total):
        out.append({"kind": "slow_drift", "delta": total, "hours": st["n"] * 5 / 60, "r2": st["r2"], "sigma": abs(total) / s})
    c, peak = clusters(st["res_abs"], P["kE"] * s, s)
    if c >= P["cE"]:
        out.append({"kind": "recurring_excursions", "count": c, "hours": st["n"] * 5 / 60, "peak_sigma": peak})
    return out


def detect(role, metric, xs, P):
    """Findings for one sensor; xs oldest first, 5-min samples, the last one = now. P = tuned thresholds."""
    if role == "occupancy" or len(xs) < MIN_POINTS:
        return []
    return decide(stats(role, metric, xs), P)


def describe(f, unit=""):
    u = f" {unit}" if unit else ""
    if f["kind"] == "level_shift":
        return f"12 h view: level shifted {f['delta']:+.3g}{u} about {f['ago_pts'] * 5 / 60:.1f} h ago and stayed ({f['sigma']:.1f}x noise)"
    if f["kind"] == "slow_drift":
        return f"12 h view: slow drift {f['delta']:+.3g}{u} over {f['hours']:.0f} h (r2 {f['r2']:.2f}, {f['sigma']:.1f}x noise)"
    return f"12 h view: {f['count']} separate excursions beyond normal noise in {f['hours']:.0f} h (peak {f['peak_sigma']:.1f}x), none crossing a limit"


# ------------------------------------------------------------------ tuning / evaluation
def load_cases(d):
    return [json.loads(l) for l in open(Path(d) / "cases.jsonl", encoding="utf-8")]


def piecewise_calm(c):
    """Clean by the TRAINING definition in every 4 h slice of the 12 h window (generate_dataset.is_calm).
    The study's 12 h calm filter used a non-robust noise estimate that real events inflate, so 12 h
    "clean" windows could hold a real tank refill or load step; this check is independent of the detectors."""
    xs = c["xs"]
    return (c["family"] == "clean" and c["truth"]["status"] == "normal" and len(xs) >= 144 and
            all(W.G.is_calm(c["role"], c["metric"], xs[i:i + 48]) for i in (0, 48, 96)))


FAMILY_OF = {"level_shift": "step_old", "slow_drift": "drift_long", "recurring_excursions": "subthr_spikes"}


def scores(cases, P, pre):
    res = {"fp_clean": [], "tp": {k: [] for k in FAMILY_OF}, "any_on_events": [], "per_family": {}}
    for c in cases:
        if c["family"] == "real":
            continue
        f = {x["kind"] for x in decide(pre[c["id"]], P)} if pre[c["id"]] else set()
        if piecewise_calm(c):
            res["fp_clean"].append(bool(f))
        for k, fam in FAMILY_OF.items():
            if c["family"] == fam:
                res["tp"][k].append(k in f)
        res["per_family"].setdefault(c["family"], []).append(bool(f))
    return res


def tune(a):
    cases = load_cases(a.dev)
    grid = {"kL": [4, 5, 6, 8, 10, 12], "kD": [4, 5, 6, 8, 10], "rD": [0.5, 0.6, 0.7, 0.8], "kE": [2.0, 2.5, 3.0, 4.0],
            "cE": [3, 4, 5, 6], "kQ": [0, 0.5, 1.0, 2.0]}
    best = None
    rows = []
    pre = {c["id"]: (stats(c["role"], c["metric"], c["xs"]) if c["role"] != "occupancy" and len(c["xs"]) >= MIN_POINTS else None)
           for c in cases if c["family"] != "real"}
    for vals in itertools.product(*grid.values()):
        P = dict(zip(grid, vals))
        r = scores(cases, P, pre)
        fp = sum(r["fp_clean"]) / len(r["fp_clean"])
        tp = {k: sum(v) / len(v) for k, v in r["tp"].items()}
        rows.append({**P, "fp_clean": round(fp, 3), **{f"tp_{k}": round(v, 3) for k, v in tp.items()}})
        # objective: mean TP over the three targets, subject to the false-alarm budget on clean dev windows
        if fp <= a.fp_budget:
            obj = sum(tp.values()) / 3
            if best is None or obj > best[0] or (obj == best[0] and fp < best[1]):
                best = (obj, fp, P, tp)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tune_grid.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    res = {"split": "dev", "fp_budget": a.fp_budget, "n_clean_piecewise_calm": sum(1 for c in cases if piecewise_calm(c)),
           "best_params": best[2] if best else None, "dev_fp_clean": best[1] if best else None,
           "dev_tp": best[3] if best else None, "grid_size": len(rows)}
    (out / "params.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


def evaluate(a):
    P = json.loads(Path(a.params).read_text())["best_params"]
    cases = {c["id"]: c for c in load_cases(a.test)}
    rows = [json.loads(l) for l in open(Path(a.test) / "samples.jsonl", encoding="utf-8")]
    agent = {}
    for r in rows:
        agent[(r["id"], r["n"])] = W.flagged(W.parse(r["text"]))
    det = {cid: {x["kind"] for x in detect(c["role"], c["metric"], c["xs"], P)} for cid, c in cases.items()}
    fams = sorted({c["family"] for c in cases.values() if c["family"] != "real"})
    out = {"params": P, "per_family": {}}
    for f in fams:
        ids = [i for i, c in cases.items() if c["family"] == f and (f != "clean" or piecewise_calm(c))]
        out["per_family"][f] = {
            "agent_4h": W.rate([agent[(i, 48)] for i in ids]),
            "detectors_12h": W.rate([bool(det[i]) for i in ids]),
            "agent_4h_or_detectors": W.rate([agent[(i, 48)] or bool(det[i]) for i in ids]),
            "agent_12h": W.rate([agent[(i, 144)] for i in ids]),
        }
    ev = [i for i, c in cases.items() if c["family"] not in ("clean", "real")]
    cl = [i for i, c in cases.items() if piecewise_calm(c)]
    for name, fn in [("agent_4h", lambda i: agent[(i, 48)]), ("detectors_12h", lambda i: bool(det[i])),
                     ("agent_4h_or_detectors", lambda i: agent[(i, 48)] or bool(det[i])), ("agent_12h", lambda i: agent[(i, 144)])]:
        out[name] = {"detection_all_events": W.rate([fn(i) for i in ev]), "false_alarm_clean": W.rate([fn(i) for i in cl])}
    real = [i for i, c in cases.items() if c["family"] == "real"]
    out["detectors_on_real_windows"] = W.rate([bool(det[i]) for i in real])
    od = Path(a.out)
    od.mkdir(parents=True, exist_ok=True)
    (od / "evaluate_test.json").write_text(json.dumps(out, indent=1))
    L = ["agent_4h", "detectors_12h", "agent_4h_or_detectors", "agent_12h"]
    t = ["| | " + " | ".join(L) + " |\n|---|" + "---|" * len(L) + "\n"]
    t.append("| detection, all events | " + " | ".join(W.pct(out[k]["detection_all_events"]) for k in L) + " |\n")
    t.append("| false alarms, clean | " + " | ".join(W.pct(out[k]["false_alarm_clean"]) for k in L) + " |\n")
    for f in fams:
        t.append(f"| {f} | " + " | ".join(W.pct(out["per_family"][f][k]) for k in L) + " |\n")
    (od / "evaluate_test.md").write_text("".join(t), encoding="utf-8")
    print("".join(t))
    print("detectors fire on real windows:", W.pct(out["detectors_on_real_windows"]))


def fixtures(a):
    """A few deterministic series + expected findings for the Go cross-check test."""
    import random
    rng = random.Random(5)
    P = json.loads(Path(a.params).read_text())["best_params"]
    fx = []
    for role, metric, base in [("air_quality", "co2", 600), ("power", "power_kw", 40), ("water", "level", 60)]:
        for kind, amp in (("calm", 0), ("shift", 0.08), ("shift", 0.3), ("shift", -0.5), ("drift", 0.1), ("drift", 0.4),
                          ("drift", -0.6), ("excursions", 0)):
            xs = [base + rng.gauss(0, base * 0.004) for _ in range(144)]
            if kind == "shift":
                xs = [v + (base * amp if i >= 80 else 0) for i, v in enumerate(xs)]
            elif kind == "drift":
                xs = [v + base * amp * i / 143 for i, v in enumerate(xs)]
            elif kind == "excursions":
                for p in (30, 70, 110, 140):
                    xs[p] += base * 0.03
            fx.append({"role": role, "metric": metric, "xs": xs, "findings": detect(role, metric, xs, P)})
    Path(a.out).write_text(json.dumps({"params": P, "cases": fx}, indent=1))
    print(f"{len(fx)} fixtures -> {a.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tune", "evaluate", "fixtures"])
    ap.add_argument("--dev")
    ap.add_argument("--test")
    ap.add_argument("--params")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fp-budget", type=float, default=0.05)
    a = ap.parse_args()
    {"tune": tune, "evaluate": evaluate, "fixtures": fixtures}[a.cmd](a)


if __name__ == "__main__":
    main()
