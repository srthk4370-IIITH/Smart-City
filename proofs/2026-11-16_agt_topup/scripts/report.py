"""report.py T PF: numbers of the 2026-11-16 agt_v3 laptop top-up -> PF/REPORT.md (+ PF/curve.png, PF/report_numbers.json).
Aggregates only (counts, scores): no real window leaves the laptop in these files."""
import json
import os
import sys
from pathlib import Path

T, PF = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt/kaggle")
import rows as RW  # noqa: E402


def j(p, d=None):
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return d


def score(p):
    try:
        s = [json.loads(l) for l in open(p)]
    except Exception:  # noqa: BLE001
        return None
    agg = {k: round(100 * sum(bool(x[k]) for x in s if x.get(k) is not None) / max(1, sum(x.get(k) is not None for x in s)), 1)
           for k in ("json", "status", "pattern", "cause", "dq")}
    return dict(score=round(RW.gen_score(s), 4), n=len(s), **agg)


dm, mm, pil, sel = j(T / "data/data_manifest.json", {}), j(T / "mix/mix_manifest.json", {}), j(T / "state/pilot.json", {}), j(T / "post/selection.json", {})
refs = {k: score(T / f"post/ref/{k}.jsonl") for k in ("val_b50", "val_s1750", "syn_s1750")}
gc, gs = j(PF / "gate_topup.json", {}), j(PF / "gate_s1750_subset.json", {})
# ---- owner 2026-11-16: explicit no-harm check vs snap_1750 (independence + synthetic slice) and the FINAL hand-off file
import subprocess  # noqa: E402
bst = (sel or {}).get("best_step")
nh = None
if bst is not None and gc:
    subprocess.run([sys.executable, str(PF / "scripts/noharm.py"), str(T / "gate/samples_cand"), str(T / "gate/samples_s1750"),
                    str(T / ("post/s%04d/syn.jsonl" % bst)), str(T / "post/ref/syn_s1750.jsonl"), str(PF / "noharm.json")])
    nh = j(PF / "noharm.json")
final_ok = bool(gc.get("verdict") == "PASS" and nh and nh.get("no_harm"))
FG = T / ("post/final_s%04d/agt3_final_s%04d_q4_0.gguf" % (bst, bst)) if bst is not None else None
if final_ok:
    open(T / "FINAL", "w", newline="\n").write("gguf=%s\nmd5=%s\nadapter=%s\nstep=%s\n" % (
        FG, open(str(FG) + ".md5").read().strip(), T / ("run/snap_%04d" % bst), bst))
L = [json.loads(l) for l in open(T / "run/losses.jsonl")] if (T / "run/losses.jsonl").exists() else []
nums = {"data": {k: dm.get(k) for k in ("pools", "drop", "kept_real", "real_train", "real_val", "val_groups", "hvac_rerender_unchecked",
                                        "real_train_by_status", "real_train_by_role", "real_val_by_status")},
        "mix": mm, "pilot": pil, "refs": refs, "selection": sel, "gate_cand": gc.get("verdict"), "gate_s1750": gs.get("verdict")}
json.dump(nums, open(PF / "report_numbers.json", "w", newline="\n"), indent=1)
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    if L:
        ax[0].plot([x["step"] for x in L], [x["loss"] for x in L], lw=0.6)
        ax[0].set(title="train loss (completion tokens)", xlabel="step")
    c = sel.get("curve", [])
    st = [0] + [d["step"] for d in c]
    for key, lab, r0 in (("val", "REAL VAL", refs["val_s1750"]), ("syn", "synthetic slice", refs["syn_s1750"])):
        ys = [r0["score"] if r0 else None] + [d[key]["score"] for d in c]
        ax[1].plot(st, ys, marker="o", label=lab + " score")
    if refs["val_b50"]:
        ax[1].axhline(refs["val_b50"]["score"], ls="--", c="gray", label="B50 on REAL VAL (v2 prompts)")
    ax[1].set(title="merged Q4_0 selection (step 0 = snap_1750)", xlabel="top-up step")
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(PF / "curve.png", dpi=110)
except Exception as e:  # noqa: BLE001
    print("plot skipped:", e)


def tbl(*gates):
    names = [g.get("candidate", "?") for g in gates]
    rows = ["| check | " + " | ".join(names) + " |", "|---|" + "---|" * len(gates)]
    by = [{c["check"]: c for c in g.get("checks", [])} for g in gates]
    for c in gates[0].get("checks", []):
        cells = []
        for b in by:
            x = b.get(c["check"])
            cells.append(("PASS " if x["pass"] else "**FAIL** ") + x["detail"][:110].replace("|", "/") if x else "-")
        rows.append("| " + c["check"] + " | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def f(d):
    return "-" if not d else "score %.4f, status %.1f, pattern %.1f, cause %.1f, dq %s (n %d)" % (d["score"], d["status"], d["pattern"], d["cause"], d.get("dq"), d["n"])


md = ["# agt_v3 laptop top-up on REAL windows (2026-11-16)", "",
      "Laptop only (RTX 4050, WSL); real per-sample data never left the laptop. Raw: `~/smartcity_runs/agt_topup/` (data, mix, run, post, gate).",
      "Scripts: `scripts/` (build_data.py, mix.py, chain.sh, gate_subset.py, report.py). Log: `STATUS.md`.", "",
      "## Data", "```", json.dumps(nums["data"], indent=1), "```",
      "## Mix", "```", json.dumps(mm, indent=1), "```", "## Pilot", "```", json.dumps(pil), "```",
      "## Selection curve (merged Q4_0, shared agt_v3 imatrix, host GPU, REAL VAL %s rows + synthetic slice %s rows)" % (mm.get("val_sel"), mm.get("syn_slice")), "",
      "| step | REAL VAL | synthetic slice |", "|---|---|---|",
      "| B50 (v2 prompts of the same REAL VAL windows) | %s | - |" % f(refs["val_b50"]),
      "| 0 = snap_1750 | %s | %s |" % (f(refs["val_s1750"]), f(refs["syn_s1750"]))]
for d in sel.get("curve", []):
    md.append("| %d | %s | %s |" % (d["step"], f({**d["val"], **{k: 100 * d["val"][k] for k in ("status", "pattern", "cause")}}),
                                    f({**d["syn"], **{k: 100 * d["syn"][k] for k in ("status", "pattern", "cause")}})))
md += ["", "Best step: **%s** (REAL VAL score %s; since best %s; stop %s). ![curve](curve.png)" % (sel.get("best_step"), sel.get("best"), sel.get("since_best"), sel.get("stop")), "",
       "## Small re-gate (subsets: dev_paired 600 pairs, E1 184, unseen_metric 150, unseen_layout 200, campus 200, calm_fault 150, rename 100 pairs)",
       "B50 and snap_1750 samples are the 2026-11-15 full-gate outputs sliced to the same rows (greedy, same GGUFs); only the top-up ran anew.", "",
       "Verdict: top-up **%s**, snap_1750 on the same subsets **%s**" % (gc.get("verdict"), gs.get("verdict")), "", tbl(gc, gs) if gc else "(gate not run)", "",
       "## No-harm check vs snap_1750 (paired exact sign test; harm = worse with p < 0.05)", "```", json.dumps(nh, indent=1) if nh else "(not run)", "```",
       "FINAL hand-off: %s" % (("written: " + str(T / "FINAL")) if final_ok else "NOT written (needs gate PASS and no harm)"), ""]
open(PF / "REPORT.md", "w", encoding="utf-8", newline="\n").write("\n".join(md) + "\n")
print("report written")
