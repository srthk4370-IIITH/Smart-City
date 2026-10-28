"""D4 follow-up: does the table hold up on clean (no-event) windows?

  py -3 c3_clean.py      -> clean_study.md / clean_study.json

Clean windows are already in the fit set (placement_v2 clean at n = 48/96/144, host400/test_all negatives;
truth stable / teacher label, so a non-stable call on a clean window is a miss for its pattern x age cell).
They are ~13% of the fit rows, so the event rows dominate each cell. Variants tried here:
  * clean weight w: every clean fit row counts w times
  * +status: cells also split on the model's own status (normal vs alerting) -- the app knows it
Each variant is scored by event-grouped 5-fold CV on the fit set and on held-out placement_s24 (events, clean, all).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import c1_fit as C

HERE = Path(__file__).resolve().parent


def alerting(r):
    return r["pred_status"] not in ("normal",)


def keyf(variant):
    if variant == "pattern_age":
        return lambda r: (r["pred"], C.bucket(r["age"]))
    if variant == "pattern_age_status":
        return lambda r: (r["pred"], C.bucket(r["age"]), alerting(r))
    if variant == "pattern_status_age":  # status at the pattern level too (parent = pattern x status)
        return lambda r: (r["pred"], C.bucket(r["age"]), alerting(r))
    raise ValueError(variant)


def fit_w(rows, variant, A, w):
    kf = keyf(variant)
    wt = lambda r: w if r["clean"] else 1.0  # noqa: E731
    tot = sum(wt(r) for r in rows)
    pg = sum(wt(r) * r["ok_pattern"] for r in rows) / tot
    par = defaultdict(lambda: [0.0, 0.0]); cell = defaultdict(lambda: [0.0, 0.0])
    pkey = (lambda r: (r["pred"], alerting(r))) if variant == "pattern_status_age" else (lambda r: r["pred"])
    for r in rows:
        x = wt(r)
        p = par[pkey(r)]; p[0] += x * r["ok_pattern"]; p[1] += x
        c = cell[kf(r)]; c[0] += x * r["ok_pattern"]; c[1] += x
    ppar = {k: (s + A * pg) / (n + A) for k, (s, n) in par.items()}

    def predict(r):
        pp = ppar.get(pkey(r), pg)
        s, n = cell.get(kf(r), (0.0, 0.0))
        return (s + A * pp) / (n + A)
    return predict, (pg, ppar, dict(cell))


def score(ps, rows):
    ys = [float(r["ok_pattern"]) for r in rows]
    return C.metrics(ps, ys)


def main():
    R = json.load(open(HERE / "rows.json", encoding="utf-8"))
    enum = {r["gold_pattern"] for r in R if r["gold_pattern"]} | {"stable"}
    usable = [r for r in R if r["conf"] is not None and r["pred"] in enum and 0 <= r["conf"] <= 1]
    fit = [r for r in usable if r["src"] in C.FIT_SRC]
    ev = [r for r in usable if r["src"] == "placement_s24"]
    parts = {"all": ev, "events": [r for r in ev if not r["clean"]], "clean": [r for r in ev if r["clean"]]}
    out = {"n_fit": len(fit), "n_fit_clean": sum(r["clean"] for r in fit), "heldout_n": {k: len(v) for k, v in parts.items()}}
    res = {}
    res["raw model confidence"] = {k: score([r["conf"] for r in v], v) for k, v in parts.items()}
    for variant in ("pattern_age", "pattern_age_status", "pattern_status_age"):
        for w in (1, 2, 4, 8):
            for A in (5, 10):
                f, _ = fit_w(fit, variant, A, w)
                name = f"{variant} w={w} A={A}"
                res[name] = {k: score([f(r) for r in v], v) for k, v in parts.items()}
                cps, cys, _ = C.grouped_cv(fit, lambda tr, v=variant, A=A, w=w: fit_w(tr, v, A, w)[0])
                res[name]["cv_fit"] = C.metrics(cps, cys)
    out["results"] = res
    json.dump(out, open(HERE / "clean_study.json", "w"), indent=1)
    md = ["# D4 clean-window study (held out: placement_s24)", "",
          f"fit rows {out['n_fit']} (clean {out['n_fit_clean']}); held out {out['heldout_n']}", "",
          "| variant | all ECE | all Brier | events ECE | events Brier | clean ECE | clean Brier | clean AUC | CV Brier |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, m in res.items():
        md.append(f"| {name} | {m['all']['ece']:.3f} | {m['all']['brier']:.3f} | {m['events']['ece']:.3f} | {m['events']['brier']:.3f} | "
                  f"{m['clean']['ece']:.3f} | {m['clean']['brier']:.3f} | {m['clean']['auc'] if m['clean']['auc'] is not None else '-'} | "
                  f"{m.get('cv_fit', {}).get('brier', float('nan')):.3f} |")
    (HERE / "clean_study.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
