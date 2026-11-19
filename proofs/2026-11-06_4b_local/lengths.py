"""token-length distribution of the r2 training rows with the Qwen3.5 tokenizer (identical tokenizer.json md5 for 2B/4B:
7b6074791b84e7ce3a5fc12746b82d48). Source: the trainer's own token caches (all rows, seg tokenization, tools_r2) (fit4b_probe run dir),
cross-checked by re-encoding a random sample of 300 rows per file with train_rsn3.encode and the 4B tokenizer."""
import json, os, random, sys, torch
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle")
import train_rsn3 as T
from transformers import AutoTokenizer
R = os.path.expanduser("~/smartcity_runs/fit4b_probe/")   # written by fit_probe.sh (train_rsn3.prep, max_len 8192 = no row dropped)
F = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_r2/data/final/"
tok = AutoTokenizer.from_pretrained(os.path.expanduser("~/models/qwen3.5-4b"))
tools = json.load(open(F + "tools_r2.json")); tools["none"] = None
out = {}
for name, cache, src in (("incident", "inc_2a1af257940e_seg_tok.pt", "incidents_train.jsonl"), ("chat", "chat_3876eaf0badb_seg_tok.pt", "chat_train.jsonl")):
    d = torch.load(R + cache)
    L = sorted(int(x["ids"].numel()) for x in d)
    lab = sum(int((x["labels"] != -100).sum()) for x in d) / len(d)
    rows = [json.loads(l) for l in open(F + src, encoding="utf-8")]
    byid = {x["id"]: int(x["ids"].numel()) for x in d}
    random.Random(5).shuffle(rows)
    mism = 0
    for r in rows[:300]:
        e, _ = T.encode(tok, r, tools.get(r["tools"]), 10 ** 6)
        mism += len(e[0]) != byid[r["id"]]
    q = lambda p: L[min(len(L) - 1, int(p * len(L)))]
    out[name] = {"rows": len(L), "file_rows": len(rows), "p50": q(.5), "p90": q(.9), "p99": q(.99), "max": L[-1], "mean": round(sum(L) / len(L)),
                 "label_tokens_mean": round(lab), "tokens_M": round(sum(L) / 1e6, 1), "sample_recheck_mismatch": "%d/300" % mism,
                 "pct_over": {str(c): round(100 * sum(1 for x in L if x > c) / len(L), 3) for c in (3072, 4096, 5120, 6144)}}
print(json.dumps(out, indent=1))
json.dump(out, open("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/lengths.json", "w"), indent=1)
