"""chat_test_r3 items whose gold depends on a parameter the question does not state (owner decision 2026-11-12: excluded from
the r4 gate's fog-slice comparison for both models). Conservative rule, only two parameters:
  co_occurring_incidents.window_min = W in the gold, and W does not appear as a number in the last question
  recurring_issues.min_count = K in the gold, and K does not appear as a number in the last question
(an unstated parameter should take the tool default: window 60, min_count 3; the r3 generator put a random value in the gold
when the template had no slot for it). -> ../data/chat_test_r3_ambiguous.jsonl
  python3 ambig_r3.py"""
import collections, json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "2026-11-06_4b_local", "data", "final", "chat_test_r3.jsonl")
OUT = os.path.join(HERE, "..", "data", "chat_test_r3_ambiguous.jsonl")
rows, c = [], collections.Counter()
for l in open(SRC, encoding="utf-8"):
    r = json.loads(l)
    q = [m["content"] for m in r["messages"] if m["role"] == "user"][-1]
    why = []
    for g in r["gold_calls"]:
        for tool, arg in (("co_occurring_incidents", "window_min"), ("recurring_issues", "min_count")):
            if g["name"] == tool and arg in g["args"] and not re.search(r"(?<![\d.])%d(?![\d.])" % int(g["args"][arg]), q):
                why.append("%s.%s=%s not stated in the question" % (tool, arg, g["args"][arg]))
    if why:
        rows.append({"id": r["id"], "kind": r["kind"], "fog": r["fog"], "question": q, "reason": "; ".join(why)})
        c[r["fog"]] += 1
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    for x in rows:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")
print(len(rows), dict(c), dict(collections.Counter(x["kind"] for x in rows)))
