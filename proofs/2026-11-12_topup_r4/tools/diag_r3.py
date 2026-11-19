"""Diagnose r3 gate chat failures per kind/fog/reason (reads post/gate_r3 per-item files)."""
import json, collections, sys
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/post/gate_r3/"
for fn in ["chat_test_r3_4b.jsonl", "chatdev3_r3.jsonl"]:
    rows = [json.loads(l) for l in open(P + fn, encoding="utf-8")]
    rk = collections.Counter(); fk = collections.Counter(); ex = collections.defaultdict(list)
    for r in rows:
        if r["pass"]:
            continue
        for x in r["reasons"]:
            k = x.split(":")[0]
            rk[(k, r["fog"])] += 1
            fk[(r["kind"], k)] += 1
            if len(ex[(r["kind"], k)]) < 2:
                ex[(r["kind"], k)].append((x, r["final"][:260], [ (c["function"]["name"], json.dumps(c["function"]["arguments"])[:120]) for m in r["new"] for c in (m.get("tool_calls") or [])], [m.get("reasoning_content","")[:150] for m in r["new"] if m.get("reasoning_content")]))
    print("==", fn, len(rows)); print(sorted(rk.items(), key=lambda z: -z[1])[:20])
    for (k, rs), n in fk.most_common(45):
        print("##", k, rs, n)
        for e in ex[(k, rs)][:1]:
            print("   ", e)
