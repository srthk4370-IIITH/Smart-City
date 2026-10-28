import json, sys
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-23_reasoner_research/P0/host_bench")
from transformers import AutoTokenizer
from tools_impl import openai_tools, CHAT_TOOLS, INCIDENT_TOOLS
tok = AutoTokenizer.from_pretrained("/home/hp_srthk4370/models/qwen3.5-4b")
n = lambda s: len(tok(s, add_special_tokens=False)["input_ids"])
it, ct = openai_tools(INCIDENT_TOOLS), openai_tools(CHAT_TOOLS)
print("incident tools", n(json.dumps(it)), "chat tools", n(json.dumps(ct)))
rows = [json.loads(l) for l in open("../data/train_mix.jsonl", encoding="utf-8")][:300]
import statistics as S
for kind in ("incident", "chat"):
    rr = [r for r in rows if r["tools"] == kind]
    print(kind, "system", n(rr[0]["messages"][0]["content"]), "user p50", S.median(n(r["messages"][1]["content"]) for r in rr),
          "final p50", S.median(n(r["messages"][-1]["content"]) for r in rr))
