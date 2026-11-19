"""Independent second pass over the written files: every row re-verified; think rules; v4 format rules; train/test overlap.
  python3 verify_final.py data/final -> data/final/verify.json"""
import collections
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_inc_v4 as G  # noqa: E402
import gen_chat_v4 as C  # noqa: E402

D = sys.argv[1]
res = collections.Counter()


def h(t):
    return hashlib.md5(re.sub(r"\s+", " ", re.sub(r"INC-\d+", "INC", t)).strip().lower().encode()).hexdigest()


def roles_flagged(u):
    return set(re.findall(r"^S\d+ \[FLAGGED\]: .*\((\w+)\)$", u, re.M))


def chk(path, tag):
    hs = set()
    for l in open(path, encoding="utf-8"):
        r = json.loads(l)
        t = r.get("tools")
        res["%s:rows" % tag] += 1
        u = next(m["content"] for m in r["messages"] if m["role"] == "user")
        hs.add(h(u + "\x00" + (r["messages"][-1].get("content") or "")))
        if t == "incident_v4":
            e = G.full_check(r)
            th = r["messages"][-1].get("reasoning_content")
            multi = len(roles_flagged(u)) >= 2
            res["%s:inc_think_%s" % (tag, "multi_ok" if (multi and th) else "single_empty_ok" if (not multi and not th) else "BAD")] += 1
        elif t == "chat_r5" and "gold_facts" not in r:
            e = C.check_row(dict(r, hard=bool(r.get("hard")))) if r.get("family", "").startswith("site:") else G.V.check_chat(dict(r, tools="chat"))
            lu = max(i for i, m in enumerate(r["messages"]) if m["role"] == "user")
            after = r["messages"][lu + 1:]
            if not r.get("hard") and any(m.get("reasoning_content") for m in after):
                e = list(e) + ["easy_think"]
            if any(m.get("reasoning_content") for m in after if m["role"] == "assistant" and not m.get("tool_calls")):
                e = list(e) + ["think_after_tool_final"]
        elif t == "incident":
            e = G.V.check_incident(r)
        elif t == "chat" and "gold_facts" not in r:
            e = G.V.check_chat(r)
        else:
            e = []
        if t == "incident_v4" and re.search(r"\n  (LIMITS|TANK):", u):
            e = list(e) + ["old_head"]
        if e:
            for x in set(z.split(":")[0] for z in e):
                res["%s:FAIL:%s" % (tag, x)] += 1
    return hs


train = chk(os.path.join(D, "train_new.jsonl"), "train_new") | chk(os.path.join(D, "replay.jsonl"), "replay")
for f in sorted(os.listdir(os.path.join(D, "tests"))):
    th = chk(os.path.join(D, "tests", f), "tests/" + f)
    res["tests/%s:overlap_with_train" % f] = len(th & train)
json.dump(dict(sorted(res.items())), open(os.path.join(D, "verify.json"), "w"), indent=1)
print(json.dumps(dict(sorted(res.items())), indent=0))
