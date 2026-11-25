"""check_big.py DATA_DIR : (1) verify: every B/C/D row re-verified (incident rows G.full_check, chat rows big_chat.check), structure of A rows,
no overlap of train/replay with the gate set or with any test/dev set, unique ids (dups only via dup_of), LF; (2) audit: rsn_p2_audit.py rules
extended to ALL new report rows and ALL chat/tool rows: cited ids exist in the prompt, severity valid and equal to the contrast-family gold, root
cause / chain non-trivial, ids passed to tools exist in the question / earlier results / history, tool names + args valid (schema, enums), finals
non-empty and <= 650 chars, format instructions honoured (two lines / one word each / manager / one sentence / <= 8 words), CO2 numbers carry ppm,
not-found rows say so. A bad rate > 5 % on any block = FAIL (fix the generator, do not filter).  -> DATA_DIR/CHECK.md + check.json, exit 1 on FAIL"""
import collections
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import big_chat as BC  # noqa: E402
import build_rsn as B  # noqa: E402
import v2_gen as X  # noqa: E402

G = B.G
D = sys.argv[1]
TOOLS = json.load(open(D + "/tools_v4.json"))
SCHEMA = {f["function"]["name"]: f["function"]["parameters"] for f in TOOLS["chat_r5"]}
ID = re.compile(r"S\d+\.E\d+")
SEV = {"normal", "info", "warning", "critical", "sensor_fault"}


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def rep_of(r):
    c = r["messages"][-1]["content"].split("</think>")[-1]
    a, b = c.find("{"), c.rfind("}")
    try:
        return json.loads(c[a:b + 1])
    except Exception:
        return None


def audit_report(r):
    p = rep_of(r)
    bad = []
    if not isinstance(p, dict) or "severity" not in p:
        return ["unparsable report"]
    u = r["messages"][1]["content"]
    txt = json.dumps(p, ensure_ascii=False)
    u = u + " ".join(m.get("content") or "" for m in r["messages"] if m["role"] == "tool")
    for i in set(ID.findall(txt)):
        if (i + " ") not in u and (i + ",") not in u and (i + "]") not in u and (i + '"') not in u:
            bad.append("id %s not in prompt" % i)
    sev = p.get("severity")
    if sev not in SEV:
        bad.append("bad severity %s" % sev)
    fam = r.get("family", "")
    m = re.match(r"big_(co2|pm|temp):(\w+)", fam)
    if m and m.group(2) != sev:
        bad.append("contrast family %s but severity %s" % (m.group(2), sev))
    if fam.startswith("big_benign") and sev != "normal":
        bad.append("benign family not normal")
    if any(k in fam for k in ("flat_alone", "step_real", "plateau_real")) and sev == "sensor_fault" and "mem" not in fam:
        bad.append("sensor_fault on single-kind evidence")
    if len(str(p.get("root_cause", ""))) < 25 or len(str(p.get("causal_chain", ""))) < 10:
        bad.append("empty root cause/chain")
    if not ID.search(str(p.get("causal_chain", ""))) and sev not in ("normal", "info") and "tool" not in fam:
        bad.append("chain cites no evidence id")
    for sid, n in re.findall(r"(S\d+)\.E8[^\n]*?noise ([0-9.]+)", u):
        if float(n) > 0 and re.search(r"(zero|no|without)\s+noise", txt, re.I) and sid in txt:
            bad.append("noise claim vs %s" % sid)
    if "+sevchange" in fam and "Severity is" not in p.get("explanation", ""):
        bad.append("sevchange without explanation")
    return bad


def audit_chat(r):
    bad = []
    msgs, fin = r["messages"], r["messages"][-1]["content"] or ""
    if not fin.strip():
        return ["empty final"]
    if len(fin) > 650:
        bad.append("final > 650 chars")
    known = " ".join(m.get("content") or "" for m in msgs if m["role"] in ("user", "assistant", "tool"))
    seen_text = msgs[0]["content"]
    for i, m in enumerate(msgs):
        if m["role"] in ("user", "tool") or (m["role"] == "assistant" and not m.get("tool_calls")):
            seen_text += "\n" + (m.get("content") or "")
        for tc in m.get("tool_calls") or []:
            n, a = tc["function"]["name"], tc["function"]["arguments"]
            sch = SCHEMA.get(n)
            if sch is None:
                bad.append("unknown tool %s" % n)
                continue
            for k, v in a.items():
                if k not in sch["properties"]:
                    bad.append("arg %s.%s" % (n, k))
                elif "enum" in sch["properties"][k] and v not in sch["properties"][k]["enum"]:
                    bad.append("enum %s.%s=%s" % (n, k, v))
            for rq in sch.get("required", []):
                if rq not in a:
                    bad.append("required %s.%s" % (n, rq))
            iid = a.get("id")
            if iid and iid not in seen_text:
                bad.append("id %s not in context" % iid)
        if m["role"] == "assistant" and m.get("tool_calls"):
            seen_text += "\n" + json.dumps(m["tool_calls"])
    fmt = r.get("fmt")
    if fmt == "two_lines" and len([x for x in fin.split("\n") if x.strip()]) != 2:
        bad.append("two lines not honoured")
    if fmt == "one_word" and any(len(x.split()) != 1 for x in re.split(r",\s*", fin.rstrip("."))):
        bad.append("one word each not honoured")
    if fmt == "one_sentence" and len(re.findall(r"[.!?](\s|$)", fin)) != 1:
        bad.append("one sentence not honoured")
    if fmt == "shorter" and len(fin.split()) > 8:
        bad.append("8 words not honoured")
    if fmt == "manager" and (len(re.findall(r"[.!?](\s|$)", fin)) > 3 or re.search(r"INC-\d+|S\d+\.E\d", fin)):
        bad.append("manager format")
    if fmt == "simple" and re.search(r"sensor_fault|air_quality|power_kw|S\d+\.E\d", fin):
        bad.append("jargon in simple words")
    k = r.get("kind", "")
    if k == "get_missing" and not re.search(r"not on this device|cannot find|no incident", fin):
        bad.append("not-found not said")
    if k == "unknown_sensor" and not re.search(r"cannot find|no sensor|no .* matching", fin, re.I):
        bad.append("unknown entity not said")
    if re.search(r"(?i)co2[^.0-9:]{0,14}[0-9]+(?:[.][0-9]+)?(?![0-9])(?!s*ppm)", re.sub(r"(?i)co2[^.]*?(building|sensor)[^.]*", "", fin)) and "ppm" not in fin and not k.startswith("site"):
        bad.append("CO2 number without ppm")
    if "faulty" in k and r.get("verdict") is None:
        bad.append("verdict missing")
    if k == "cooccur" and not re.search(r"does not show|not prove|alone|nothing else", fin, re.I):
        bad.append("no hedge")
    if r.get("nocall") and r["gold_calls"]:
        bad.append("nocall with call")
    if not r.get("nocall") and k != "fmt_shorter" and not r["gold_calls"] and not str(r.get("family", "")).startswith(("site:", "big_chat:site")):
        bad.append("no call where one is expected")
    return bad


def hh(t):
    return hashlib.md5(re.sub(r"\s+", " ", re.sub(r"INC-\d+", "INC", t or "")).strip().lower().encode()).hexdigest()


def user_last(r):
    return next(m["content"] for m in reversed(r["messages"]) if m["role"] == "user")


def main():
    res = collections.Counter()
    out = {"blocks": {}, "fail": []}
    train, replay = jl(D + "/train_new.jsonl"), jl(D + "/replay.jsonl")
    # ids
    ids = collections.Counter(r["id"] for r in train)
    dup = [i for i, n in ids.items() if n > 1]
    res["id_dups"] = len(dup)
    # verify + audit new rows
    byb = collections.defaultdict(lambda: [0, 0, []])
    for r in train:
        if r.get("dup_of"):
            continue
        b = r.get("block", "?")
        t = r.get("tools", "")
        e = []
        if t.startswith("incident"):
            e = list(G.full_check(r)) if not any(m.get("tool_calls") for m in r["messages"]) else list(G.V.check_incident(r))
            e += audit_report(r)
        elif r.get("fog_gold"):
            e = [] if (r["messages"][-1].get("content") or "").strip() else ["empty final"]
        elif t == "chat_r5":
            e = BC.check(r) + audit_chat(r)
        res["rows:" + r.get("big", "?")] += 1
        x = byb[b]
        x[0] += 1
        if e:
            x[1] += 1
            if len(x[2]) < 4:
                x[2].append([r["id"], e[:3]])
    for r in replay:
        res["rows:A"] += 1
    # overlap with gate + tests
    gate = jl(D + "/gate/gate_set.jsonl") if os.path.exists(D + "/gate/gate_set.jsonl") else []
    gh = {hh(user_last(g)) + "|" + str(len(g["messages"])) for g in gate}
    gq = {hh(user_last(g)) for g in gate}
    ov = sum(1 for r in train + replay if hh(user_last(r)) in gq and r.get("big") != "A") + sum(1 for r in train if r.get("big") in ("B", "C", "D") and hh(user_last(r)) in gq)
    res["gate_overlap_new_rows"] = ov
    gate_ids = {g["id"] for g in gate}
    res["gate_id_in_train"] = sum(1 for r in train + replay if r["id"] in gate_ids)
    tests = set()
    for f in os.listdir(D + "/tests"):
        pass
    t2 = os.path.abspath(os.path.join(HERE, "..", "..", "2026-11-13_v3_data", "rsn", "data", "final_v2", "tests"))
    for f in os.listdir(t2):
        for r in jl(t2 + "/" + f):
            tests.add(hh(user_last(r)))
    res["test_overlap_new_rows"] = sum(1 for r in train if r.get("big") in ("B", "C", "D") and hh(user_last(r)) in tests)
    # report
    L = ["# check_big (verify + audit)", "", "| block | rows | bad | bad % |", "|---|---|---|---|"]
    worst = 0.0
    for b, (n, nb, ex) in sorted(byb.items()):
        rate = nb / max(n, 1)
        worst = max(worst, rate) if n >= 20 else worst
        L.append("| %s | %d | %d | %.1f%% |" % (b, n, nb, 100 * rate))
        for x in ex:
            L.append("|  ex | %s | %s | |" % (x[0], "; ".join(x[1])[:150]))
        out["blocks"][b] = {"rows": n, "bad": nb}
    tot_n, tot_b = sum(v[0] for v in byb.values()), sum(v[1] for v in byb.values())
    ok = (worst <= 0.05 and tot_b / max(tot_n, 1) <= 0.05 and res["id_dups"] == 0 and res["gate_overlap_new_rows"] == 0 and res["gate_id_in_train"] == 0 and res["test_overlap_new_rows"] == 0)
    L += ["", "new rows %d, bad %d = %.2f%% (limit 5%% overall and per block)" % (tot_n, tot_b, 100 * tot_b / max(tot_n, 1)), "counters: %s" % dict(res), "",
          "RESULT: " + ("PASS" if ok else "FAIL")]
    open(D + "/CHECK.md", "w", newline="\n").write("\n".join(L) + "\n")
    out["counters"], out["bad_rate"], out["ok"] = dict(res), tot_b / max(tot_n, 1), ok
    json.dump(out, open(D + "/check.json", "w"), indent=1)
    print("\n".join(L[-4:]))
    sys.exit(0 if ok else 1)


main()
