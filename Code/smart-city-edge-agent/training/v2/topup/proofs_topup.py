"""Collect the v2 top-up evidence into proofs/2026-10-21_v2_topup: data manifest + validation, training plan,
baseline, every dev evaluation (original + targeted), train-loss log, chosen step, GGUF manifest + md5, and an
SVG of the loss curves (no plotting library needed). Safe to run at any time (copies what exists).

  python proofs_topup.py [--run ~/smartcity_runs/agents_v2_topup]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROOF = HERE.parents[4] / "proofs" / "2026-10-21_v2_topup"


def svg_curves(evals, train_pts, base, path):
    W, H, P = 900, 520, 60
    series = [("original dev (200)", "#1f77b4", [(e["step"], e["eval_orig_loss"]) for e in evals if "eval_orig_loss" in e]),
              ("targeted dev (160)", "#d62728", [(e["step"], e["eval_target_loss"]) for e in evals if "eval_target_loss" in e]),
              ("train loss (per 5 steps)", "#999999", train_pts)]
    pts = [p for _, _, s in series for p in s]
    if not pts:
        return
    xmax = max(10, max(p[0] for p in pts))
    ys = [p[1] for p in pts]
    ymin, ymax = min(ys) * 0.95, max(ys) * 1.05
    X = lambda x: P + (W - 2 * P) * x / xmax
    Y = lambda y: H - P - (H - 2 * P) * (y - ymin) / (ymax - ymin or 1)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif" font-size="12">',
         f'<rect width="{W}" height="{H}" fill="white"/>',
         f'<line x1="{P}" y1="{H - P}" x2="{W - P}" y2="{H - P}" stroke="black"/><line x1="{P}" y1="{P}" x2="{P}" y2="{H - P}" stroke="black"/>',
         f'<text x="{W / 2}" y="{H - 20}" text-anchor="middle">top-up optimizer step (0 = v2 adapter step 4494)</text>',
         f'<text x="{W / 2}" y="25" text-anchor="middle" font-size="14">v2 top-up: dev loss (original vs targeted) and train loss</text>']
    for i in range(6):
        y = ymin + (ymax - ymin) * i / 5
        o.append(f'<text x="{P - 5}" y="{Y(y) + 4}" text-anchor="end">{y:.4f}</text>'
                 f'<line x1="{P}" y1="{Y(y)}" x2="{W - P}" y2="{Y(y)}" stroke="#eee"/>')
    for i in range(0, xmax + 1, max(25, (xmax // 8) // 25 * 25 or 25)):
        o.append(f'<text x="{X(i)}" y="{H - P + 16}" text-anchor="middle">{i}</text>')
    if base:
        for k, c in (("eval_orig_loss", "#1f77b4"), ("eval_target_loss", "#d62728")):
            o.append(f'<line x1="{P}" y1="{Y(base[k])}" x2="{W - P}" y2="{Y(base[k])}" stroke="{c}" stroke-dasharray="4 4" opacity="0.6"/>')
        o.append(f'<line x1="{P}" y1="{Y(base["eval_orig_loss"] * 1.03)}" x2="{W - P}" y2="{Y(base["eval_orig_loss"] * 1.03)}" stroke="orange" stroke-dasharray="2 6"/>'
                 f'<text x="{W - P}" y="{Y(base["eval_orig_loss"] * 1.03) - 4}" text-anchor="end" fill="orange">forgetting limit (+3% orig)</text>')
    for li, (name, c, s) in enumerate(series):
        if s:
            o.append(f'<polyline fill="none" stroke="{c}" stroke-width="2" points="{" ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in s)}"/>')
            o += [f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="{c}"/>' for x, y in s if li < 2]
        o.append(f'<rect x="{W - P - 200}" y="{P + 18 * li}" width="12" height="12" fill="{c}"/><text x="{W - P - 182}" y="{P + 10 + 18 * li}">{name}</text>')
    o.append("</svg>")
    Path(path).write_text("\n".join(o))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=str(Path.home() / "smartcity_runs" / "agents_v2_topup"))
    a = ap.parse_args()
    run = Path(a.run)
    global PROOF
    if run.name != "agents_v2_topup":
        PROOF = PROOF / run.name
    PROOF.mkdir(parents=True, exist_ok=True)
    for sub in ("data", "train", "gguf"):
        (PROOF / sub).mkdir(exist_ok=True)
    cp = lambda src, dst: shutil.copy2(src, dst) if Path(src).exists() else None
    for f in ("manifest.json", "validation.json", "validation.md", "gen.log"):
        cp(run / "data" / f, PROOF / "data" / f)
    for f in ("plan.json", "baseline.json", "evals.jsonl", "choice.json", "train.log", "session_status.json",
              "FORGETTING.json", "session.log", "evals_offline.jsonl", "train_args.txt", "init_choice.json"):
        cp(run / f, PROOF / "train" / f)
    for f in ["gguf_manifest.json", "imatrix_info.json", "q4_0.log"] + [p.name for p in (run / "post" / "gguf").glob("*.md5")]:
        cp(run / "post" / "gguf" / f, PROOF / "gguf" / f)
    for f in ("post_topup.log", "STATUS"):
        cp(run / "post" / f, PROOF / "gguf" / f)
    cp(run / "merged_v2t" / "merge_check.json", PROOF / "gguf" / "merge_check.json")
    # data stats (small, readable)
    vp = run / "data" / "validation.json"
    if vp.exists():
        v = json.loads(vp.read_text())
        m = json.loads((run / "data" / "manifest.json").read_text())
        stats = {"counts": v["counts"], "train_mix": m["train_mix"], "all_hard_pass": v["all_hard_pass"],
                 "leakage": v["leakage"], "overlap": v["overlap"], "tokens": v["tokens"], "dev_split_check": v["dev_split_check"],
                 "targeted_role_pattern": v["label_distribution"]["targeted_role_pattern"],
                 "targeted_status": v["label_distribution"]["targeted_status"]}
        (PROOF / "data" / "data_stats.json").write_text(json.dumps(stats, indent=1))
    # curves
    evals = [json.loads(l) for l in open(run / "evals.jsonl")] if (run / "evals.jsonl").exists() else []
    evals.sort(key=lambda e: e["step"])
    base = json.loads((run / "baseline.json").read_text()) if (run / "baseline.json").exists() else None
    train_pts, ga, ms, ep = [], 16, 403, 1.0
    if (run / "plan.json").exists():
        pl = json.loads((run / "plan.json").read_text())
        ga, ms, ep = pl.get("grad_accum", 16), pl["max_steps"], pl.get("epochs", 1.0)
    if (run / "train.log").exists():
        for l in open(run / "train.log", encoding="utf-8"):
            mm = re.search(r'metrics (\{.*"loss".*\})', l)
            if mm:
                d = json.loads(mm.group(1))
                if "loss" in d:
                    step = int(round(d["epoch"] * ms / ep))
                    train_pts.append((step, d["loss"] / ga))  # the logged loss is summed over grad-accum
    # a resumed session re-logs some steps: keep the last value per step
    tp = {}
    for s, y in train_pts:
        tp[s] = y
    train_pts = sorted(tp.items())
    if evals:
        rows = ["| step | original dev loss | vs baseline | targeted dev loss | vs baseline |", "|---|---|---|---|---|"]
        for e in evals:
            o, t = e.get("eval_orig_loss"), e.get("eval_target_loss")
            ro = f"{(o / base['eval_orig_loss'] - 1) * 100:+.2f}%" if base and o else ""
            rt = f"{(t / base['eval_target_loss'] - 1) * 100:+.2f}%" if base and t else ""
            rows.append(f"| {e['step']} | {o} | {ro} | {t} | {rt} |")
        (PROOF / "train" / "dev_curves.md").write_text("\n".join(rows) + "\n")
        svg_curves(evals, train_pts, base, PROOF / "train" / "loss_curves.svg")
    files = {}
    for d, _, fs in os.walk(PROOF):
        for f in fs:
            if f == "manifest.json" and Path(d) == PROOF:
                continue
            p = Path(d) / f
            files[str(p.relative_to(PROOF)).replace(os.sep, "/")] = {"bytes": p.stat().st_size,
                                                                     "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}
    json.dump({"what": "v2 top-up LoRA (targeted weak cases + replay): data, validation, dev curves, chosen step, GGUF",
               "run_dir": str(run), "updated": datetime.datetime.now().isoformat(timespec="seconds"), "files": files},
              open(PROOF / "manifest.json", "w"), indent=1)
    print(f"proofs updated: {PROOF} ({len(files)} files)")


if __name__ == "__main__":
    main()
