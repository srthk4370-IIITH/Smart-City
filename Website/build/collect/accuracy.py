"""Accuracy datasets: v1 host eval, quantisation waterfall, device54 Genie vs htpd, test900 partial."""
from _lib import *

S = __file__
T = "accuracy"
RES = TRAIN / "results"
EV = RES / "agents_20261006_2101" / "eval.json"
DEV_G = RES / "device_eval_samples.jsonl"
DEV_GJ = RES / "device_eval.json"
FQ = RES / "fakequant_step0.jsonl"
HA = PROOFS / "2026-10-16_htpd_accuracy"
METRICS = [("pattern", "pattern"), ("status", "status"), ("likely_cause", "cause"),
           ("action", "action"), ("evidence_valid", "evidence valid"), ("json_valid", "valid JSON")]
ROLES = ["air_quality", "water", "power", "occupancy", "weather"]


def v1_host():
    ev = read_json(EV)
    tuned, base, rules = ev["tuned"], ev["base"], ev["rules_pattern_acc"]
    ser_t = [pt(lbl, **rate_from(tuned["ALL"][k], 150)) for k, lbl in METRICS]
    ser_b = [pt(lbl, **rate_from(base["ALL"][k], 150)) for k, lbl in METRICS]
    ser_r = [pt("pattern", **rate_from(rules["ALL"], 150))]
    write(T, "acc_v1_host_eval", "Fine-tuned vs base vs rules, 150 held-out Nov-Dec windows (laptop, 4-bit)",
          "fraction", [ser("fine-tuned Llama 3.2 3B", ser_t, "ours"), ser("base Llama 3.2 3B", ser_b),
                       ser("rules (Mode 1)", ser_r)],
          [EV, RES / "agents_20261006_2101/eval.md", hb_section("2.7")], S, n=150,
          chart={"type": "bar", "x": "metric", "y": "accuracy"},
          claim="Fine-tuning: pattern 94% vs 20% base and 68% rules",
          why="The base model invents formats and numbers; fine-tuning makes every answer usable.",
          notes="k reconstructed as round(rate*150). Status/cause/action labels are produced by the same teacher "
                "rules Mode 1 runs, so only the pattern comparison is independent (HANDBOOK 2.36). eval_agents.py kept "
                "aggregates only: no per-sample rows, so no McNemar for this table.")
    pts = {}
    for arm, src in (("tuned", tuned), ("base", base)):
        pts[arm] = [pt(r, **rate_from(src[r]["pattern"], 30)) for r in ROLES]
    pr = [pt(r, **rate_from(rules[r], 30), note=("circular: occupancy labels come from the rules" if r == "occupancy" else None)) for r in ROLES]
    write(T, "acc_v1_host_per_role", "Pattern accuracy per role (150 held-out windows, 30 per role)",
          "fraction", [ser("fine-tuned", pts["tuned"], "ours"), ser("base", pts["base"]), ser("rules (Mode 1)", pr)],
          [EV, hb_section("2.36")], S, n=30, chart={"type": "bar", "x": "role", "y": "pattern accuracy"},
          notes="Occupancy pattern labels come from occ_label, the same logic as the rules, so rules score 100% by construction.")
    # fair subset: continuous roles only
    cont = ["air_quality", "water", "power", "weather"]
    kt = sum(round(tuned[r]["pattern"] * 30) for r in cont)
    kr = sum(round(rules[r] * 30) for r in cont)
    write(T, "acc_v1_rules_vs_llm_fair", "Pattern accuracy on the 4 non-circular roles (air, water, power, weather)",
          "fraction", [ser("fine-tuned", [pt("pattern, 4 roles", **rate(kt, 120))], "ours"),
                       ser("rules (Mode 1)", [pt("pattern, 4 roles", **rate(kr, 120))])],
          [EV, hb_section("2.36")], S, n=120, chart={"type": "ciDot"},
          claim="Without the circular occupancy role: 92.5% vs 60.0%",
          notes="HANDBOOK 2.36 also quotes rules 68.6% recomputed on all 900 test windows (prose; per-sample file not saved).")
    tok = [pt(r, tuned[r]["mean_out_tokens"]) for r in ROLES + ["ALL"]]
    tokb = [pt(r, base[r]["mean_out_tokens"]) for r in ROLES + ["ALL"]]
    write(T, "acc_v1_output_tokens", "Mean answer length in tokens: fine-tuned vs base", "tokens",
          [ser("fine-tuned", tok, "ours"), ser("base", tokb)], [EV], S, n=150,
          chart={"type": "bar"}, claim="84 vs 199 tokens: shorter answers are faster answers",
          why="Decode is ~70% of a call, so every token saved is ~40-50 ms.")


def quant():
    steps = [
        ("fine-tuned, laptop NF4", "host", 0.94, 150, "ours"),
        ("first NPU export (w4a16, base ranges)", "QIDK", 0.543, 46, "alt"),
        ("+ MSE-clipped weight scales", "QIDK", 0.391, 46, "alt"),
        ("diagnostic: device int4 weights, fp activations", "host", 0.739, 46, "ref"),
        ("GPTQ int4, fp activations", "host", 0.891, 46, "ref"),
        ("GPTQ + base activation ranges", "QIDK", 0.674, 46, "alt"),
        ("GPTQ + Kaggle-recalibrated ranges", "QIDK", 0.609, 46, "alt"),
        ("GPTQ + recalibrated, BOS fixed", "QIDK", 0.826, 46, "alt"),
        ("GPTQ + published ranges, BOS fixed (live)", "QIDK", 0.826, 46, "ours"),
        ("same live model, 54 windows", "QIDK", 0.852, 54, "ours"),
    ]
    pts = [pt(name, **rate_from(r, n), where=w, step=i + 1, role=role) for i, (name, w, r, n, role) in enumerate(steps)]
    write(T, "acc_quant_waterfall", "Getting the fine-tune onto the NPU: pattern accuracy per export step",
          "fraction", [ser("pattern accuracy", pts, "ours")], [hb_section("2.7"), FQ, RES / "device_eval.md", ROOT / "ppt.md"],
          S, n=46, chart={"type": "waterfall", "x": "step", "y": "pattern accuracy"},
          claim="54% -> 85%: the biggest gain was a double-BOS prompt bug, not quantisation",
          why="Host accuracy does not transfer to the device automatically; every step was measured on the same windows.",
          notes="Same 46 held-out windows for steps 2-9; step 1 is the 150-window laptop eval, step 10 the 54-window device set. "
                "Five of these steps exist only as HANDBOOK prose (bundles overwritten); k = round(rate*n). Steps 4-5 come from "
                "fakequant_eval.py (fakequant_step0.jsonl).")
    rows = read_jsonl(FQ)
    seen = []
    p = []
    for r in rows:
        lbl = f'{r["mode"]} {r["ckpt"]}'
        if lbl in seen:
            lbl += " (repeat)"
        seen.append(lbl)
        p.append(pt(lbl, **rate_from(r["pattern"], r["n"]), status=r["status"], cause=r["likely_cause"]))
    write(T, "acc_fakequant_host", "Host fake-quant check: bf16 vs int4 (GPTQ merged) vs plain int4 (46 windows)", "fraction",
          [ser("pattern accuracy", p, "ours")], [FQ, hb_section("2.7")], S, n=46, chart={"type": "bar"},
          notes="bf16 ceiling 0.913; GPTQ int4 0.891; round-to-nearest int4 (device weights) 0.739.")


def _key(r):
    return (r["role"], json.dumps(r.get("_gold") or {"p": r.get("gold_pattern")}, sort_keys=True))


def device54():
    g = read_jsonl(DEV_G)
    h1 = read_jsonl(HA / "device54/samples.jsonl")
    h6 = read_jsonl(HA / "device54_v5pc/samples.jsonl")
    s1 = read_json(HA / "device54/summary.json")
    s6 = read_json(HA / "device54_v5pc/summary.json")
    gi = {_key(r): r for r in g}
    h1i = {_key(r): r for r in h1}
    keys = [_key(r) for r in h6]
    assert len(set(keys)) == 54 and set(keys) == set(gi), "device54 sets differ"
    mets = [("pattern", "pattern"), ("status", "status"), ("likely_cause", "cause"), ("action_derived", "action (derived)"),
            ("json", "valid JSON"), ("evidence", "evidence valid"), ("policy", "policy pass")]
    series = []
    for name, rows, role in (("Genie (QAIRT CLI/genied)", g, "alt"), ("htpd v1", h1, "alt"), ("htpd final (v5/v6 + prefix cache)", h6, "ours")):
        series.append(ser(name, [pt(lbl, **rate(sum(bool(r.get(m)) for r in rows), len(rows))) for m, lbl in mets], role))
    tests = {}
    for m, lbl in mets[:4]:
        a = [bool(gi[k].get(m)) for k in keys]
        b = [bool(r.get(m)) for r in h6]
        tests[lbl] = dict(mcnemar(a, b), a="Genie", b="htpd final")
        # htpd v1 and final were run by the same script in the same order (role + gold pattern match row by row)
        if all(x["role"] == y["role"] and x["gold_pattern"] == y["gold_pattern"] for x, y in zip(h1, h6)):
            c = [bool(r.get(m)) for r in h1]
            tests[lbl + " (v1 vs final)"] = dict(mcnemar(c, b), a="htpd v1", b="htpd final")
    write(T, "acc_device54_engines", "Same fine-tuned weights on the QIDK NPU: Genie vs htpd (54 held-out windows)", "fraction",
          series, [DEV_G, DEV_GJ, HA / "device54/samples.jsonl", HA / "device54_v5pc/samples.jsonl", HA / "device54/summary.json",
                   HA / "device54_v5pc/summary.json", hb_section("2.37")], S, n=54,
          chart={"type": "bar"}, claim="htpd is no worse: pattern 90.7% vs 85.2% on Genie (n = 54, p = 0.45)",
          why="A faster runtime is only acceptable if the answers do not get worse.",
          notes="Paired on identical windows (matched by role+gold label; each pair unique). n=54 (about 1 per class), so a few "
                "points are within noise: see paired tests (none significant). Wall time: htpd v1 136 s, final 78.6 s for all 54.",
          extra={"paired_tests": tests, "wall_s": {"htpd v1": s1["wall_s"], "htpd final": s6["wall_s"]}})
    pr = []
    for name, rows, role in (("Genie", g, "alt"), ("htpd v1", h1, "alt"), ("htpd final", h6, "ours")):
        pts = []
        for r_ in ROLES:
            sub = [r for r in rows if r["role"] == r_]
            pts.append(pt(r_, **rate(sum(bool(r.get("pattern")) for r in sub), len(sub))))
        pr.append(ser(name, pts, role))
    write(T, "acc_device54_per_role", "Device pattern accuracy per role (54 windows)", "fraction", pr,
          [DEV_G, HA / "device54/samples.jsonl", HA / "device54_v5pc/samples.jsonl"], S, n=12,
          chart={"type": "bar"}, notes="9-12 windows per role: per-role differences are within noise.")
    # action generated vs derived (Genie run)
    gen = [bool(r["action"]) for r in g]
    der = [bool(r["action_derived"]) for r in g]
    fixed = sum(1 for a, b in zip(gen, der) if b and not a)
    worse = sum(1 for a, b in zip(gen, der) if a and not b)
    write(T, "acc_action_derived", "Action generated by the model vs derived from (cause, status)", "fraction",
          [ser("generated by the model", [pt("action", **rate(sum(gen), 54))]),
           ser("derived by policy.go", [pt("action", **rate(sum(der), 54))], "ours")],
          [DEV_G, DEV_GJ, hb_section("2.8")], S, n=54, chart={"type": "ciDot"},
          claim="Deriving the action: 0.778 -> 0.815, 2 fixed, 0 made worse",
          extra={"paired": dict(mcnemar(gen, der), fixed=fixed, made_worse=worse)})
    dj = read_json(DEV_GJ)
    write(T, "acc_device_v1_validation", "On-device validation that switched the app to the fine-tune (2026-10-07)", "fraction",
          [ser("fine-tuned (n=20)", [pt("pattern", **rate_from(0.45, 20)), pt("policy pass", **rate_from(0.80, 20))], "ours"),
           ser("base (n=20)", [pt("pattern", **rate_from(0.20, 20)), pt("policy pass", **rate_from(0.20, 20))])],
          [hb_section("2.7"), hb_section("2.36")], S, n=20, chart={"type": "bar"},
          notes="First export (before GPTQ and the BOS fix). The base run was later overwritten, so these are HANDBOOK numbers "
                "without per-sample rows. Per call: tuned 4.9 s vs base 7.5 s. Current live device result: device_eval.json "
                f"pattern {dj['summary']['tuned']['pattern']}, validated={dj['validated']}.",
          extra={"latency_s": {"fine-tuned": 4.9, "base model": 7.5}})


def test900():
    rows = read_jsonl(HA / "test900/samples.jsonl")
    log = text(HA / "test900.log")
    mets = [("pattern", "pattern"), ("status", "status"), ("likely_cause", "cause"), ("json", "valid JSON"), ("policy", "policy pass")]
    n = len(rows)
    write(T, "acc_test900_partial", f"900-window device rerun: stopped after {n} windows (thermal stall at 91 C)", "fraction",
          [ser("htpd final, first %d of 900" % n, [pt(lbl, **rate(sum(bool(r.get(m)) for r in rows), n)) for m, lbl in mets], "ours")],
          [HA / "test900/samples.jsonl", HA / "test900.log", hb_section("2.37")], S, n=n, chart={"type": "ciDot"},
          notes="Incomplete: the run stopped on a one-off socket timeout (" + ("TimeoutError" if "TimeoutError" in log else "error") +
                ") at 91 C after 3 batches of 13. Shown only for completeness; wide CIs. The full 900-window rerun is still to do.")


def main():
    v1_host(); quant(); device54(); test900()


if __name__ == "__main__":
    main()
