import json
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/"
amb = {json.loads(l)["id"] for l in open(P + "2026-11-12_topup_r4/data/chat_test_r3_ambiguous.jsonl")}
rs = [json.loads(l) for l in open(P + "2026-11-06_4b_local/post/gate_r3/chat_test_r3_4b.jsonl")]
for fog in ("online", "offline", "timeout"):
    full = [r for r in rs if r["fog"] == fog]; f = [r for r in full if r["id"] not in amb]
    pa = sum(r["pass"] for r in f); pf = sum(r["pass"] for r in full)
    print(fog, "full %d/%d=%.3f" % (pf, len(full), pf / len(full)), "filtered %d/%d=%.3f" % (pa, len(f), pa / len(f)), "excluded", len(full) - len(f),
          "excluded passing", sum(r["pass"] for r in full if r["id"] in amb))
