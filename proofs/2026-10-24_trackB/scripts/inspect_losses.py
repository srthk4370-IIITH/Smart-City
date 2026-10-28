"""Print rows a rule made worse (short): python inspect_losses.py SET RULE [KEY] [MAX]"""
import sys

import trackb_lib as L

ds, rule = sys.argv[1], sys.argv[2]
key = sys.argv[3] if len(sys.argv) > 3 else "status"
mx = int(sys.argv[4]) if len(sys.argv) > 4 else 12
data = {r["id"]: r for r, _ in L.load(ds)}
pairs, ch = L.run_rules(ds, rule.split(","))
byid = {c["id"]: c for c in ch}
k = 0
for b, a in pairs:
    if b.get(key) and not a.get(key):
        r = data[b["id"]]
        c = L.Ctx(r)
        st = c.st or {}
        print(b["id"], r.get("node"), r.get("metric"), "n", c.n, "gold", b["gold_pattern"], b["gold_status"],
              "fam", r.get("family"), "| ch", [(x[1], x[2], x[3]) for x in byid[b["id"]]["changes"]],
              "| last %.2f min %.2f max %.2f base %.2f" % (st.get("last", 0), st.get("min", 0), st.get("max", 0), c.base or 0))
        k += 1
        if k >= mx:
            break
