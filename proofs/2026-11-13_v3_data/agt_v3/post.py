"""Assemble + dedup + token lengths for agt_v3 (run after gen_agt.py).

  python3 post.py DATA_DIR SHARDS_DIR TOKENIZER_JSON
1. concat shards per split -> verify_agt (every row) -> agt_v3/<split>.jsonl (+ reports/verify_<split>.json)
2. dedup (V3_DESIGN §4.7): exact normalised evidence block + MinHash (word 3-grams, 64 perms, LSH 16x4, J >= 0.9)
   of every train row vs all existing agent gate sets (dev3f, eval3e, E1, sft_v2 dev/test, host400, rw5, placement)
   and vs our own dev/test splits; hits are dropped from train (reports/dedup.json)
3. token lengths with the Llama-3.2 tokenizer (prompt + completion); rows over 1536 dropped (reports/tokens.json)
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAXLEN = 1536
SPLITS = ("train", "dev", "test_unseen_layout", "test_campus", "test_unseen_metric", "calm_fault")
GATE_GLOBS = ["~/smartcity_runs/agents_v2_topup3f/dev/dev3f.jsonl", "~/smartcity_runs/agents_v2_topup3e/eval/eval3e.jsonl",
              "~/smartcity_runs/agents_v2_topup3f/eval_rw5dev/eval3e.jsonl", "~/smartcity_runs/agents_v21/data/v21_rw5.jsonl",
              "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/e1/eval3e.jsonl",
              "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/data/sft_v2/dev.jsonl",
              "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/data/sft_v2/test.jsonl",
              "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-22_host_gguf_eval/prompts_host400.jsonl",
              "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-20_v2_post/device/placement_v2/prompts.jsonl",
              "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-21_v2t_device/placement_s24/prompts.jsonl",
              "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_v2t3f/rw5/*.jsonl"]
P = (1 << 61) - 1
RNG = random.Random(9)
A = [RNG.randrange(1, P) for _ in range(64)]
B = [RNG.randrange(0, P) for _ in range(64)]


def ev_block(prompt):
    i = prompt.find("EVIDENCE:")
    j = prompt.find("SERIES")
    if j < 0:
        j = prompt.find("STATES")
    if j < 0:
        j = prompt.find("ROOM TEMP")
    s = (prompt[j:i] if 0 <= j < i else "") + prompt[i:]
    s = s.split("<|eot_id|>")[0]
    return re.sub(r"\s+", " ", s).strip().lower()


def minhash(text):
    w = text.split()
    sh = {hash(" ".join(w[i:i + 3])) & 0xFFFFFFFF for i in range(max(1, len(w) - 2))}
    return [min(((a * x + b) % P) for x in sh) for a, b in zip(A, B)]


def bands(sig):
    return [(k, tuple(sig[k * 4:(k + 1) * 4])) for k in range(16)]


def main():
    D, S, TOK = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    out = D / "agt_v3"
    rep_dir = out / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    # 1. assemble + verify
    for sp in SPLITS:
        files = sorted(glob.glob(str(S / f"{sp}__*.jsonl")))
        raw = out / f"_raw_{sp}.jsonl"
        with open(raw, "w", encoding="utf-8") as o:
            for f in files:
                o.write(open(f, encoding="utf-8").read())
        subprocess.run([sys.executable, str(HERE / "verify_agt.py"), str(raw), str(out / f"{sp}.jsonl"), str(rep_dir / f"verify_{sp}.json")], check=True)
    # 2. dedup
    refs = []
    for g in GATE_GLOBS:
        for p in glob.glob(os.path.expanduser(g)):
            refs.append(p)
    exact, lsh, sigs = {}, defaultdict(list), []
    nref = Counter()
    for p in refs:
        for l in open(p, encoding="utf-8"):
            try:
                r = json.loads(l)
            except Exception:  # noqa: BLE001
                continue
            pr = r.get("prompt") or ""
            if "EVIDENCE:" not in pr:
                continue
            e = ev_block(pr)
            exact[hashlib.sha1(e.encode()).hexdigest()] = p
            sg = minhash(e)
            k = len(sigs)
            sigs.append((sg, p))
            for bd in bands(sg):
                lsh[bd].append(k)
            nref[Path(p).name] += 1
    own = {}
    for sp in SPLITS[1:]:
        for l in open(out / f"{sp}.jsonl", encoding="utf-8"):
            r = json.loads(l)
            e = ev_block(r["prompt"])
            own[hashlib.sha1(e.encode()).hexdigest()] = sp
            sg = minhash(e)
            k = len(sigs)
            sigs.append((sg, "own:" + sp))
            for bd in bands(sg):
                lsh[bd].append(k)
    dd = {"ref_files": dict(nref), "ref_rows": sum(nref.values()), "train_in": 0, "exact_hits": Counter(), "near_hits": Counter(), "examples": []}
    kept = []
    seen_train = set()
    for l in open(out / "train.jsonl", encoding="utf-8"):
        r = json.loads(l)
        dd["train_in"] += 1
        e = ev_block(r["prompt"])
        h = hashlib.sha1(e.encode()).hexdigest()
        if h in exact or h in own or h in seen_train:
            dd["exact_hits"][exact.get(h) or own.get(h) or "train_self"] += 1
            continue
        seen_train.add(h)
        sg = minhash(e)
        cand = set()
        for bd in bands(sg):
            cand.update(lsh.get(bd, ()))
        hit = None
        for k in cand:
            j = sum(1 for a, b in zip(sg, sigs[k][0]) if a == b) / 64
            if j >= 0.9:
                hit = sigs[k][1]
                break
        if hit:
            dd["near_hits"][hit] += 1
            if len(dd["examples"]) < 5:
                dd["examples"].append({"id": r["id"], "hit": hit})
            continue
        kept.append(l)
    with open(out / "train.jsonl", "w", encoding="utf-8") as o:
        o.writelines(kept)
    dd["train_out"] = len(kept)
    (rep_dir / "dedup.json").write_text(json.dumps(dd, indent=1, default=dict))
    print("dedup", dd["train_in"], "->", dd["train_out"], dict(dd["exact_hits"]), dict(dd["near_hits"]), flush=True)
    # 3. tokens
    from tokenizers import Tokenizer
    tk = Tokenizer.from_file(TOK)
    tok = {}
    for sp in SPLITS:
        p = out / f"{sp}.jsonl"
        rows = open(p, encoding="utf-8").readlines()
        lens, comp, keep, over = [], [], [], 0
        fam = defaultdict(list)
        for l in rows:
            r = json.loads(l)
            a = len(tk.encode(r["prompt"], add_special_tokens=False).ids)
            c = len(tk.encode(r["completion"], add_special_tokens=False).ids)
            if a + c > MAXLEN:
                over += 1
                continue
            lens.append(a + c)
            comp.append(c)
            fam[r["family"]].append(a + c)
            keep.append(l)
        with open(p, "w", encoding="utf-8") as o:
            o.writelines(keep)
        s = sorted(lens)
        q = lambda x: s[min(len(s) - 1, int(x * (len(s) - 1)))] if s else None  # noqa: E731
        tok[sp] = {"rows": len(keep), "dropped_over_1536": over, "total_p50": q(0.5), "total_p95": q(0.95), "total_max": max(s) if s else None,
                   "completion_p50": sorted(comp)[len(comp) // 2] if comp else None, "completion_max": max(comp) if comp else None,
                   "tokens_sum": sum(lens), "max_by_family": {k: max(v) for k, v in fam.items()}}
        print(sp, tok[sp]["rows"], "max", tok[sp]["total_max"], "over", over, flush=True)
    (rep_dir / "tokens.json").write_text(json.dumps(tok, indent=1))


if __name__ == "__main__":
    main()
