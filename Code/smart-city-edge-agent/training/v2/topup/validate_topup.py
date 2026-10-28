"""Validate the v2 top-up data (gen_topup.py): every hard check of checks_v2 (json/schema/enums, evidence ids,
numbers, prompt rebuild, v1 equality at 48, leakage by month + held-out node, amplitude, shape), duplicates
against the original train/dev/test, token length, label distribution per bucket, and a dev-split check.
Writes <data>/validation.json + validation.md. Exit 1 if any hard check fails.

  python validate_topup.py --data ~/smartcity_runs/agents_v2_topup/data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
import checks_v2 as CK  # noqa: E402
import features_v2 as V  # noqa: E402
import generate_v2 as GV  # noqa: E402
import hvac_adapter as HA  # noqa: E402

SRC = GV.DATA / "sft_v2"


def month(e):
    return datetime.fromtimestamp(e, V.IST).month


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="/home/hp_srthk4370/models/llama-3.2-3b-instruct")
    ap.add_argument("--max-len", type=int, default=1280)
    a = ap.parse_args()
    d = Path(a.data).expanduser()
    HA.register()
    V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text()))
    man0 = json.loads((SRC / "manifest.json").read_text())
    heldout = man0["heldout_nodes"]
    rd = lambda p: [json.loads(l) for l in open(p, encoding="utf-8")]
    train, devt, dev = rd(d / "train.jsonl"), rd(d / "dev_target.jsonl"), rd(d / "dev.jsonl")
    test = rd(SRC / "test.jsonl")
    out = {"data": str(d), "counts": {"train": len(train), "dev_target": len(devt), "dev_original": len(dev)}}

    # 1. checks_v2 hard checks on every new-file row (train = replay + targeted; dev_target)
    res = {k: [0, 0] for k in CK.HARD}
    ex = defaultdict(list)
    flags = {"gen_tokens": [], "prompt_tokens": [], "obs_words": [], "gen_over_70": 0, "prompt_over_900": 0}
    # replay rows are original v2 rows built on Windows; a rebuild on Linux can differ in the last rounded digit
    # of one evidence value (float summation order). They are trained on exactly as stored, so a replay-row
    # rebuild difference is reported separately (soft); targeted rows must rebuild exactly.
    res_rp = {k: [0, 0] for k in CK.HARD}
    ex_rp = defaultdict(list)
    for r in train + devt:
        if r.get("topup_bucket") == "replay":
            CK.check_row(r, heldout, res_rp, flags, ex_rp)
        else:
            CK.check_row(r, heldout, res, flags, ex)
    replay_rebuild = {"pass": res_rp["rebuild"][0], "fail": res_rp["rebuild"][1], "examples": ex_rp.get("rebuild", [])[:8],
                      "note": "original rows (Windows build) re-rendered on Linux; last-digit rounding only, soft"}
    for k in CK.HARD:
        if k != "rebuild":
            res[k][0] += res_rp[k][0]
            res[k][1] += res_rp[k][1]
            ex[k] += ex_rp.get(k, [])
    # duplicates: within the top-up files, and targeted rows vs the original train/dev/test
    h = lambda r: hashlib.sha256(r["prompt"].encode()).hexdigest()
    test_h = {h(r) for r in test}
    dev_h = {h(r) for r in dev}
    seen = {}
    dup = []
    for r in train + devt:
        k = h(r)
        if k in seen and r.get("topup_bucket") != "replay":
            dup.append(f"{r['id']} == {seen[k]}")
        seen.setdefault(k, r["id"])
    in_test = [r["id"] for r in train + devt if h(r) in test_h]
    tr_in_dev = [r["id"] for r in train if h(r) in dev_h]
    devt_in_train = [r["id"] for r in devt if h(r) in {h(x) for x in train}]
    res["duplicates"] = [len(train) + len(devt) - len(dup), len(dup)]
    out["hard_checks"] = {k: {"pass": v[0], "fail": v[1], "examples": ex.get(k, [])[:8]} for k, v in res.items()}
    out["hard_checks"]["rebuild"]["scope"] = "targeted rows (train + dev_target)"
    out["replay_rebuild_soft"] = replay_rebuild
    out["overlap"] = {"rows_in_original_test": len(in_test), "train_rows_in_original_dev": len(tr_in_dev),
                      "dev_target_rows_in_train": len(devt_in_train), "dup_examples": dup[:8]}

    # 2. leakage summary (independent of check_row): months and held-out nodes
    def months(rows):
        c = Counter()
        for r in rows:
            c[f"{month(r['end_epoch'] - (r['hist_len'] - 1) * 300)}-{month(r['end_epoch'])}"] += 1
        return dict(sorted(c.items()))
    held = {(role, n) for role, ns in heldout.items() for n in ns}
    out["leakage"] = {
        "train_months_history_start-window_end": months(train),
        "dev_target_months": months(devt),
        "train_rows_outside_jan_aug": sum(1 for r in train if month(r["end_epoch"]) > 8 or month(r["end_epoch"] - (r["hist_len"] - 1) * 300) > 8),
        "dev_target_rows_outside_sep_oct": sum(1 for r in devt if month(r["end_epoch"]) not in (9, 10) or month(r["end_epoch"] - (r["hist_len"] - 1) * 300) not in (9, 10)),
        "rows_from_test_months_nov_dec": sum(1 for r in train + devt if month(r["end_epoch"]) >= 11),
        "rows_on_heldout_nodes": sum(1 for r in train + devt if (r["role"], r["node"]) in held),
        "split_field": dict(Counter(f"{r.get('topup_bucket') == 'replay' and 'replay' or 'targeted'}:{r['split']}" for r in train + devt))}

    # 3. token lengths (train + both dev sets) against the trainer's max_len
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(a.base, local_files_only=True)
        L = [len(tok(r["prompt"] + r["completion"], add_special_tokens=False)["input_ids"]) for r in train + devt]
        Ls = sorted(L)
        out["tokens"] = {"max": Ls[-1], "p95": Ls[int(0.95 * (len(Ls) - 1))], "mean": round(sum(L) / len(L), 1),
                         "over_max_len": sum(1 for x in L if x > a.max_len), "max_len": a.max_len}
    except Exception as e:  # noqa: BLE001
        out["tokens"] = {"error": repr(e)}

    # 4. label distribution
    tg = [r for r in train if r.get("topup_bucket") != "replay"]
    rp = [r for r in train if r.get("topup_bucket") == "replay"]
    per_bucket = defaultdict(lambda: defaultdict(Counter))
    for split, rows in (("train", tg), ("dev_target", devt)):
        for r in rows:
            b = per_bucket[f"{split}/{r['topup_bucket']}"]
            b["pattern"][r["pattern"]] += 1
            b["status"][r["status"]] += 1
            b["fault_kind"][str(r["fault_kind"])] += 1
            b["n"][r["n"]] += 1
            b["d"]["none" if r.get("d") is None else "3-12" if r["d"] <= 12 else "13-36" if r["d"] <= 36 else ">36"] += 1
            b["small_boundary"][str(r.get("small"))] += 1
    out["label_distribution"] = {
        "train_all_role_pattern": dict(sorted(Counter(f"{r['role']}/{r['pattern']}" for r in train).items())),
        "targeted_role_pattern": dict(sorted(Counter(f"{r['role']}/{r['pattern']}" for r in tg).items())),
        "replay_role": dict(Counter(r["role"] for r in rp)), "replay_family": dict(Counter(r["family"] for r in rp)),
        "targeted_status": dict(Counter(r["status"] for r in tg)), "replay_status": dict(Counter(r["status"] for r in rp)),
        "targeted_n": dict(sorted(Counter(r["n"] for r in tg).items())),
        "per_bucket": {k: {kk: dict(vv) for kk, vv in v.items()} for k, v in sorted(per_bucket.items())}}
    out["dev_split_check"] = {
        "dev_target_n": len(devt), "dev_target_roles": dict(Counter(r["role"] for r in devt)),
        "dev_target_buckets": dict(Counter(r["topup_bucket"] for r in devt)),
        "dev_target_all_split_dev": all(r["split"] == "dev" for r in devt),
        "dev_original_identical_to_source": hashlib.sha256((d / "dev.jsonl").read_bytes()).hexdigest()
        == hashlib.sha256((SRC / "dev.jsonl").read_bytes()).hexdigest(),
        "dev_target_nodes_seen_in_train_targeted": len({r["node"] for r in devt} & {r["node"] for r in tg}),
        "dev_target_distinct_nodes": len({r["node"] for r in devt})}
    out["soft_flags"] = {"gen_over_70": flags["gen_over_70"], "prompt_over_900": flags["prompt_over_900"],
                         "obs_words_max": max(flags["obs_words"]) if flags["obs_words"] else None}
    lk = out["leakage"]
    hard_ok = (all(v[1] == 0 for v in res.values()) and not in_test and not tr_in_dev and not devt_in_train
               and lk["train_rows_outside_jan_aug"] == 0 and lk["dev_target_rows_outside_sep_oct"] == 0
               and lk["rows_from_test_months_nov_dec"] == 0 and lk["rows_on_heldout_nodes"] == 0
               and out["tokens"].get("over_max_len", 1) == 0 and out["dev_split_check"]["dev_original_identical_to_source"])
    out["all_hard_pass"] = hard_ok
    (d / "validation.json").write_text(json.dumps(out, indent=1, default=str))
    md = ["# v2 top-up data validation\n", f"all hard checks pass: **{hard_ok}**\n\n", "| check | pass | fail |\n|---|---|---|\n"]
    md += [f"| {k} | {v['pass']} | {v['fail']} |\n" for k, v in out["hard_checks"].items()]
    md.append(f"\nreplay rows rebuild (soft): {json.dumps(replay_rebuild)}\n")
    md.append(f"\noverlap:{json.dumps(out['overlap'])}\n\nleakage: {json.dumps(lk)}\n\ntokens: {json.dumps(out['tokens'])}\n")
    md.append(f"\ndev split: {json.dumps(out['dev_split_check'])}\n\ncounts: {json.dumps(out['counts'])}\n")
    md.append("\n## targeted rows per bucket (train)\n| bucket | n | patterns | status |\n|---|---|---|---|\n")
    for k, v in out["label_distribution"]["per_bucket"].items():
        if k.startswith("train/"):
            md.append(f"| {k[6:]} | {sum(v['pattern'].values())} | {dict(v['pattern'])} | {dict(v['status'])} |\n")
    (d / "validation.md").write_text("".join(md), encoding="utf-8")
    print("".join(md))
    sys.exit(0 if hard_ok else 1)


if __name__ == "__main__":
    main()
