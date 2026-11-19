"""exact token lengths of the r3 training data, tokenized by train_rsn3.prep itself (seg tokenization, tools_r3.json,
4B tokenizer) with max_len 10**6 so no row is dropped. The caches it writes (~/smartcity_runs/fit4b_r3/*_seg_tok.pt, keyed
by each file's md5) are the ones the real run loads. -> lengths_r3.json"""
import json, os, sys
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/kaggle")
import train_rsn3 as T
from transformers import AutoTokenizer
F = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/data/final/"
OUT = os.path.expanduser("~/smartcity_runs/fit4b_r3"); os.makedirs(OUT, exist_ok=True)
tok = AutoTokenizer.from_pretrained(os.path.expanduser("~/models/qwen3.5-4b"))
tools = json.load(open(F + "tools_r3.json", encoding="utf-8")); tools["none"] = None
res = {}
for name, src in (("inc", "incidents_train.jsonl"), ("chat", "chat_train_r3.jsonl"), ("dev", "dev_r3.jsonl")):
    n_file = sum(1 for _ in open(F + src, encoding="utf-8"))
    d, cache = T.prep(tok, F + src, tools, 10 ** 6, OUT, name)
    L = sorted(int(x["ids"].numel()) for x in d)
    q = lambda p: L[min(len(L) - 1, int(p * len(L)))]
    res[src] = {"file_rows": n_file, "kept": len(L), "p50": q(.5), "p90": q(.9), "p99": q(.99), "max": L[-1], "mean": round(sum(L) / len(L)),
                "tokens_M": round(sum(L) / 1e6, 1), "cache": cache,
                "pct_over": {str(c): round(100 * sum(1 for x in L if x > c) / len(L), 3) for c in (5120, 6144, 6400, 6656, 6912, 7168)}}
    del d
    print(src, json.dumps(res[src]), flush=True)
json.dump(res, open("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/lengths_r3.json", "w"), indent=1)
print("MAX", max(r["max"] for r in res.values()))
