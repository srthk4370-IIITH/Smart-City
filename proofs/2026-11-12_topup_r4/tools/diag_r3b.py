import json, sys
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/"
gold = {}
for l in open(P + "data/final/chat_test_r3.jsonl", encoding="utf-8"):
    r = json.loads(l); gold[r["id"]] = r
kinds = sys.argv[1].split(",")
n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
for l in open(P + "post/gate_r3/chat_test_r3_4b.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r["kind"] in kinds and not r["pass"] and n > 0:
        n -= 1
        g = gold[r["id"]]
        print("ID", r["id"], r["fog"], r["reasons"])
        print("GOLDKEYS", list(g.keys()))
        for k in g:
            if k not in ("messages",):
                print(" ", k, json.dumps(g[k], ensure_ascii=False)[:700])
        for m in g.get("messages", [])[1:]:
            print("  MSG", m["role"], (m.get("content") or "")[:600], json.dumps(m.get("tool_calls"))[:300] if m.get("tool_calls") else "")
        print("  MODEL final:", r["final"][:400])
