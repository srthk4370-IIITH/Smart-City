"""Fixture for the Go parity test (app/backend/postrules_test.go TestPostRulesParity): every stored v2 answer of the
four eval sets (hvac / occupancy excluded: no post-rules), its window, and the finding after the Python rules.
  python export_parity.py  -> ../raw/postrules_parity.jsonl
"""
import json
from pathlib import Path

import trackb_lib as L
import common_v2 as C

GO_NAME = {"floor250": "floor"}
KEPT = ["erratic", "limit", "quality_cause", "rel_power", "rel_level", "water_cause", "glitch", "floor250", "chatter", "cause", "fkind"]
OUT = Path(__file__).resolve().parent.parent / "raw" / "postrules_parity.jsonl"

n = nch = 0
with open(OUT, "w") as fh:
    for ds in ("test", "rw5test", "dev", "rw5dev"):
        for row, s in L.load(ds):
            if row["role"] in ("hvac", "occupancy"):
                continue
            d = L.parse_full(s["text"])
            c = L.Ctx(row)
            if d is None or c.xs is None:
                continue
            p = {k: C._norm(d.get(k, "")) for k in ("pattern", "status", "likely_cause")}
            p["fault_kind"] = C._norm(d["fault_kind"]) if d.get("fault_kind") else None
            p["event_active"] = d.get("event_active")
            before = dict(p)
            changed = []
            for name in KEPT:
                for k, v in L.RULES[name](c, p):
                    changed.append(name)
                    p[k] = v
                    if k == "status" and v == "sensor_fault":
                        p["likely_cause"] = "sensor_fault"
            fh.write(json.dumps({"set": ds, "id": row["id"], "role": row["role"], "metric": row["metric"], "node": row.get("node", ""),
                                 "end": row["end_epoch"], "xs": c.xs, "tank": c.tank, "before": before, "after": p,
                                 "rules": sorted({GO_NAME.get(x, x) for x in changed})}) + "\n")
            n += 1
            nch += bool(changed)
print(n, "rows,", nch, "changed ->", OUT)
