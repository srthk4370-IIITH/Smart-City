"""Host check (mock LLM): cross-domain orchestration, context agents, synthesizer decision, cache."""
import json, time, urllib.request
import sys
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8092"
def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())
def wait_new(before, injected=None, mode=None):
    t0 = time.time()
    while time.time() - t0 < (60 if "8092" in BASE else 400):
        for i in call("/api/incidents"):
            if i["id"] not in before and i["state"] != "running" and (injected is None or i["injected"] == injected) and (mode is None or i["mode"] == mode):
                return call(f"/api/incidents/{i['id']}")
        time.sleep(0.5)
for sc in ("ventilation_failure", "tank_leak", "crowded_room"):
    call("/api/replay", {"restart": True, "speed": 1, "poll_ms": 100 if "8092" in BASE else 700}); time.sleep(1.5 if "8092" in BASE else 6)
    before = {i["id"] for i in call("/api/incidents")}
    call("/api/inject", {"scenario": sc})
    d = wait_new(before, injected=True)
    print(f"\n=== {sc}: {d['id']} {d['title']}")
    for s in d["sensors"]:
        print(f"  {s['ref']} {'context' if s['context'] else 'FLAGGED'} {s['role']:11} {s['node']} {s['metric']} rule={s['rule_finding']['pattern']}/{s['rule_finding']['status']} {s.get('why','')}")
    for a in d["agents"]:
        print(f"  agent {a['ref']} {a['model'][:28]:28} {a['latency_ms']/1000:5.1f}s ttft={a.get('ttft_ms',0)/1000:.1f}s tok={a.get('gen_tokens')} valid={a['valid']} cached={a.get('cached')}")
    if d["final"]: print(f"  final latency {d['final']['latency_ms']/1000:.1f}s tokens={d['final'].get('gen_tokens')} | TOTAL {d['total_ms']/1000:.1f}s")
    print("  final:", d["final"]["model"][:45] if d["final"] else None, "| npu calls", d["npu_calls"])
    print("  timeline:", [t["msg"][:90] for t in d["timeline"]][1:3])
    call("/api/inject", {"scenario": "clear"})
before = {i["id"] for i in call("/api/incidents")}
call(f"/api/incidents/{d['id']}/rerun?mode=3", {})
r = wait_new(before, mode=3)
print("\nrerun of", d["id"], "-> npu calls", r["npu_calls"], "| total ms", r["total_ms"], "|", [t["msg"][:70] for t in r["timeline"] if "agent done" in t["msg"]])
