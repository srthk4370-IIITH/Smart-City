import json, sys
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/"
gold = {json.loads(l)["id"]: json.loads(l) for l in open(P + "data/final/chat_test_r3.jsonl", encoding="utf-8")}
kinds = sys.argv[1].split(","); n0 = int(sys.argv[2])
cnt = {}
for l in open(P + "post/gate_r3/chat_test_r3_4b.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r["kind"] in kinds and not r["pass"] and cnt.get(r["kind"], 0) < n0:
        cnt[r["kind"]] = cnt.get(r["kind"], 0) + 1
        g = gold[r["id"]]
        us = [m["content"] for m in g["messages"] if m["role"] == "user"]
        print("##", r["kind"], r["fog"], "hard" if g["hard"] else "easy", r["reasons"])
        print("  Q:", us[-1][:200], "| sys-fog:", [ln for ln in g["messages"][0]["content"].split("\n") if "fog" in ln.lower()][:1])
        print("  GOLD calls:", json.dumps(g["gold_calls"])[:300], "facts:", json.dumps(g["gold_facts"])[:300])
        print("  REF:", g["reference_answer"][:300])
        print("  MODEL calls:", [(c["function"]["name"], c["function"]["arguments"]) for m in r["new"] for c in (m.get("tool_calls") or [])])
        print("  MODEL:", r["final"][:300], "| THINK:", [m.get("reasoning_content","")[:120] for m in r["new"] if m.get("reasoning_content")][:1])
