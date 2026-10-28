"""Bench prompts for the reasoner (exact backend layout: v3StaticPrefix + user + <|im_end|> + assistant open).
Writes bench/prompts.jsonl: {id, prompt, prefix, gold}. Sources: 2 real board incidents (2026-10-27 run) + RWH held-out."""
import json, os, random
Q = r"C:\Users\hp\Desktop\qidk"
B = os.path.join(Q, r"Code\smart-city-edge-agent\app\backend")
hdr = open(os.path.join(B, "reasoner_v3_header.txt"), encoding="utf-8").read()
sysm = open(os.path.join(B, "reasoner_v3_system.txt"), encoding="utf-8").read()
prefix = hdr + sysm + "<|im_end|>\n<|im_start|>user\n"
OPEN = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
out = []
for tag in ("smoke_0", "chaos_0"):
    d = json.load(open(os.path.join(Q, r"proofs\2026-10-27_reasoner_board\raw", tag + "_incident.json"), encoding="utf-8"))
    f = d["incident"]["final"]
    assert f["prompt"].startswith(prefix), tag
    out.append({"id": d["id"], "prompt": f["prompt"], "gold": f["raw"]})
rows = [json.loads(l) for l in open(os.path.join(Q, r"proofs\2026-10-25_reasoner_final\data\incidents_rwh.ok.jsonl"), encoding="utf-8")]
rows = [r for r in rows if len(r["messages"]) == 3]
random.Random(7).shuffle(rows)
seen = set()
for r in rows:
    if r["family"] in seen: continue
    seen.add(r["family"])
    out.append({"id": "rwh:" + r["id"], "prompt": prefix + r["messages"][1]["content"] + "<|im_end|>\n" + OPEN, "gold": r["messages"][2]["content"]})
    if len(out) >= 10: break
with open(os.path.join(Q, r"proofs\2026-10-27_reasoner_fast\bench\prompts.jsonl"), "w", encoding="utf-8", newline="\n") as fo:
    for o in out:
        o["prefix"] = prefix
        fo.write(json.dumps(o) + "\n")
print(len(out), [o["id"] for o in out], len(prefix))
