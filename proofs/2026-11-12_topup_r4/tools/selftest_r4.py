"""Scorer self-test: gold outputs must score perfect, corrupted ones must not. Writes ../build/selftest/scorer_selftest.json (data/final is frozen).
  python3 selftest_r4.py
"""
import argparse
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_r4 as SR  # noqa: E402
F = os.path.join(HERE, "..", "data", "final")
TMP = os.path.join(HERE, "..", "build", "selftest")
os.makedirs(TMP, exist_ok=True)
R = random.Random(5)
rows = SR.load(os.path.join(F, "test_inc_r4.jsonl"))
gold, bad = [], []
for r in rows:
    th = r["messages"][-1].get("reasoning_content") or ""
    js = r["messages"][-1]["content"]
    gold.append({"id": r["id"], "think": th, "json_text": js})
    rep = json.loads(js)
    rep["severity"] = {"critical": "warning", "warning": "critical", "normal": "warning", "sensor_fault": "critical"}[rep["severity"]]
    rep["causal_chain"] = re.sub(r"\bS(\d+)\b", lambda m: "S%d" % (int(m.group(1)) % 9 + 1), rep["causal_chain"], count=1)
    bad.append({"id": r["id"], "think": "" if th else "I think about 12345 things.", "json_text": json.dumps(rep)})
res = {}
for name, outs in (("inc_gold", gold), ("inc_corrupt", bad)):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for o in outs:
            f.write(json.dumps(o) + "\n")
    a = argparse.Namespace(rows=os.path.join(F, "test_inc_r4.jsonl"), out=p)
    s = SR.score_inc(a)["all"]
    res[name] = {k: s.get(k) for k in ("n", "parsed", "severity", "label", "check_recall", "req", "schema_err", "ungrounded", "root_domain_ok", "think_ok_multi",
                                       "think_empty_single")}
recs = SR.load(os.path.join(F, "test_chat_r4.jsonl"))
kg = [SR.key_ok(r, r["reference_answer"]) for r in recs if r.get("answer_key")]
kb = []
for r in recs:
    if not r.get("answer_key"):
        continue
    ids = re.findall(r"INC-\d+", r["reference_answer"])
    ans = r["reference_answer"]
    if len(set(ids)) >= 2:
        a1, a2 = ids[0], next(i for i in ids if i != ids[0])
        ans = ans.replace(a1, "\0").replace(a2, a1).replace("\0", a2)
    for ph in sum(SR.REL_PH.values(), []):
        ans = re.sub(re.escape(ph), "xx", ans, flags=re.I)
    kb.append(SR.key_ok(r, ans))
res["chat_key_gold"] = "%d/%d" % (sum(1 for x in kg if x), len(kg))
res["chat_key_corrupt"] = "%d/%d" % (sum(1 for x in kb if x), len(kb))
json.dump(res, open(os.path.join(TMP, "scorer_selftest.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
