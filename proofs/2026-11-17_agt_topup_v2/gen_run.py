"""gen_run.py: run the v2 generators in parallel (CPU, nice), token-filter every turn (prompt <= PROMPT_MAX = 904, completion <= 240), write shards.
usage: python3 gen_run.py --out DIR [--scale 1.0] [--procs 3] [--seed 1117] [--split train|dev] [--only fam,fam]
Plan (scale 1.0, units are ROWS, tool families are scenarios -> ~2.1 rows each): see PLAN below. Output DIR/new_full.jsonl (all keys: card, hist, meta ...)
and DIR/gen_report.json (units wanted/made/tries per family, drop reasons)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections import Counter, OrderedDict
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_v2 as G  # noqa: E402
import gen_tools as GT  # noqa: E402

PROMPT_MAX, COMP_MAX = 904, 240           # board: prompt + 240 new tokens + 136 headroom <= agent ctx 1280
TOK = os.path.expanduser(os.environ.get("BASE_TOK", "~/models/llama-3.2-3b-instruct/tokenizer.json"))
PLAN = OrderedDict([
    ("dyn", 800), ("hard_standby", 280), ("hard_leak", 280), ("hard_night", 240), ("hard_plateau", 300), ("hard_limits", 360),
    ("hard_ph", 180), ("weak", 560),
    ("tool_history", 250), ("tool_neighbors", 130), ("tool_card", 50), ("tool_card_neighbors", 35)])
TRIES = {"tool_history": 1500, "tool_card_neighbors": 150, "tool_neighbors": 120, "hard_ph": 120}   # max tries per wanted unit
_tk = None
MULT = json.loads(os.environ.get("FAM_MULT", "{}"))   # error-driven up-weighting (DATASET_V2B)


def ntok(text):
    global _tk
    if _tk is None:
        from tokenizers import Tokenizer
        _tk = Tokenizer.from_file(TOK)
    return len(_tk.encode(text, add_special_tokens=False).ids)


def unit_fn(fam):
    if fam.startswith("tool_"):
        return GT.SC[fam[5:]][0]
    return G.FAMS[fam]


def run_task(args):
    split, fam, k, count, seed, out = args
    path = Path(out) / "shards" / f"{split}__{fam}__{k:03d}.jsonl"
    if path.with_suffix(".done").exists():
        return str(path), "cached", 0, {}
    T = G.GA.Task(split, "ex_event", k, count, f"{seed}-v2")
    fn = unit_fn(fam)
    made, tries, drops = 0, 0, Counter()
    t0 = time.time()
    seen = set()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        while made < count and tries < count * TRIES.get(fam, 60):
            tries += 1
            try:
                r = fn(T)
            except Exception as e:  # noqa: BLE001
                drops["exc:" + repr(e)[:60]] += 1
                if sum(v for kk, v in drops.items() if kk.startswith("exc")) < 3:
                    traceback.print_exc()
                continue
            if not r:
                drops["none"] += 1
                continue
            rows = r[0] if isinstance(r, tuple) else [r]
            if any(x["id"] in seen for x in rows):
                drops["dup"] += 1
                continue
            bad = [x for x in rows if ntok(x["prompt"]) > PROMPT_MAX or ntok(x["completion"]) > COMP_MAX]
            if bad:
                drops["tokens"] += 1
                continue
            for x in rows:
                seen.add(x["id"])
                x["split_gen"] = split
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
            made += len(rows) if not fam.startswith("tool_") else 1   # tool families count scenarios
    path.with_suffix(".done").write_text(json.dumps({"made": made, "tries": tries, "drops": dict(drops.most_common(6)), "sec": round(time.time() - t0, 1)}))
    return str(path), made, tries, dict(drops)


def tasks(split, scale, seed, only, out):
    ts = []
    for fam, n in PLAN.items():
        if only and fam not in only:
            continue
        n = max(1, int(round(n * scale * MULT.get(fam, 1.0))))
        chunk = 40 if fam.startswith("tool_") else 100
        for k in range((n + chunk - 1) // chunk):
            ts.append((split, fam, k, min(chunk, n - k * chunk), seed, str(out)))
    return ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--seed", default="1117")
    ap.add_argument("--split", default="train")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "shards").mkdir(parents=True, exist_ok=True)
    ts = tasks(a.split, a.scale, a.seed, [x for x in a.only.split(",") if x], out)
    print(len(ts), "tasks", flush=True)
    t0 = time.time()
    rep = {}
    with Pool(a.procs) as pool:
        for i, (p, made, tries, drops) in enumerate(pool.imap_unordered(run_task, ts)):
            fam = Path(p).name.split("__")[1]
            d = rep.setdefault(fam, {"units": 0, "tries": 0, "drops": Counter()})
            if made != "cached":
                d["units"] += made
                d["tries"] += tries
                d["drops"].update(drops)
            print("[%d/%d] %s made=%s tries=%s t=%ds" % (i + 1, len(ts), Path(p).name, made, tries, time.time() - t0), flush=True)
    n = 0
    seen = set()
    with open(out / "new_full.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for p in sorted((out / "shards").glob("*.jsonl")):
            for l in open(p, encoding="utf-8"):
                if not l.strip():
                    continue
                r = json.loads(l)
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                f.write(l if l.endswith("\n") else l + "\n")
                n += 1
    for d in rep.values():
        d["drops"] = dict(d["drops"].most_common(6))
    json.dump({"plan": dict(PLAN), "scale": a.scale, "rows": n, "by_family": rep, "sec": round(time.time() - t0)},
              open(out / "gen_report.json", "w", newline="\n"), indent=1)
    print("rows", n, "sec", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
