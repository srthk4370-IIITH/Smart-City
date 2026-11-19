"""v2 independent checks (pass 3, on the written files; verify_final.py is pass 2) -> final_v2/verify_v2.json.
  python3 v2_verify.py data/final_v2
v1 rows byte-identical; agt3 rows match the agent's real output + the window E-lines byte for byte + evidence-supported gold
(audit judge re-run); cross-floor link / upstream naming / negative controls; weak-type labels vs chain length; tool-choice
rows call the tool; prompt-only and evidence-signature overlap with every test/dev set (v1 tests + B.load_bans); in-set dups;
LF line endings. Exit 1 on any failure."""
import collections
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_rsn as B  # noqa: E402
import v2_gen as X  # noqa: E402
import v2_windows as W  # noqa: E402

D = sys.argv[1]
V1 = os.path.join(HERE, "data", "final")
res = collections.Counter()
fails = []


def bad(tag, rid):
    res["FAIL:" + tag] += 1
    if len(fails) < 50:
        fails.append([tag, rid])


def md5_prefix(path, nlines):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for i, l in enumerate(f):
            if i >= nlines:
                break
            h.update(l)
    return h.hexdigest()


for fn in ("train_new.jsonl", "replay.jsonl"):
    n1 = sum(1 for _ in open(os.path.join(V1, fn), "rb"))
    v1md5 = hashlib.md5(open(os.path.join(V1, fn), "rb").read()).hexdigest()
    if md5_prefix(os.path.join(D, fn), n1) != v1md5:
        bad("v1_rows_changed:" + fn, fn)
    res["v1_rows_identical:" + fn] = n1
for root, _, files in os.walk(D):
    for f in files:
        if f.endswith((".jsonl", ".json", ".md")):
            if b"\r\n" in open(os.path.join(root, f), "rb").read():
                bad("crlf", f)
# bans: all tests/dev (v1 tests + the older suites)
bu, be, bq, _ = B.load_bans()
for f in sorted(os.listdir(os.path.join(V1, "tests"))):
    for l in open(os.path.join(V1, "tests", f), encoding="utf-8"):
        r = json.loads(l)
        u = B.user_of(r)
        if r.get("tools", "").startswith("incident"):
            bu.add(B.h(u))
            be.add(B.ev_sig(u))
        for m in r["messages"]:
            if m["role"] == "user" and not r.get("tools", "").startswith("incident"):
                bq.add(B.h(m["content"]))
for f in sorted(x for x in os.listdir(os.path.join(D, "tests")) if x != "dev_p2.jsonl"):   # dev_p2 = part-2 gate rows (overlap checked by verify_final pass 2)
    if hashlib.md5(open(os.path.join(D, "tests", f), "rb").read()).hexdigest() != hashlib.md5(open(os.path.join(V1, "tests", f), "rb").read()).hexdigest():
        bad("test_changed", f)
wins = {json.loads(l)["wid"]: json.loads(l) for l in open(os.path.join(D, "work", "windows.jsonl"), encoding="utf-8")}
outs = {json.loads(l)["id"]: json.loads(l)["text"] for l in open(os.path.join(D, "work", "agent_out.jsonl"), encoding="utf-8")}
seen = set()
n1 = sum(1 for _ in open(os.path.join(V1, "train_new.jsonl"), "rb"))
for fn in ("train_new.jsonl", "replay.jsonl"):
    for i, l in enumerate(open(os.path.join(D, fn), encoding="utf-8")):
        r = json.loads(l)
        rid = r.get("id")
        u = B.user_of(r)
        k = B.h(u) + B.h(r["messages"][-1].get("content", ""))
        new = bool(r.get("v2_add"))
        inc = r.get("tools", "").startswith("incident")
        hits = []
        if k in seen:
            hits.append("dup")
        seen.add(k)
        if inc and (B.h(u) in bu or (B.ev_sig(u) in be and "S1.E1" in u)):
            hits.append("test_overlap_inc")
        if not inc and any(B.h(m["content"]) in bq for m in r["messages"] if m["role"] == "user"):
            hits.append("test_overlap_chat")
        for x in hits:
            if new:
                bad(x, rid)
            else:
                res["info_v1_inherited:%s:%s" % (fn, x)] += 1
        if not r.get("v2_add"):
            continue
        res["v2_rows:%s:%s" % (fn, r.get("block"))] += 1
        blk = r.get("block", "")
        rep = json.loads(r["messages"][-1]["content"]) if inc else None
        if blk == "v4_agt3":
            w, o = wins[r["window_id"]], X.parse_agent(outs[r["window_id"]])
            s1 = re.split(r"\n(?=S\d+ \[)", u.split("DOMAIN AGENT FINDINGS:\n", 1)[1])[0]
            el = re.findall(r"^  S1\.(E\d+) (.*)$", s1, re.M)
            if [list(x) for x in el] != [e for e in w["ev"]]:
                bad("agt3_elines", rid)
            if "agent data: " + X.agent_line(o) not in s1:
                bad("agt3_agent_line", rid)
            if not re.search(r"agent: pattern=%s status=%s " % (re.escape(str(o.get("pattern"))), o["status"]), s1):
                bad("agt3_agent_status", rid)
            if rep["severity"] != w["gold"]["status"]:
                bad("agt3_gold", rid)
            s, why = W.supported(w["role"], w["metric"], w["gold"], [x for x in w["head"] if x.startswith(("LIMITS:", "TANK:"))], w["ev"], w["n"], w["end_epoch"])
            if s != "y":
                bad("agt3_unsupported", rid)
            if o["status"] != w["gold"]["status"]:
                res["agt3_rows_agent_wrong"] += 1
                if not any(c.get("claim", "").startswith("status ") and c["verdict"] == "corrected" for c in rep["agent_checks"]):
                    bad("agt3_no_correction", rid)
            else:
                res["agt3_rows_agent_right"] += 1
        elif blk.startswith("v4_xfloor_"):
            xf = r["xfloor"]
            ll = re.search(r"^LINKS: (.*)$", u, re.M).group(1)
            vert = ("%s drains-to %s" % (xf["up"], xf["down"]) in ll) or ("%s below %s" % (xf["down"], xf["up"]) in ll)
            if xf["linked"] != vert:
                bad("xfloor_link", rid)
            if xf["linked"]:
                src = xf["up"] if blk.endswith("water") else xf["down"]
                if src not in rep["root_cause"] or src not in rep["causal_chain"]:
                    bad("xfloor_upstream_not_named", rid)
                if xf["floor_up"] == xf["floor_down"]:
                    bad("xfloor_same_floor", rid)
            elif "separate" not in rep["root_cause"]:
                bad("xfloor_negative", rid)
        elif blk.startswith("v4_weak_multihop"):
            hops = int(blk[-1])
            if r["reasoning_type"] != "multihop" or r["hops"] != hops or rep["causal_chain"].count("->") != hops:
                bad("weak_multihop_hops", rid)
        elif blk == "v4_weak_topup":
            if r["reasoning_type"] not in ("pair_who", "three_way", "transitive", "multihop", "pair_relation"):
                bad("weak_topup_type", rid)
            res["topup_type:%s:%s" % (r["reasoning_type"], r["hops"])] += 1
        elif blk.startswith("v4_weak_"):
            if r["reasoning_type"] != blk[len("v4_weak_"):]:
                bad("weak_type", rid)
        elif blk.startswith("v4_suspect_"):
            if "suspect_node" not in rep or rep["suspect_node"]["verdict"] not in ("confirmed", "rejected"):
                bad("suspect", rid)
            res["suspect:" + rep["suspect_node"]["verdict"]] += 1
        elif blk == "r5_toolchoice":
            names = {c["function"]["name"] for m in r["messages"] if m["role"] == "assistant" for c in (m.get("tool_calls") or [])}
            if not names & {"co_occurring_incidents", "fog_search_history"}:
                bad("toolchoice", rid)
res["fail_total"] = sum(v for k, v in res.items() if k.startswith("FAIL:"))
out = dict(sorted(res.items()))
out["fail_examples"] = fails
json.dump(out, open(os.path.join(D, "verify_v2.json"), "w", newline="\n"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "fail_examples"}))
sys.exit(1 if res["fail_total"] else 0)
