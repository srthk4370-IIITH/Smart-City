"""Rebuild the exact placement_v2 series (same generator, read-only import of training code), verify the prompts are
byte-identical to proofs/2026-10-20_v2_post/device/placement_v2/prompts.jsonl, and compute deterministic detector
outputs per (case, d, n): v1 rule_pattern (the app's rules.go mirror), plus raw shape features on full-resolution data.
Writes a3_series_feats.json.  Run: PYTHONDONTWRITEBYTECODE=1 py -3 a3_rebuild_rules.py"""
import json, math, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAIN = Path(r"C:\Users\hp\Desktop\qidk\Code\smart-city-edge-agent\training")
SRC = HERE.parents[1] / "2026-10-20_v2_post" / "device" / "placement_v2"
sys.dont_write_bytecode = True
for p in (TRAIN / "v2" / "post", TRAIN / "v2", TRAIN, TRAIN / "window_study", TRAIN / "export"):
    sys.path.insert(0, str(p))
import common_v2 as C  # noqa
import features_v2 as V  # noqa
import window_study as W  # noqa
import placement_study as PS  # noqa
from window_study import F, G  # noqa
import generate_v2 as GV  # noqa


def main():
    V.NODE_LIMITS.update(json.loads((C.DATA / "node_limits.json").read_text()))
    cases = [json.loads(l) for l in open(SRC / "cases.jsonl", encoding="utf-8")]
    prompts = {(p["id"], p["d"], p["n"]): p["prompt"] for p in map(json.loads, open(SRC / "prompts.jsonl", encoding="utf-8"))}
    print("loading series", flush=True)
    series = G.load_series()
    need = {(c["role"], c["node"], c["metric"]) for c in cases}
    bases = {}
    for k in need:
        for end, xs in W.windows_full(series[k], stride=12):
            bases[(k, end)] = xs
    out, ok, bad = [], 0, 0
    for c in cases:
        k = (c["role"], c["node"], c["metric"])
        base = bases[(k, c["end_epoch"])]
        m = F.METRICS[(c["role"], c["metric"])]
        s0, _ = G.scale_of(c["role"], c["metric"], base[-48:])
        ds = [0] if c["pattern"] == "clean" else PS.DELAYS
        for d in ds:
            y = base if d == 0 else PS.inject_at(c["pattern"], base, s0, d, c["event"], m)
            for n in (48, 96, 144):
                pr = V.agent_prompt(c["role"], c["node"], G.describe(c["node"]), c["metric"], y, n, c["end_epoch"])[0]
                same = pr == prompts[(c["id"], d, n)]
                ok += same; bad += not same
                xs = y[-n:]
                rule = GV.rule_pattern_n(c["role"], c["metric"], xs, c["end_epoch"])
                rule48 = GV.rule_pattern_n(c["role"], c["metric"], y[-48:], c["end_epoch"])
                st = F.compute_stats(xs, m["dec"])
                # extra shape features on full-resolution data (candidate prompt hints)
                last36 = y[-36:]
                tail_frac = (y[-1] - y[-12]) / (max(xs) - min(xs) + 1e-9)       # share of range gained in the last hour
                out.append({"id": c["id"], "d": d, "n": n, "role": c["role"], "metric": c["metric"], "truth": "stable" if d == 0 else c["pattern"],
                            "rule": rule, "rule48": rule48, "prompt_same": same, "s0": s0,
                            "r2": st["r2"], "curv": st["curvature"], "slope": st["slope_per_h"], "noise": st["noise"],
                            "rnoise": F.robust_noise(xs), "flat": st["flat_run"], "zc": st["zero_cross"], "tail_frac": tail_frac})
    json.dump(out, open(HERE / "a3_series_feats.json", "w"))
    print(f"prompts byte-identical: {ok}, different: {bad}")


if __name__ == "__main__":
    main()
