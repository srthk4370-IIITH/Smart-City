import json, re, collections, sys
c = collections.Counter()
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l)
    if not r["tools"].startswith("incident"): continue
    u = r["messages"][1]["content"]; rep = json.loads(r["messages"][-1]["content"])
    b = r["block"]
    sts = re.findall(r"^S\d+ \[FLAGGED\].*\n(?:  .*\n)*?  agent: pattern=\S+ status=(\S+)", u, re.M)
    s1 = re.search(r"agent: pattern=\S+ status=(\S+)", u)
    c[b + ":n"] += 1
    if s1 and s1.group(1) != rep["severity"]: c[b + ":gold_sev!=S1_agent"] += 1
    if sts and all(x != rep["severity"] for x in sts): c[b + ":gold_sev!=every_flagged_agent"] += 1
    if rep["severity"] == "sensor_fault" and s1 and s1.group(1) == "normal": c["ALL:visible_fault_called_normal"] += 1
    if rep["agent_checks"]: c[b + ":has_check"] += 1
print(json.dumps(dict(sorted(c.items())), indent=0))
