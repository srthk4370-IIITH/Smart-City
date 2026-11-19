"""Per-domain / per-family breakdown of an agt_v3 snapshot's dev samples (for per-department neuron surgery). CPU only.
  python3 agent_domains.py <dev_samples.jsonl>"""
import json, sys, collections
S = [json.loads(l) for l in open(sys.argv[1])]
def tab(key):
    g = collections.defaultdict(list)
    for s in S: g[s.get(key)].append(s)
    print("%-16s %4s %6s %6s %6s %6s  top status confusions" % (key, "n", "status", "pattern", "cause", "dq"))
    for k, v in sorted(g.items(), key=lambda kv: sum(x["status"] for x in kv[1]) / len(kv[1])):
        c = collections.Counter("%s>%s" % (x["gold_status"], x["pred_status"]) for x in v if not x["status"])
        f = lambda m: sum(bool(x[m]) for x in v if x.get(m) is not None) / max(1, sum(x.get(m) is not None for x in v))
        print("%-16s %4d %6.3f %6.3f %6.3f %6.3f  %s" % (k, len(v), f("status"), f("pattern"), f("cause"), f("dq"), dict(c.most_common(3))))
tab("role"); tab("family")
cr = [s for s in S if s["gold_status"] == "critical"]; nm = [s for s in S if s["gold_status"] == "normal"]
print("critical recall %.3f (n %d) | false alarms on normal %.3f (n %d) | fault calls precision %.3f" % (
    sum(s["pred_status"] == "critical" for s in cr) / max(1, len(cr)), len(cr),
    sum(s["pred_status"] != "normal" for s in nm) / max(1, len(nm)), len(nm),
    sum(s["gold_status"] == "sensor_fault" for s in S if s["pred_status"] == "sensor_fault") / max(1, sum(s["pred_status"] == "sensor_fault" for s in S))))
