"""Run every demo scenario against the host build (mock LLM) and report the pattern the rule layer sees."""
import json, subprocess, time, urllib.request, sys
BASE = "http://127.0.0.1:8091"
def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())
expected = {"ventilation_failure": "exponential_increase", "pm_spike": "spike", "power_throttling": "throttling",
            "load_surge": "spike", "tank_leak": "gradual_decrease", "pump_cycling": "oscillation",
            "stuck_sensor": "flatline", "heat_buildup": "gradual_increase", "off_hours_presence": "off_hours_presence|arrival|occupied",
            "crowded_room": "arrival|occupied|gradual_increase|step_increase"}
scen = call("/api/scenarios")
ok = 0
for sc in scen:
    call("/api/replay", {"restart": True, "speed": 1, "poll_ms": 100})
    time.sleep(1.5)
    before = {i["id"] for i in call("/api/incidents")}
    call("/api/inject", {"scenario": sc["id"]})
    seen, t0 = None, time.time()
    while time.time() - t0 < 40:
        incs = call("/api/incidents")
        new = [i for i in incs if i["injected"] and i["id"] not in before]
        if new:
            d = call(f"/api/incidents/{new[0]['id']}")
            seen = [(s["node"], s["metric"], s["rule_finding"]["pattern"], s["rule_finding"]["status"]) for s in d["sensors"]]
            break
        time.sleep(0.5)
    want = expected[sc["id"]].split("|")
    good = bool(seen) and any(p in want for _, _, p, _ in seen)
    ok += good
    print(("OK  " if good else "BAD ") + f"{sc['id']:20} expected {expected[sc['id']]:35} got {seen}")
    call("/api/inject", {"scenario": "clear"})
print(f"{ok}/{len(scen)} scenarios produce the intended pattern")
