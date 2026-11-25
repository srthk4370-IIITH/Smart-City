"""gate_report_big.py scores.json NEW_ADAPTER NEW_GGUF > GATE.md : per-slice table p2 vs new (+ sub-slices); FLAG lines are informational."""
import json, sys
S = json.load(open(sys.argv[1])); adapter, gguf = sys.argv[2], sys.argv[3]
KEY = {"report_all": "ok", "new_family": "ok", "chat_en": "ok", "tool_chain": "ok"}
print("# Reasoner big top-up: frozen gate (p2 vs new)\n")
print("Scores only: no PASS / auto-deploy (owner decides together). Rows are few per sub-slice (1 row = 1/n), so deltas there are anecdotes; the 4 main slices are the evidence.\n")
print("candidate adapter: %s\ncandidate GGUF (not deployed): %s\n" % (adapter, gguf))
flags = []
for sl in ("report_all", "new_family", "chat_en", "tool_chain"):
    a, b = S["p2"].get(sl, {}).get("ALL"), S["new"].get(sl, {}).get("ALL")
    if not a or not b:
        print("## %s: missing results\n" % sl); continue
    print("## %s (n=%d; p2 missing %d, new missing %d)\n" % (sl, a["n"], a.get("missing", 0), b.get("missing", 0)))
    print("| metric | p2 | new | delta |\n|---|---|---|---|")
    for k in [k for k in a if k not in ("n", "missing")]:
        d = b.get(k, 0) - a[k]
        print("| %s | %.3f | %.3f | %+.3f |" % (k, a[k], b.get(k, 0), d))
        if k == "ok" and d < -0.03:
            flags.append("FLAG: %s ok dropped %+.3f" % (sl, d))
        if k == "valid" and b.get(k, 0) < a[k]:
            flags.append("FLAG: %s JSON validity %.3f < p2 %.3f" % (sl, b.get(k, 0), a[k]))
    print("\n| sub-slice | n | p2 ok | new ok | delta |\n|---|---|---|---|---|")
    for sub in sorted(set(S["p2"][sl]) | set(S["new"][sl])):
        if sub == "ALL":
            continue
        x, y = S["p2"][sl].get(sub, {}), S["new"][sl].get(sub, {})
        n = x.get("n", y.get("n", 0))
        d = y.get("ok", 0) - x.get("ok", 0)
        print("| %s | %s | %.2f | %.2f | %+.2f |" % (sub, n, x.get("ok", 0), y.get("ok", 0), d))
        if d < -0.03 and n >= 5:
            flags.append("FLAG: %s/%s ok dropped %+.2f (n=%s)" % (sl, sub, d, n))
    print()
print("## Flags (informational)\n")
print("\n".join(flags) or "none")
print("\nRESULT: SCORES ONLY (deploy decided by the owner)")
