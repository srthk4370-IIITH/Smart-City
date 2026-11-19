"""build_mix.py [N_TOTAL=10000] [REAL_FRAC=0.75] [--src=DIR] [--out=DIR] [--gen-n=100] [--pf=DIR]
The agt_v3 top-up mix for Kaggle. LAPTOP, CPU only, deterministic (seed 1116).
Real side (30,724 rows, every one a 12 h window in agt_v3 card format): stratified by role x status x family-group, calm/routine
families weighted x2. Synthetic replay (agt_v3/train.jsonl): stratified by family x stage x status, 40-min stage weighted x2
(the real windows are all 12 h, so the short-window emphasis can only live on the synthetic side), calm_routine x1.5;
unseen_metric and jittered-card rows stay in (independence).
Writes OUT/mixdata (the upload) and OUT/local (never uploaded: REAL VAL 400, synthetic slice 120, unseen_metric 100), plus a
counts-only mix_manifest.json and REAL_APPROVED.json (md5-pinned owner exception for check_data_topup.py) into the proof dir."""
import collections
import hashlib
import json
import os
import random
import sys
from pathlib import Path

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opt = {a.split("=")[0]: a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}
N = int(args[0]) if args else 10000
RF = float(args[1]) if len(args) > 1 else 0.75
HOME = Path.home()
QIDK = Path(os.environ.get("QIDK", "/mnt/c/Users/hp/Desktop/qidk"))
SRC = Path(opt.get("--src", HOME / "smartcity_runs/agt_topup"))
OUT = Path(opt.get("--out", HOME / "smartcity_runs/agt_topup_k"))
V3 = Path(opt.get("--v3", QIDK / "proofs/2026-11-13_v3_data/agt_v3"))
PF = Path(opt.get("--pf", QIDK / "proofs/2026-11-16_agt_topup_kaggle"))
GEN_N = int(opt.get("--gen-n", 100))
rng = random.Random(1116)
CALM = {"real_routine", "real_real_routine", "real_stable"}
KEEP = ("id", "prompt", "completion", "gold", "family", "role", "stage", "slices", "synthetic", "source")


def rd(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def wr(p, rows):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def alloc(rows, k, key, weight):
    """exactly min(k, len(rows)) rows; stratum quota ~ n_s * weight(stratum), capped at n_s (water filling), largest remainder"""
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
            rest = left - sum(fl.values())
            for s in sorted(free, key=lambda s: (-(raw[s] - fl[s]), str(s)))[:rest]:
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


def status_of(r):
    return r["gold"]["status"] if isinstance(r.get("gold"), dict) else "?"


real = rd(SRC / "data/real_train_all.jsonl")
val = rd(SRC / "data/real_val.jsonl")
syn = rd(V3 / "train.jsonl")
n_real = round(N * RF)
n_syn = N - n_real
grp = lambda f: "calm" if f in CALM else "other"
real_pick = alloc(real, n_real, lambda r: (r["role"], status_of(r), grp(r["family"])), lambda s: 2.0 if s[2] == "calm" else 1.0)
SW = {"40min": 2.0, "1.5h": 1.0, "3h": 1.0}
syn_pick = alloc(syn, n_syn, lambda r: (r["family"], r.get("stage"), status_of(r)),
                 lambda s: SW.get(s[1], 1.0) * (1.5 if s[0] == "calm_routine" else 1.0))
mix = [{k: r.get(k) for k in KEEP} for r in real_pick + syn_pick]
rng.shuffle(mix)
assert len({r["id"] for r in mix}) == len(mix), "duplicate ids"
vids = {r["id"] for r in val}
vkey = {(r.get("node"), r.get("end_epoch")) for r in val}
assert not (vids & {r["id"] for r in real_pick}), "real train overlaps REAL VAL (id)"
assert not (vkey & {(r.get("node"), r.get("end_epoch")) for r in real_pick}), "real train overlaps REAL VAL (node, end_epoch)"
# local-only sets: REAL VAL selection = the SAME 400 rows as the laptop top-up (first 400); the kernel's gen-dev = val[400:400+GEN_N]
val_sel = val[:400]
if (SRC / "mix/val_sel.jsonl").exists():
    assert [r["id"] for r in rd(SRC / "mix/val_sel.jsonl")] == [r["id"] for r in val_sel], "val_sel differs from the laptop top-up's"
gen = [{k: r.get(k) for k in KEEP} for r in val[400:400 + GEN_N]]
syn_slice = rd(SRC / "mix/syn_slice.jsonl")
um = alloc(rd(V3 / "gate/test_unseen_metric.jsonl"), 100, lambda r: (r["role"],), lambda s: 1.0)
assert not ({r["id"] for r in um} & {r["id"] for r in syn}), "unseen_metric eval rows are in the synthetic train set"
wr(OUT / "mixdata/train.jsonl", mix)
wr(OUT / "mixdata/gendev.jsonl", gen)
wr(OUT / "local/val_sel.jsonl", val_sel)
wr(OUT / "local/syn_slice.jsonl", syn_slice)
wr(OUT / "local/unseen100.jsonl", um)
cnt = lambda rows, f: dict(sorted(collections.Counter(f(r) for r in rows).items(), key=lambda x: str(x[0])))
jit = {r["id"]: str(r.get("jittered")) for r in syn}
man = {"n_total": len(mix), "real": len(real_pick), "synthetic": len(syn_pick), "real_frac": round(len(real_pick) / len(mix), 4),
       "steps_1_pass": -(-len(mix) // 32),
       "real_by_role": cnt(real_pick, lambda r: r["role"]), "real_by_status": cnt(real_pick, status_of),
       "real_by_family": cnt(real_pick, lambda r: r["family"]),
       "real_calm_routine_share": round(sum(r["family"] in CALM for r in real_pick) / len(real_pick), 4),
       "real_calm_routine_share_pool": round(sum(r["family"] in CALM for r in real) / len(real), 4),
       "real_window": "12 h (144 x 5 min) for every real row: the real pool has no short windows",
       "syn_by_family": cnt(syn_pick, lambda r: r["family"]), "syn_by_stage": cnt(syn_pick, lambda r: r.get("stage")),
       "syn_by_status": cnt(syn_pick, status_of), "syn_stage_pool": cnt(syn, lambda r: r.get("stage")),
       "syn_unseen_metric": sum(r["family"] == "unseen_metric" for r in syn_pick),
       "syn_jittered_cards": sum(jit.get(r["id"]) == "True" for r in syn_pick),
       "syn_jittered_pool_share": round(sum(v == "True" for v in jit.values()) / len(jit), 4),
       "gendev_real": len(gen), "local": {"val_sel": len(val_sel), "syn_slice": len(syn_slice), "unseen100": len(um)},
       "md5": {"train": md5(OUT / "mixdata/train.jsonl"), "gendev": md5(OUT / "mixdata/gendev.jsonl")}}
PF.mkdir(parents=True, exist_ok=True)
json.dump(man, open(PF / "mix_manifest.json", "w", newline="\n"), indent=1)
json.dump({"dataset_slug": "agt3-topup-data", "private": True, "scope": "THIS dataset only: train.jsonl + gendev.jsonl pinned by md5",
           "approval": "owner approved real windows on Kaggle as a PRIVATE dataset for the agt_v3 top-up (relayed by the main session, 2026-11-16)",
           "allowed_sources": ["real_sft_v2", "real_topup2", "real_rw5"], "n_real_train": len(real_pick), "n_real_gendev": len(gen),
           "train_md5": man["md5"]["train"], "gendev_md5": man["md5"]["gendev"], "local_val_sel": str(OUT / "local/val_sel.jsonl")},
          open(PF / "REAL_APPROVED.json", "w", newline="\n"), indent=1)
print(json.dumps({k: man[k] for k in ("n_total", "real", "synthetic", "steps_1_pass", "syn_unseen_metric", "syn_jittered_cards", "gendev_real")}))
