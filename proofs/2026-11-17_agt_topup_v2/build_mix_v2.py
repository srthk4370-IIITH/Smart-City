"""build_mix_v2.py [--new=DIR/new_full.jsonl] [--dev=DIR/dev_full.jsonl] [--out=RUNDIR] [--pf=PROOFDIR] [--replay-frac=0.6]
The agt_v3 top-up v2 mix (LAPTOP, CPU, deterministic, seed 1117).
 NEW   rows of gen_run.py (synthetic): dynamic windows, hard cases, weak roles, tool-protocol turns.
 REPLAY rows of the v1 top-up mix (real 12 h windows + synthetic; ~/smartcity_runs/agt_topup_k/mixdata/train.jsonl) that fit the board context
        (prompt <= 904 tokens, completion <= 240): stratified by role x status x real/synthetic, weak v1 classes x1.5, so replay = REPLAY_FRAC of the mix.
Writes RUN/mixdata/{train,gendev}.jsonl (the upload; gendev = the v1 gen-dev, identical), RUN/local/* (never uploaded: v1 val_sel / syn_slice /
unseen100 + tool_t1 / tool_t2 / hard_val from the DEV split), counts-only mix_manifest.json and the md5-pinned REAL_APPROVED.json."""
import collections
import hashlib
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
args = {a.split("=")[0]: a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}
HOME = Path.home()
RUN = Path(args.get("--out", HOME / "smartcity_runs/agt_topup_k2"))
NEW = Path(args.get("--new", RUN / "gen/new_full.jsonl"))
DEV = Path(args.get("--dev", RUN / "gen_dev/new_full.jsonl"))
PF = Path(args.get("--pf", HERE))
V1 = Path(args.get("--v1", HOME / "smartcity_runs/agt_topup_k"))
RF = float(args.get("--replay-frac", 0.6))
LIMIT = int(args.get("--limit", 0))        # dry run: keep only LIMIT new rows (replay scaled with it)
PROMPT_MAX, COMP_MAX = 904, 240
rng = random.Random(1117)
KEEP = ("id", "prompt", "completion", "gold", "family", "role", "stage", "slices", "synthetic", "source", "turn")
WEAK_ROLE = {"power": 1.5, "water": 1.4}
WEAK_FAM = {"real_fault": 1.5, "real_real_longrange": 1.5, "real_water_fill": 1.3, "real_zero_stop": 1.5}


def rd(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def wr(p, rows):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def status_of(r):
    g = r.get("gold")
    return g.get("status", g.get("tool", "?")) if isinstance(g, dict) else "?"


def alloc(rows, k, key, weight):
    by = collections.defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    for s in sorted(by, key=str):
        rng.shuffle(by[s])
    k = min(k, len(rows))
    cap = {s: len(v) for s, v in by.items()}
    w = {s: len(v) * weight(s) for s, v in by.items()}
    q, free, left = {}, set(by), k
    while free and left > 0:
        tw = sum(w[s] for s in free)
        over = [s for s in free if left * w[s] / tw >= cap[s]]
        if not over:
            raw = {s: left * w[s] / tw for s in free}
            fl = {s: int(raw[s]) for s in free}
            for s in sorted(free, key=lambda s: (-(raw[s] - fl[s]), str(s)))[:left - sum(fl.values())]:
                fl[s] += 1
            q.update(fl)
            break
        for s in sorted(over, key=str):
            q[s] = cap[s]
            left -= cap[s]
            free.discard(s)
    out = []
    for s in sorted(by, key=str):
        out += by[s][:q.get(s, 0)]
    rng.shuffle(out)
    return out


def main():
    from tokenizers import Tokenizer
    tk = Tokenizer.from_file(os.path.expanduser("~/models/llama-3.2-3b-instruct/tokenizer.json"))
    nt = lambda t: len(tk.encode(t, add_special_tokens=False).ids)  # noqa: E731
    new = rd(NEW)
    if LIMIT:
        rng.shuffle(new)
        new = new[:LIMIT]
    v1 = rd(V1 / "mixdata/train.jsonl")
    elig = [r for r in v1 if nt(r["prompt"]) <= PROMPT_MAX and nt(r["completion"]) <= COMP_MAX]
    n_rep = round(len(new) * RF / (1 - RF))
    rep = alloc(elig, n_rep, lambda r: (r["synthetic"] is False, r["role"], status_of(r), r["family"] if r["family"] in WEAK_FAM else "-"),
                lambda s: WEAK_ROLE.get(s[1], 1.0) * WEAK_FAM.get(s[3], 1.0))
    mix = [{k: r.get(k) for k in KEEP if k in r} for r in new + rep]
    for r in mix:
        if r.get("turn") is None:
            r.pop("turn", None)
    rng.shuffle(mix)
    assert len({r["id"] for r in mix}) == len(mix), "duplicate ids"
    # local-only sets
    val = rd(V1 / "local/val_sel.jsonl")
    vids = {r["id"] for r in val}
    assert not (vids & {r["id"] for r in mix}), "train overlaps REAL VAL (id)"
    dev = rd(DEV) if DEV.exists() else []
    t1 = [r for r in dev if r.get("turn") == "call"]
    t2 = [r for r in dev if r.get("turn") == "final"]
    direct = [r for r in dev if r["family"].startswith("dyn_") and r["n"] in (18, 36)][:max(20, len(t1) // 2)]
    hard = [r for r in dev if r["family"].startswith(("hard_", "weak_"))]
    kk = ("id", "prompt", "completion", "gold", "family", "role", "stage", "slices", "turn", "tool_kind", "synthetic", "source")
    sl = lambda rows: [{k: r.get(k) for k in kk if k in r} for r in rows]  # noqa: E731
    hold = {hashlib.md5(r["prompt"].encode()).hexdigest() for r in dev}
    assert not (hold & {hashlib.md5(r["prompt"].encode()).hexdigest() for r in mix}), "dev eval slice prompts are in train"
    RUN.mkdir(parents=True, exist_ok=True)
    wr(RUN / "mixdata/train.jsonl", mix)
    wr(RUN / "mixdata/gendev.jsonl", rd(V1 / "mixdata/gendev.jsonl"))
    for n in ("val_sel", "syn_slice", "unseen100"):
        wr(RUN / ("local/%s.jsonl" % n), rd(V1 / ("local/%s.jsonl" % n)))
    wr(RUN / "local/tool_t1.jsonl", sl(t1 + [dict(r, turn="direct") for r in direct]))
    wr(RUN / "local/tool_t2.jsonl", sl(t2))
    wr(RUN / "local/hard_val.jsonl", sl(hard))
    cnt = lambda rows, f: dict(sorted(((str(k), v) for k, v in collections.Counter(f(r) for r in rows).items())))  # noqa: E731
    real = [r for r in mix if r.get("synthetic") is False]
    isnew = {r["id"] for r in new}
    man = {"n_total": len(mix), "new": len(new), "replay": len(rep), "replay_frac": round(len(rep) / len(mix), 4), "real_replay": len(real),
           "steps_1_pass": -(-len(mix) // 32), "v1_rows": len(v1), "v1_eligible_le904": len(elig),
           "v1_dropped_over_ctx": {"real": sum(r["synthetic"] is False for r in v1) - sum(r["synthetic"] is False for r in elig),
                                   "synthetic": sum(r["synthetic"] is not False for r in v1) - sum(r["synthetic"] is not False for r in elig)},
           "new_by_family": cnt(new, lambda r: r["family"]), "new_by_window": cnt(new, lambda r: r.get("stage")),
           "new_by_turn": cnt(new, lambda r: r.get("turn", "-")), "tool_share_of_new": round(sum(1 for r in new if r.get("turn")) / max(1, len(new)), 4),
           "tool_by_kind": cnt([r for r in new if r.get("turn")], lambda r: (r.get("tool_kind"), r["turn"])),
           "replay_by_role": cnt(rep, lambda r: r["role"]), "replay_by_status": cnt(rep, status_of),
           "replay_real_by_family": cnt([r for r in rep if r.get("synthetic") is False], lambda r: r["family"]),
           "mix_by_status": cnt([r for r in mix if r["id"] in isnew or True], status_of),
           "local": {"val_sel": len(val), "tool_t1": len(t1) + len(direct), "tool_t2": len(t2), "hard_val": len(hard)},
           "md5": {"train": md5(RUN / "mixdata/train.jsonl"), "gendev": md5(RUN / "mixdata/gendev.jsonl")}}
    PF.mkdir(parents=True, exist_ok=True)
    json.dump(man, open(PF / "mix_manifest.json", "w", newline="\n"), indent=1)
    gen = rd(RUN / "mixdata/gendev.jsonl")
    json.dump({"dataset_slug": "agt3-topup2-data", "private": True, "scope": "THIS dataset only: train.jsonl + gendev.jsonl pinned by md5",
               "approval": "owner approved real windows on Kaggle as a PRIVATE dataset for the agt_v3 top-up (2026-11-16) and the automated top-up v2 "
                           "(2026-11-17, same exception, replay of the v1 real rows only; logged in AGENT_REGISTRY.md)",
               "allowed_sources": ["real_sft_v2", "real_topup2", "real_rw5"], "n_real_train": len(real), "n_real_gendev": len(gen),
               "train_md5": man["md5"]["train"], "gendev_md5": man["md5"]["gendev"], "local_val_sel": str(RUN / "local/val_sel.jsonl")},
              open(PF / "REAL_APPROVED.json", "w", newline="\n"), indent=1)
    print(json.dumps({k: man[k] for k in ("n_total", "new", "replay", "replay_frac", "real_replay", "steps_1_pass", "tool_share_of_new", "local")}))


main()
