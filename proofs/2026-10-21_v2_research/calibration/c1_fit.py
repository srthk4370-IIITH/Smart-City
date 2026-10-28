"""D4 confidence recalibration: fit, validate, emit the Go table.

  py -3 c0_rows.py --placement ..\\..\\2026-10-21_v2_confirm\\placement_s24     (rows.json)
  py -3 c1_fit.py [--eval placement_s24] [--apply]

Target   P(pattern correct) of a v2 agent answer (exact match, common_v2 scoring).
Cells    (predicted pattern, onset-age bucket); onset age = features_v2.go onsetAge on the model's own onset
         (readings from onset to window end inside the window; -1 = none). Age buckets are the Go rows.
Estimate hierarchical binned shrinkage (empirical Bayes, beta prior):
             p_global = k/m over the fit set
             p_pat    = (k_pat + A * p_global) / (m_pat + A)
             p_cell   = (k_cell + A * p_pat)   / (m_cell + A)
         A picked by 5-fold event-grouped CV on the fit set (Brier). Wilson 95% CI reported per cell.
Variants compared by the same CV: +raw-confidence split (>=0.8), +window-length split (48 vs >48), and a
global isotonic map of the raw confidence (PAV), to show whether the extra dimension earns its place.
Fit      2026-10-20 device data (placement_v2 + host400 + test_all). Held out: --eval source (placement_s24).
Only answers that pass the app's policy gate on pattern (pattern in the v2 enum, confidence present) count:
the others are never shown with a confidence.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
GO = HERE.parents[2] / "Code" / "smart-city-edge-agent" / "app" / "backend" / "features_v2.go"
FIT_SRC = ("placement_v2", "host400", "test_all")
AGE_BUCKETS = [(-1, -1), (1, 6), (7, 12), (13, 24), (25, 48), (49, 96), (97, 144)]
A_GRID = (2, 5, 10, 20, 40, 80)


def bucket(age):
    for i, (lo, hi) in enumerate(AGE_BUCKETS):
        if lo <= age <= hi:
            return i
    return 0


def wilson(k, m, z=1.96):
    if m == 0:
        return (0.0, 1.0)
    p = k / m
    d = 1 + z * z / m
    c = (p + z * z / (2 * m)) / d
    h = z * math.sqrt(p * (1 - p) / m + z * z / (4 * m * m)) / d
    return (max(0.0, c - h), min(1.0, c + h))


# ------------------------------------------------------------------ models
def key_fn(variant):
    if variant == "pattern_age":
        return lambda r: (r["pred"], bucket(r["age"]))
    if variant == "pattern_age_conf":
        return lambda r: (r["pred"], bucket(r["age"]), r["conf"] >= 0.8)
    if variant == "pattern_age_n":
        return lambda r: (r["pred"], bucket(r["age"]), r["n"] > 48)
    if variant == "pattern_only":
        return lambda r: (r["pred"],)
    raise ValueError(variant)


CLEAN_W = 1.0  # weight of a clean (no-event) fit row; set by --clean-weight (see c3_clean.py / clean_study.md)


def wt(r):
    return CLEAN_W if r["clean"] else 1.0


def fit_shrunk(rows, variant, A):
    kf = key_fn(variant)
    m = sum(wt(r) for r in rows)
    pg = sum(wt(r) * r["ok_pattern"] for r in rows) / m
    pat = defaultdict(lambda: [0, 0])
    cell = defaultdict(lambda: [0, 0])
    for r in rows:
        x = wt(r)
        pat[r["pred"]][0] += x * r["ok_pattern"]; pat[r["pred"]][1] += x
        c = cell[kf(r)]; c[0] += x * r["ok_pattern"]; c[1] += x
    ppat = {p: (k + A * pg) / (n + A) for p, (k, n) in pat.items()}

    def predict(r):
        pp = ppat.get(r["pred"], pg)
        k, n = cell.get(kf(r), (0, 0))
        return (k + A * pp) / (n + A)
    return predict, {"p_global": pg, "pat": dict(pat), "cell": {str(k): v for k, v in cell.items()}, "ppat": ppat}


def pav(xs, ys):
    """isotonic (non-decreasing) regression of ys on xs; returns a step function."""
    pts = sorted(zip(xs, ys))
    blocks = []  # [sum, count, xmax]
    for x, y in pts:
        blocks.append([y, 1, x])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, c, xm = blocks.pop()
            blocks[-1][0] += s; blocks[-1][1] += c; blocks[-1][2] = xm
    steps = [(b[2], b[0] / b[1]) for b in blocks]

    def f(x):
        for xm, v in steps:
            if x <= xm:
                return v
        return steps[-1][1]
    return f


def fit_iso(rows):
    f = pav([r["conf"] for r in rows], [float(r["ok_pattern"]) for r in rows])
    return lambda r: f(r["conf"])


# ------------------------------------------------------------------ metrics
def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ys)


def logloss(ps, ys):
    e = 1e-4
    return -sum(y * math.log(min(1 - e, max(e, p))) + (1 - y) * math.log(min(1 - e, max(e, 1 - p))) for p, y in zip(ps, ys)) / len(ys)


def ece(ps, ys, nb=10):
    bins = defaultdict(list)
    for p, y in zip(ps, ys):
        bins[min(nb - 1, int(p * nb))].append((p, y))
    return sum(len(v) * abs(sum(p for p, _ in v) / len(v) - sum(y for _, y in v) / len(v)) for v in bins.values()) / len(ys)


def rel_bins(ps, ys, nb=10):
    bins = defaultdict(list)
    for p, y in zip(ps, ys):
        bins[min(nb - 1, int(p * nb))].append((p, y))
    return [(sum(p for p, _ in v) / len(v), sum(y for _, y in v) / len(v), len(v)) for _, v in sorted(bins.items())]


def auc(ps, ys):
    pos = [p for p, y in zip(ps, ys) if y]; neg = [p for p, y in zip(ps, ys) if not y]
    if not pos or not neg:
        return None
    from bisect import bisect_left, bisect_right
    neg.sort()
    s = sum(bisect_left(neg, p) + 0.5 * (bisect_right(neg, p) - bisect_left(neg, p)) for p in pos)
    return s / (len(pos) * len(neg))


def metrics(ps, ys):
    return {"n": len(ys), "acc": round(sum(ys) / len(ys), 4), "mean_conf": round(sum(ps) / len(ps), 4),
            "ece": round(ece(ps, ys), 4), "brier": round(brier(ps, ys), 4), "logloss": round(logloss(ps, ys), 4),
            "auc": round(auc(ps, ys), 4)}


def grouped_cv(rows, make, folds=5, seed=7):
    evs = sorted({r["event"] for r in rows})
    random.Random(seed).shuffle(evs)
    fold = {e: i % folds for i, e in enumerate(evs)}
    ps, ys, raw = [], [], []
    for k in range(folds):
        tr = [r for r in rows if fold[r["event"]] != k]
        te = [r for r in rows if fold[r["event"]] == k]
        f = make(tr)
        ps += [f(r) for r in te]; ys += [float(r["ok_pattern"]) for r in te]; raw += [r["conf"] for r in te]
    return ps, ys, raw


def boot_diff(rows, p_before, p_after, B=1000, seed=11):
    """event-grouped bootstrap of (after - before) for ECE and Brier."""
    by = defaultdict(list)
    for i, r in enumerate(rows):
        by[r["event"]].append(i)
    evs = list(by)
    rng = random.Random(seed)
    de, db = [], []
    for _ in range(B):
        idx = [i for e in (rng.choice(evs) for _ in evs) for i in by[e]]
        ys = [float(rows[i]["ok_pattern"]) for i in idx]
        a = [p_after[i] for i in idx]; b = [p_before[i] for i in idx]
        de.append(ece(a, ys) - ece(b, ys)); db.append(brier(a, ys) - brier(b, ys))
    q = lambda v: [round(sorted(v)[int(0.025 * B)], 4), round(sorted(v)[int(0.975 * B)], 4)]  # noqa: E731
    return {"d_ece_ci95": q(de), "d_brier_ci95": q(db)}


# ------------------------------------------------------------------ outputs
def svg_reliability(panels, path):
    W, H, M = 360, 360, 48
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W * len(panels)}" height="{H + 40}" font-family="sans-serif" font-size="11">',
           f'<rect width="100%" height="100%" fill="#fff"/>']
    for j, (title, series) in enumerate(panels):
        ox = j * W
        s = W - 2 * M
        X = lambda v: ox + M + v * s  # noqa: E731
        Y = lambda v: M + (1 - v) * s  # noqa: E731
        out.append(f'<text x="{ox + W / 2}" y="20" text-anchor="middle" font-size="13" font-weight="bold">{title}</text>')
        out.append(f'<rect x="{X(0)}" y="{Y(1)}" width="{s}" height="{s}" fill="none" stroke="#999"/>')
        out.append(f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(1)}" stroke="#bbb" stroke-dasharray="4 3"/>')
        for t in (0, .2, .4, .6, .8, 1):
            out.append(f'<text x="{X(t)}" y="{Y(0) + 14}" text-anchor="middle">{t:.1f}</text>')
            out.append(f'<text x="{X(0) - 6}" y="{Y(t) + 4}" text-anchor="end">{t:.1f}</text>')
        out.append(f'<text x="{X(.5)}" y="{Y(0) + 30}" text-anchor="middle">confidence shown</text>')
        out.append(f'<text x="{ox + 12}" y="{Y(.5)}" transform="rotate(-90 {ox + 12} {Y(.5)})" text-anchor="middle">observed pattern accuracy</text>')
        for li, (name, color, bins, m) in enumerate(series):
            pts = " ".join(f"{X(p):.1f},{Y(a):.1f}" for p, a, _ in bins)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5"/>')
            tot = sum(c for _, _, c in bins)
            for p, a, c in bins:
                out.append(f'<circle cx="{X(p):.1f}" cy="{Y(a):.1f}" r="{2 + 10 * math.sqrt(c / tot):.1f}" fill="{color}" fill-opacity="0.45" stroke="{color}"><title>{name}: shown {p:.2f}, observed {a:.2f}, n={c}</title></circle>')
            out.append(f'<text x="{X(0) + 8}" y="{Y(1) + 16 + 15 * li}" fill="{color}">{name}: ECE {m["ece"]:.3f}, Brier {m["brier"]:.3f}</text>')
    out.append(f'<text x="8" y="{H + 30}" fill="#555">10 equal-width confidence bins; dot area ~ rows in bin. Pattern correctness, exact match. D4 table = (pattern, onset-age) shrunk bins.</text>')
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def go_table(rows, A, pg, ppat, cell_counts, fit_desc):
    pats = sorted(ppat)
    lines = ["// BEGIN generated D4 table (proofs/2026-10-21_v2_research/calibration/c1_fit.py; do not edit by hand)",
             "// " + fit_desc,
             "// Rows: MinAge..MaxAge = readings from the model's onset to the window end (onsetAge; -1 = no onset in the",
             "// window); Conf = shrunk empirical P(pattern correct) of the device v2 agent in that cell. \"*\" = a pattern",
             "// without fit data (global rate per age). See calibration/calibration.md and reliability.svg.",
             "var ConfidenceRecalV2 = map[string][]ConfRecalRow{"]
    glob = defaultdict(lambda: [0, 0])
    for r in rows:
        g = glob[bucket(r["age"])]; g[0] += wt(r) * r["ok_pattern"]; g[1] += wt(r)
    for p in pats + ["*"]:
        items = []
        for bi, (lo, hi) in enumerate(AGE_BUCKETS):
            if p == "*":
                k, n = glob.get(bi, (0, 0)); v = (k + A * pg) / (n + A)
            else:
                k, n = cell_counts.get((p, bi), (0, 0)); v = (k + A * ppat[p]) / (n + A)
            items.append(f"{{{lo}, {hi}, {v:.2f}}}")
        w = max(len(q) for q in pats) + 3  # gofmt alignment of the map values
        lines.append("\t" + f'"{p}":'.ljust(w) + " {" + ", ".join(items) + "},")
    lines.append("}")
    lines.append("")
    lines.append("// END generated D4 table")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(HERE / "rows.json"))
    ap.add_argument("--eval", default="placement_s24")
    ap.add_argument("--apply", action="store_true", help="write the table into features_v2.go between the markers")
    ap.add_argument("--clean-weight", type=float, default=2.0,
                    help="weight of clean (no-event) fit rows; 2 = the clean/event trade-off chosen in clean_study.md")
    a = ap.parse_args()
    global CLEAN_W
    CLEAN_W = a.clean_weight
    R = json.load(open(a.rows, encoding="utf-8"))
    enum = {r["gold_pattern"] for r in R if r["gold_pattern"]} | {"stable"}
    usable = [r for r in R if r["conf"] is not None and r["pred"] in enum and 0 <= r["conf"] <= 1]
    fit = [r for r in usable if r["src"] in FIT_SRC]
    ev = [r for r in usable if r["src"] == a.eval]
    res = {"fit_sources": FIT_SRC, "eval_source": a.eval, "n_fit": len(fit), "n_eval": len(ev),
           "dropped_no_conf_or_offenum": len(R) - len(usable), "age_buckets": AGE_BUCKETS}

    # 1. CV on the fit set: variants x A
    cv = {}
    ys_raw = None
    for variant in ("pattern_only", "pattern_age", "pattern_age_conf", "pattern_age_n"):
        for A in A_GRID:
            ps, ys, raw = grouped_cv(fit, lambda tr, v=variant, A=A: fit_shrunk(tr, v, A)[0])
            cv[f"{variant}|A={A}"] = metrics(ps, ys)
            ys_raw = (ys, raw)
    ps, ys, raw = grouped_cv(fit, fit_iso)
    cv["isotonic_raw_conf"] = metrics(ps, ys)
    cv["raw_model_conf"] = metrics(ys_raw[1], ys_raw[0])
    res["cv_fit"] = cv
    bestA = min(A_GRID, key=lambda A: cv[f"pattern_age|A={A}"]["brier"])
    res["chosen"] = {"variant": "pattern_age", "A": bestA, "clean_weight": CLEAN_W}

    # 2. final fit on all fit rows, held-out eval
    pred, info = fit_shrunk(fit, "pattern_age", bestA)
    held = {}
    if ev:
        ys = [float(r["ok_pattern"]) for r in ev]
        before = [r["conf"] for r in ev]
        after = [pred(r) for r in ev]
        held["raw_model_conf"] = metrics(before, ys)
        held["d4_pattern_age"] = metrics(after, ys)
        for variant in ("pattern_age_conf", "pattern_age_n", "pattern_only"):
            f, _ = fit_shrunk(fit, variant, bestA)
            held[variant] = metrics([f(r) for r in ev], ys)
        fi = fit_iso(fit)
        held["isotonic_raw_conf"] = metrics([fi(r) for r in ev], ys)
        held["bootstrap_d4_minus_raw"] = boot_diff(ev, before, after)
        # the unweighted table (clean weight 1, A 5) shipped first, for comparison
        cw, CLEAN_W = CLEAN_W, 1.0
        f1, _ = fit_shrunk(fit, "pattern_age", 5)
        CLEAN_W = cw
        prev = [f1(r) for r in ev]
        held["prev_table_w1"] = metrics(prev, ys)
        evi = [i for i, r in enumerate(ev) if not r["clean"]]
        held["events_only"] = {"raw": metrics([before[i] for i in evi], [ys[i] for i in evi]),
                               "prev_table_w1": metrics([prev[i] for i in evi], [ys[i] for i in evi]),
                               "d4": metrics([after[i] for i in evi], [ys[i] for i in evi]),
                               "bootstrap_d4_minus_prev": boot_diff([ev[i] for i in evi], [prev[i] for i in evi], [after[i] for i in evi])}
        cli = [i for i, r in enumerate(ev) if r["clean"]]
        held["clean_only"] = {"raw": metrics([before[i] for i in cli], [ys[i] for i in cli]),
                              "prev_table_w1": metrics([prev[i] for i in cli], [ys[i] for i in cli]),
                              "d4": metrics([after[i] for i in cli], [ys[i] for i in cli])}
        fa = [i for i in cli if ev[i]["pred"] != "stable"]
        held["clean_false_alarm_calls"] = {"n": len(fa), **{k: {"mean": round(sum(v[i] for i in fa) / len(fa), 3), "share_ge_0.8": round(sum(v[i] >= 0.8 for i in fa) / len(fa), 3)}
                                                           for k, v in (("raw", before), ("prev_table_w1", prev), ("d4", after))}}
        # by stage proxy: early (n=48, d<=8), refinement (d>=18)
        for name, sel in (("events_d<=8", lambda r: not r["clean"] and r["d"] <= 8), ("events_d>=18", lambda r: not r["clean"] and r["d"] >= 18),
                          ("clean", lambda r: r["clean"])):
            ix = [i for i, r in enumerate(ev) if sel(r)]
            held[name] = {"raw": metrics([before[i] for i in ix], [ys[i] for i in ix]), "d4": metrics([after[i] for i in ix], [ys[i] for i in ix])}
        cvp, cvy, cvr = grouped_cv(fit, lambda tr: fit_shrunk(tr, "pattern_age", bestA)[0])
        svg_reliability([
            ("Fit set, 5-fold event-grouped CV", [("model confidence", "#c0392b", rel_bins(cvr, cvy), metrics(cvr, cvy)),
                                                   ("D4 recalibrated", "#2471a3", rel_bins(cvp, cvy), metrics(cvp, cvy))]),
            (f"Held out: {a.eval}", [("model confidence", "#c0392b", rel_bins(before, ys), held["raw_model_conf"]),
                                     ("D4 recalibrated", "#2471a3", rel_bins(after, ys), held["d4_pattern_age"])]),
        ], HERE / "reliability.svg")
    res["heldout"] = held

    # 3. table + cell report
    cells = defaultdict(lambda: [0, 0])   # raw counts (report)
    wcells = defaultdict(lambda: [0, 0])  # clean-weighted counts (table)
    for r in fit:
        c = cells[(r["pred"], bucket(r["age"]))]; c[0] += r["ok_pattern"]; c[1] += 1
        c = wcells[(r["pred"], bucket(r["age"]))]; c[0] += wt(r) * r["ok_pattern"]; c[1] += wt(r)
    evc = defaultdict(lambda: [0, 0])
    for r in ev:
        c = evc[(r["pred"], bucket(r["age"]))]; c[0] += r["ok_pattern"]; c[1] += 1
    md = ["| pattern | onset age (readings) | fit k/m | fit Wilson 95% | table conf | held-out k/m | held-out acc |", "|---|---|---|---|---|---|---|"]
    for p in sorted(info["ppat"]):
        for bi, (lo, hi) in enumerate(AGE_BUCKETS):
            k, m = cells.get((p, bi), (0, 0))
            ek, em = evc.get((p, bi), (0, 0))
            if m == 0 and em == 0:
                continue
            wk, wm = wcells.get((p, bi), (0, 0))
            v = (wk + bestA * info["ppat"][p]) / (wm + bestA)
            lo_, hi_ = wilson(k, m)
            md.append(f"| {p} | {'none' if lo < 0 else f'{lo}-{hi}'} | {k}/{m} | {lo_:.2f}-{hi_:.2f} | {v:.2f} | {ek}/{em} | {(ek / em if em else float('nan')):.2f} |")
    (HERE / "table_cells.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    desc = (f"Fit: {len(fit)} device answers (2026-10-20 placement_v2 + host400 + test_all), clean rows x{CLEAN_W:g}, shrinkage A={bestA}, global {info['p_global']:.3f}; "
            f"held out {a.eval} n={len(ev)}: ECE {held.get('raw_model_conf', {}).get('ece')} -> {held.get('d4_pattern_age', {}).get('ece')}, "
            f"Brier {held.get('raw_model_conf', {}).get('brier')} -> {held.get('d4_pattern_age', {}).get('brier')}.")
    gt = go_table(fit, bestA, info["p_global"], info["ppat"], wcells, desc)
    (HERE / "confidence_recal_v2.go.txt").write_text(gt + "\n", encoding="utf-8")
    if a.apply:
        src = GO.read_text(encoding="utf-8")
        s = src.index("// BEGIN generated D4 table"); e = src.index("// END generated D4 table") + len("// END generated D4 table")
        GO.write_text(src[:s] + gt + src[e:], encoding="utf-8", newline="\n")
        print("applied to", GO)
    # fixtures for the Go test (d4_calib_test.go): held-out rows -> the onset age Python computed and the
    # table value the Go side must return (parsed back from the generated table, i.e. the 2-dp numbers)
    tab = {}
    for line in gt.splitlines():
        m = re.match(r'\t"([^"]+)": +\{(.*)\},$', line)
        if m:
            tab[m[1]] = [tuple(float(x) for x in t.split(",")) for t in re.findall(r"\{([^{}]+)\}", m[2])]
    rng = random.Random(5)
    fx = []
    for r in rng.sample(ev, min(300, len(ev))) if ev else []:
        rows_ = tab.get(r["pred"], tab["*"])
        exp = next(c for lo, hi, c in rows_ if lo <= r["age"] <= hi)
        fx.append({"pattern": r["pred"], "onset": r["onset"], "n": r["n"], "end_hm": r["end_hm"], "age": r["age"], "conf": exp, "raw": r["conf"]})
    fxp = GO.parent / "testdata" / "d4_calib_fixtures.json"
    if a.apply:
        json.dump(fx, open(fxp, "w", encoding="utf-8", newline="\n"), indent=0)
    json.dump(res, open(HERE / "calibration_metrics.json", "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("n_fit", "n_eval", "chosen", "heldout")}, indent=1))
    print("CV:", json.dumps({k: (v["ece"], v["brier"], v["logloss"]) for k, v in cv.items()}, indent=0))


if __name__ == "__main__":
    main()
