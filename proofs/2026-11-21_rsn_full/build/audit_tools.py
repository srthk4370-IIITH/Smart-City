"""audit_tools.py: audit data/gen5_tools.jsonl against data/tools_v5.json (rules of check_big.audit_chat): tool names + args + enums + required
per schema (chat_r5 / chat_r6), incident ids and node args of every call exist in earlier context, ids cited in finals exist in tool
results/question, non-empty finals <= 650 chars, format instructions honoured, CO2 numbers carry ppm, recovery rows really contain an
empty/error result before the last call, 2-4 calls on agentic rows. Writes AUDIT_TOOLS.md; exit 1 if bad > 2 %."""
import collections
import json
import os
import re
import sys

D = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
T = json.load(open(D + "/tools_v5.json"))
SCH = {k: {f["function"]["name"]: f["function"]["parameters"] for f in T[k]} for k in ("chat_r5", "chat_r6")}
rows = [json.loads(l) for l in open(D + "/gen5_tools.jsonl", encoding="utf-8")]


def bad_of(r):
    b = []
    msgs, fin = r["messages"], r["messages"][-1]["content"] or ""
    if not fin.strip():
        return ["empty final"]
    if len(fin) > 650:
        b.append("final>650")
    if r.get("src_real") is not False:
        b.append("src_real")
    sch = SCH.get(r["tools"])
    if sch is None:
        return b + ["tools key"]
    seen = msgs[0]["content"]
    ncalls = 0
    for m in msgs:
        if m["role"] in ("user", "tool") or (m["role"] == "assistant" and not m.get("tool_calls")):
            seen += "\n" + (m.get("content") or "")
        for tc in m.get("tool_calls") or []:
            ncalls += 1
            n, a = tc["function"]["name"], tc["function"]["arguments"]
            s = sch.get(n)
            if s is None:
                b.append("unknown tool " + n)
                continue
            for k, v in a.items():
                if k not in s["properties"]:
                    b.append("arg %s.%s" % (n, k))
                elif "enum" in s["properties"][k] and v not in s["properties"][k]["enum"]:
                    b.append("enum %s.%s=%s" % (n, k, v))
            for q in s.get("required", []):
                if q not in a:
                    b.append("required %s.%s" % (n, q))
            for key in ("id", "node"):
                v = a.get(key)
                if isinstance(v, str) and v.lower() not in seen.lower():
                    b.append("%s %s not in context" % (key, v))
        if m["role"] == "assistant" and m.get("tool_calls"):
            seen += "\n" + json.dumps(m["tool_calls"])
    ctx = " ".join(m.get("content") or "" for m in msgs[1:])
    for i in set(re.findall(r"INC-\d+", fin)):
        if i not in ctx.replace(fin, ""):
            b.append("final id %s unseen" % i)
    f = r.get("fmt")
    if f == "two_lines" and len([x for x in fin.split("\n") if x.strip()]) != 2:
        b.append("two lines")
    if f == "one_sentence" and len(re.findall(r"[.!?](\s|$)", fin)) != 1:
        b.append("one sentence")
    if re.search(r"(?i)co2[^.0-9:]{0,14}[0-9]+(?:[.][0-9]+)?(?![0-9])(?!\s*ppm)", fin) and "ppm" not in fin:
        b.append("co2 no ppm")
    if r["family"] == "gen5_agentic":
        if not 2 <= ncalls <= 4:
            b.append("calls %d" % ncalls)
        if r.get("recovery"):
            tl = [json.loads(m["content"]) for m in msgs if m["role"] == "tool"]
            first = tl[0] if tl else {}
            if not ("error" in first or first.get("found") is False or first.get("items") == [] or first.get("sensors") == [] or first.get("total") == 0):
                b.append("recovery without failed first result")
        else:
            if any(isinstance(json.loads(m["content"]), dict) and "error" in json.loads(m["content"]) for m in msgs if m["role"] == "tool"):
                b.append("unexpected error in plain chain")
    elif ncalls < 1 and not r.get("nocall"):
        b.append("no call")
    return b


per = collections.defaultdict(lambda: [0, 0])
ex = collections.defaultdict(list)
for r in rows:
    e = bad_of(r)
    p = per[r["family"]]
    p[0] += 1
    if e:
        p[1] += 1
        if len(ex[r["family"]]) < 3:
            ex[r["family"]].append((r["id"], e[:3]))
tot, tb = sum(v[0] for v in per.values()), sum(v[1] for v in per.values())
kinds = collections.Counter(r.get("kind") for r in rows if r["family"] == "gen5_agentic")
rec = sum(1 for r in rows if r.get("recovery"))
ag = sum(1 for r in rows if r["family"] == "gen5_agentic")
nc = collections.Counter(len(r["gold_calls"]) for r in rows if r["family"] == "gen5_agentic")
L = ["# AUDIT_TOOLS (gen5_tools.jsonl vs tools_v5.json)", "", "| family | rows | bad | bad % |", "|---|---|---|---|"]
for k, (n, nb) in sorted(per.items()):
    L.append("| %s | %d | %d | %.1f%% |" % (k, n, nb, 100 * nb / max(n, 1)))
for k, v in ex.items():
    for x in v:
        L.append("- bad example %s: %s" % x)
L += ["", "total %d rows, bad %d = %.2f%% (limit 2%%)" % (tot, tb, 100 * tb / max(tot, 1)),
      "agentic: %d rows, recovery %d (%.1f%%), calls per row %s" % (ag, rec, 100 * rec / max(ag, 1), dict(sorted(nc.items()))), "agentic kinds: %s" % dict(kinds),
      "fog states: %s" % dict(collections.Counter(r["fog"] for r in rows)), "format rows: %s" % dict(collections.Counter(r.get("fmt") for r in rows)),
      "", "RESULT: " + ("PASS" if tb / max(tot, 1) <= 0.02 else "FAIL")]
open(D + "/../AUDIT_TOOLS.md", "w", newline="\n").write("\n".join(L) + "\n")
print("\n".join(L[-6:]))
sys.exit(0 if tb / max(tot, 1) <= 0.02 else 1)
