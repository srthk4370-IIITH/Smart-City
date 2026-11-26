"""board_collect.py: RQ1 board numbers from the incidents the board actually ran (read-only GETs + htpd.log).
Live-ingest sweep (board_run.py) is infeasible on the live app: a sensor opens about one incident per 4 h window, and only 5 sensors have reachable critical limits."""
import json, re, statistics as S
import board_run as B
out = {"incidents": [], "log": {}}
for i in B.ids():
    d = B.req("/api/incidents/" + i)[1] or {}
    s = B.slim(d)
    s["test_incident"] = i in ("INC-0013", "INC-0014", "INC-0015", "INC-0016")
    out["incidents"].append(s)
log = B.sh("grep -E \"reasoner loaded in|agents' model back|prefill|load phases\" /data/local/tmp/smart_city_edge/state/htpd.log", 60)
lg = B.parse_log("")
sw = [int(m[1]) for m in re.finditer(r"reasoner loaded in (\d+) ms", log)]
bk = [int(m[1]) for m in re.finditer(r"agents' model back in (\d+) ms", log)]
pf = [(int(m[1]), int(m[2])) for m in re.finditer(r"reason \d+ streams?, (\d+) decode steps, prefill (\d+) ms", log)]
med = lambda x: round(S.median(x)) if x else None
out["log"] = dict(swap_in_ms=sw, swap_back_ms=bk, prefill_ms=[p for _, p in pf], decode_steps=[d for d, _ in pf],
                  summary=dict(n_swap=len(sw), swap_in_med=med(sw), swap_back_med=med(bk), prefill_med=med([p for _, p in pf])))
rows = []
for s in out["incidents"]:
    r = s["reasoner"]
    if not s.get("total_ms"):
        continue
    ag = [a for a in s["agents"] if a["latency_ms"]]
    rows.append(dict(id=s["id"], test=s["test_incident"], n_primary=s.get("n_primary"), npu_calls=s["npu_calls"], total_ms=s["total_ms"],
                     n_npu_agents=len(ag), agent_sum_ms=round(sum(a["latency_ms"] for a in ag)), agent_max_ms=round(max([a["latency_ms"] for a in ag] or [0])),
                     reasoner_model=r["model"], reasoner_ms=r["latency_ms"], reasoner_ttft_ms=r["ttft_ms"], reasoner_tokens=r["gen_tokens"], severity=r["severity"]))
out["rows"] = rows
json.dump(out, open("results/board_incidents.json", "w"), indent=1)
for r in rows:
    print(r)
print(out["log"]["summary"])
