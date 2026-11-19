"""byte-identity checks: incident system text == app reasoner_v3_system.txt; chat system/header as r3 (render_header_r3 already
proves tools_r3.json chat header == app chat_header_r3.txt)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
Q = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(Q, "proofs", "2026-10-25_reasoner_final", "pipeline"))
from prompts import SYSTEM_INCIDENT_SHORT
BE = os.path.join(Q, "Code", "smart-city-edge-agent", "app", "backend")
app = open(os.path.join(BE, "reasoner_v3_system.txt"), encoding="utf-8").read()
print("incident system == app reasoner_v3_system.txt:", app == SYSTEM_INCIDENT_SHORT, app.rstrip("\n") == SYSTEM_INCIDENT_SHORT)
F = os.path.join(HERE, "..", "data", "final")
for fn in ("train_new.jsonl", "test_inc_r4.jsonl"):
    p = os.path.join(F, fn)
    if os.path.exists(p):
        n = bad = 0
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            if r.get("tools") == "incident":
                n += 1
                bad += r["messages"][0]["content"] != SYSTEM_INCIDENT_SHORT
        print(fn, "incident rows", n, "system mismatches", bad)
