"""MANIFEST.json + examples.md for APPROVAL.md (counts, composition, md5s, 3-4 truncated examples per family)."""
import collections
import hashlib
import json
import os
import random
import re
import sys

D = sys.argv[1]
out = {"files": {}, "composition": {}}
for root, _, fs in os.walk(D):
    for f in sorted(fs):
        p = os.path.join(root, f)
        if f.endswith((".jsonl", ".json")) and not f.startswith(("MANIFEST", "build_stats")):
            out["files"][os.path.relpath(p, D)] = {"md5": hashlib.md5(open(p, "rb").read()).hexdigest(),
                                                    "rows": sum(1 for _ in open(p, encoding="utf-8")) if f.endswith(".jsonl") else None}


def comp(path):
    c = collections.Counter()
    for l in open(path, encoding="utf-8"):
        r = json.loads(l)
        b = r.get("block", r.get("tools"))
        c["block:" + b] += 1
        if str(r.get("tools", "")).startswith("incident"):
            try:
                txt = r["messages"][-1]["content"]
                rep = json.loads(txt[txt.find("{"):])
                c["severity:" + rep["severity"]] += 1
                c["suspect_node:" + rep.get("suspect_node", {}).get("verdict", "none")] += 1
            except Exception:
                c["severity:?"] += 1
            c["agent_format:" + r.get("agent_format", "r3")] += 1
            c["think:" + str(bool(r["messages"][-1].get("reasoning_content")))] += 1
            c["rtype:" + str(r.get("reasoning_type", "none"))] += 1
            fam = r.get("family", "?").split("+")[0]
            c["family:" + re.sub(r"^card:.*", "card:*", re.sub(r"real_agent(_v4)?:.*", "real_agent", fam))] += 1
            if "agent_checks" in txt:
                c["has_agent_check:" + str('"agent_checks": []' not in txt)] += 1
        else:
            c["fog:" + str(r.get("fog"))] += 1
            c["hard:" + str(bool(r.get("hard")))] += 1
            c["hinglish:" + str(bool(r.get("hinglish")))] += 1
            c["multi_turn:" + str(bool(r.get("multi_turn")) or sum(m["role"] == "user" for m in r["messages"]) > 1)] += 1
    return dict(sorted(c.items()))


for f in ("train_new.jsonl", "replay.jsonl"):
    out["composition"][f] = comp(os.path.join(D, f))
for f in sorted(os.listdir(os.path.join(D, "tests"))):
    out["composition"]["tests/" + f] = comp(os.path.join(D, "tests", f))
json.dump(out, open(os.path.join(D, "MANIFEST.json"), "w"), indent=1)

# examples
R = random.Random(5)
by = collections.defaultdict(list)
for l in open(os.path.join(D, "train_new.jsonl"), encoding="utf-8"):
    r = json.loads(l)
    by[r["block"]].append(r)
ex = []
for b in sorted(by):
    ex.append("### %s (%d rows)\n" % (b, len(by[b])))
    for r in R.sample(by[b], min(3, len(by[b]))):
        msgs = r["messages"]
        if str(r["tools"]).startswith("incident"):
            u = msgs[1]["content"]
            lines = u.split("\n")
            keep = [x for x in lines if not re.match(r"\s+S\d+\.E([2-9]|10) ", x)]
            ex.append("`%s` family `%s`, agent %s\n```\n%s\n```" % (r["id"], r["family"], r.get("agent_format"), "\n".join(keep)[:1800]))
            th = msgs[-1].get("reasoning_content")
            if th:
                ex.append("think: %s" % th)
            ex.append("```json\n%s\n```" % msgs[-1]["content"][:1300])
        else:
            conv = []
            for m in msgs[1:]:
                if m["role"] == "tool":
                    conv.append("tool: " + m["content"][:300])
                elif m.get("tool_calls"):
                    conv.append("assistant%s calls: %s" % (" <think>" + m["reasoning_content"] + "</think>" if m.get("reasoning_content") else "",
                                                          json.dumps([[c["function"]["name"], c["function"]["arguments"]] for c in m["tool_calls"]], ensure_ascii=False)))
                else:
                    conv.append("%s: %s" % (m["role"], (m["content"] or "")[:400]))
            ex.append("`%s` family `%s` fog %s hard %s\n```\n%s\n```" % (r["id"], r["family"], r.get("fog"), r.get("hard"), "\n".join(conv)[:1800]))
open(os.path.join(D, "..", "examples.md"), "w", encoding="utf-8").write("\n".join(ex) + "\n")
print(json.dumps(out["composition"], indent=0)[:6000])
