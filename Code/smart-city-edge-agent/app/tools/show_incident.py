"""Print what an incident actually concluded: the rule verdict per flagged sensor next to the agent's.

  python show_incident.py INC-0004 INC-0011
"""
import json
import sys
import urllib.request

for iid in sys.argv[1:]:
    with urllib.request.urlopen(f"http://127.0.0.1:8000/api/incidents/{iid}", timeout=15) as r:
        d = json.load(r)
    print(f"== {d['id']} | {d.get('title')} | state {d.get('state')} | {d.get('npu_calls')} NPU calls")
    for s in d.get("sensors", []):
        if not s.get("context"):
            rule = s.get("rule") or {}
            print(f"   flagged {s.get('metric'):8} rule: {rule.get('pattern')} / {rule.get('status')}")
    for a in d.get("agents", []):
        if a.get("prompt"):
            p = a.get("parsed") or {}
            obs = (p.get("observations") or [""])[0]
            print(f"   agent   {a.get('role'):11} -> {p.get('pattern')} / {p.get('status')} / {p.get('likely_cause')}"
                  f"  valid={a.get('valid')}\n            \"{obs[:150]}\"")
    f = d.get("final") or {}
    fp = f.get("parsed") or {}
    if fp:
        print(f"   report  [{f.get('model')}] label={fp.get('label')} action={fp.get('action')} valid={f.get('valid')}")
