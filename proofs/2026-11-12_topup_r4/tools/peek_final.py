import json, sys
F = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/data/final/"
n = 0
for l in open(F + "replay.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("think") and r.get("tools") == "incident":
        print("REPLAY THINK:", r["messages"][-1]["reasoning_content"]); n += 1
        if n >= 2: break
seen = set()
for l in open(F + "train_new.jsonl", encoding="utf-8"):
    r = json.loads(l)
    k = r["family"].split("+")[0]
    if r["tools"] == "chat" and k.startswith("r4:x_") and k not in seen:
        seen.add(k)
        th = [m.get("reasoning_content") for m in r["messages"] if m.get("reasoning_content")]
        print(k, "| THINK:", th[:1])
