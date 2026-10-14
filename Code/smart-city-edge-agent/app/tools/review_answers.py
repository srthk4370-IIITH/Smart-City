"""Judge whether each injected scenario got the RIGHT diagnosis, not just a policy-valid one.

Reads stress_report.json and compares every scenario incident with what that scenario actually
injects (the ground truth is the scenario definition, so this is a real correctness check).

  python review_answers.py [stress_report.json]
"""
import json
import sys
from pathlib import Path

# what a correct diagnosis looks like for each injected scenario
EXPECT = {
    "ventilation_failure": {"pattern": {"exponential_increase", "gradual_increase", "step_increase"},
                            "cause": {"ventilation_insufficient", "occupancy_load"}},
    "pm_spike": {"pattern": {"spike"}, "cause": {"outdoor_pollution_ingress", "indoor_emission_source"}},
    "power_throttling": {"pattern": {"throttling", "gradual_increase", "exponential_increase", "step_increase"},
                         "cause": {"capacity_limit_throttling", "gradual_load_growth", "load_surge"}},
    "load_surge": {"pattern": {"spike"}, "cause": {"load_surge", "equipment_startup"}},
    "tank_leak": {"pattern": {"gradual_decrease", "step_decrease", "dip"},
                  "cause": {"possible_leak", "tank_draining"}},
    "pump_cycling": {"pattern": {"oscillation", "erratic"}, "cause": {"pump_cycling"}},
    "stuck_sensor": {"pattern": {"flatline"}, "status": {"sensor_fault"}, "cause": {"sensor_fault"}},
    "heat_buildup": {"pattern": {"gradual_increase", "exponential_increase", "step_increase"},
                     "cause": {"heat_buildup"}},
    "off_hours_presence": {"pattern": {"off_hours_presence", "occupied", "arrival", "intermittent"},
                           "cause": {"off_hours_presence"}},
    "crowded_room": {"cause": {"occupancy_load", "ventilation_insufficient", "equipment_startup", "load_surge",
                               "gradual_load_growth", "arrival", "normal_occupancy"}},
}

rep = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("stress_report.json")).read_text(encoding="utf-8"))
right = wrong = 0
for inc in rep["incidents"]:
    tag = inc["tag"]
    sc = next((k for k in EXPECT if tag.endswith(" " + k)), None)
    if not sc or not inc["agents"]:
        continue
    exp = EXPECT[sc]
    for a in inc["agents"]:
        ok = all(a.get(f) in exp[f] for f in ("pattern", "status", "cause") if f in exp)
        right += ok
        wrong += not ok
        mark = "OK " if ok else "BAD"
        print(f"{mark} {tag:28} {a['role']:11} {a['pattern']}/{a['status']}/{a['cause']}")
        if not ok:
            print(f"      expected {exp}\n      said: {(a.get('observations') or [''])[0][:140]}")
    r = inc["report"]
    if r.get("label"):
        print(f"    report [{(r.get('model') or '')[:28]}] label={r['label']} valid={r['valid']}"
              + (f" errors={r['errors']}" if r.get("errors") else ""))
print(f"\nagent diagnoses matching the injected scenario: {right}/{right + wrong}")
