"""Go parity fixture after P1 (postrules_test.go TestPostRulesParity default path): every stored mixA50 + v2 answer of
the four eval sets (hvac / occupancy excluded), its window, the prompt's E9 line, and the finding after the Python
P1 rules (= post_rules=all).  python export_parity_p1.py -> ../raw/postrules_parity_p1.jsonl"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dp_lib as D
import p1_rules as P
L, C = D.L, D.C
GO = {"floor250": "floor", "rel_level_p1": "rel_level", "water_cause_p1": "water_cause"}
KEPT = [r for r in P.ALL_P1 if r != "hvac_rule"]
OUT = Path(__file__).resolve().parent.parent / "raw" / "postrules_parity_p1.jsonl"
n = nch = 0
with open(OUT, "w") as fh:
    for tag in ("mixA50", "v2cuda"):
        for ds in ("test", "rw5test", "dev", "rw5dev"):
            for row, s in L.load(ds, tag):
                if row["role"] in ("hvac", "occupancy"):
                    continue
                d = L.parse_full(s["text"]); c = L.Ctx(row)
                if d is None or c.xs is None:
                    continue
                p = {k: C._norm(d.get(k, "")) for k in ("pattern", "status", "likely_cause")}
                p["fault_kind"] = C._norm(d["fault_kind"]) if d.get("fault_kind") else None
                p["event_active"] = d.get("event_active")
                before, changed = dict(p), []
                for name in KEPT:
                    for k, v in L.RULES[name](c, p):
                        changed.append(name); p[k] = v
                        if k == "status" and v == "sensor_fault":
                            p["likely_cause"] = "sensor_fault"
                e9 = P.RX_E9.search(row["prompt"])
                fh.write(json.dumps({"set": ds, "tag": tag, "id": row["id"], "role": row["role"], "metric": row["metric"], "node": row.get("node", ""),
                                     "end": row["end_epoch"], "xs": c.xs, "tank": c.tank, "prompt": "\n" + e9.group(0) if e9 else "",
                                     "before": before, "after": p, "rules": sorted({GO.get(x, x) for x in changed})}) + "\n")
                n += 1; nch += bool(changed)
print(n, "rows,", nch, "changed ->", OUT)
