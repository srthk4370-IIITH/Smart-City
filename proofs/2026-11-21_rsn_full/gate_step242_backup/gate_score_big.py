"""gate_score_big.py GATE_SET RES_P2_DIR RES_NEW_DIR -> JSON {p2:{...}, new:{...}} per slice and per sub-slice.
Slices: report_all (40 report rows, sub-slice = source test set), new_family (30: dev_p2 + fresh big families), chat_en (40), tool_chain (20).
Report rows: valid JSON, severity == gold, hygiene (cited ids S<n>.E<n> that are lines of the prompt; sensor_fault only when gold is sensor_fault),
acc = severity and hygiene.  Chat rows (live tools, see gate_run_chat.py): calls = tool-name sequence == gold; args = every id / node / metric / domain /
severity / preset argument of the gold calls equal; nonempty final; grounded = every number / INC id of the final is in the system, the questions, the tool
results or earlier assistant turns; short = <= 3 sentences (format kinds: their own rule); fmt = asked format honoured; verdict / hedge / not-found
checks per kind; ok = all applicable checks."""
import collections
import json
import os
import re
import sys

GS, RP, RN = sys.argv[1], sys.argv[2], sys.argv[3]
rows = {}
for l in open(GS, encoding="utf-8"):
    if l.strip():
        r = json.loads(l)
        rows[r["id"]] = r


def rep_of(final):
    if isinstance(final, dict):
        final = final.get("content") or ""
    t = final or ""
    i = t.find("{")
    while i >= 0:
        try:
            return json.loads(t[i:t.rfind("}") + 1])
        except Exception:
            i = t.find("{", i + 1)
    return None


def text_of(final):
    return (final.get("content") if isinstance(final, dict) else final) or ""


def score_report(r, o):
    g = rep_of(r["messages"][-1]["content"])
    u = r["messages"][1]["content"]
    p = rep_of(o.get("final"))
    ids = []
    if p:
        ids = list(p.get("evidence") or []) + [i for ob in (p.get("observations") or []) if isinstance(ob, dict) for i in (ob.get("src") or [])] + \
              [i for c in (p.get("agent_checks") or []) if isinstance(c, dict) for i in (c.get("src") or [])]
    sev = bool(p) and p.get("severity") == g["severity"]
    hyg = bool(p) and all(re.fullmatch(r"S\d+\.E\d+", str(i)) and (str(i) + " ") in u for i in ids) and (p.get("severity") != "sensor_fault" or g["severity"] == "sensor_fault")
    return {"valid": bool(p), "sev": sev, "hyg": hyg, "ok": sev and hyg}


NUM = re.compile(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w])")
GK = ("id", "node", "metric", "domain", "severity", "link", "direction", "analysis")


def gold_calls(r):
    return [(c["name"], c["args"]) for c in r.get("gold_calls") or []]


def argeq(g, c):
    for k in GK:
        if k in g and g[k] != c.get(k):
            return False
    if "time" in g and (g["time"].get("preset") or g["time"].get("from")) != ((c.get("time") or {}).get("preset") or (c.get("time") or {}).get("from")):
        return False
    return True


def score_chat(r, o):
    fin = text_of(o.get("final")).strip()
    calls = [(c["name"], c["args"] if isinstance(c["args"], dict) else {}) for c in o["calls"]]
    gc = gold_calls(r)
    k = r.get("kind") or ""
    seq = [n for n, _ in calls] == [n for n, _ in gc]
    args = seq and all(argeq(g[1], c[1]) for g, c in zip(gc, calls)) if gc else not calls
    ctx = " ".join(m.get("content") or "" for m in r["messages"] if m["role"] in ("system", "user", "assistant") and not m.get("tool_calls"))
    ctx += " " + " ".join(json.dumps(c["result"]) for c in o["calls"])
    nums = [x for x in NUM.findall(re.sub(r"\b\d\d:\d\d\b|\b\d{4}-\d\d-\d\d\b", " ", fin))]
    grounded = all(x in ctx for x in nums) and all(i in ctx for i in re.findall(r"INC-\d+", fin))
    sents = len(re.findall(r"[.!?](\s|$)", fin))
    fmt = r.get("fmt")
    short = sents <= 3 and len(fin) <= 650
    fok = True
    if fmt == "two_lines":
        fok = len([x for x in fin.split("\n") if x.strip()]) == 2
    elif fmt == "one_word":
        fok = all(len(x.split()) == 1 for x in re.split(r",\s*", fin.rstrip(".")))
    elif fmt == "one_sentence":
        fok = sents == 1
    elif fmt == "shorter":
        fok = len(fin.split()) <= 8
    elif fmt == "manager":
        fok = sents <= 3 and not re.search(r"INC-\d+", fin)
    elif fmt == "simple":
        fok = not re.search(r"sensor_fault|air_quality|power_kw|S\d+\.E\d", fin)
    if fmt:
        short = True
    extra = True
    v = r.get("verdict")
    if v:
        kw = {"fault": r"fault|not credible|implausible|broken", "people": r"fine|in use|occupied|follow", "empty": r"empty|expected|unused|no fault|nothing suggests", "flat": r"stuck|barely|check"}[v]
        extra = bool(re.search(kw, fin, re.I))
    if k == "cooccur":
        extra = bool(re.search(r"does not|not show|not prove|alone|coincid|may|nothing else|no other", fin, re.I))
    if k in ("get_missing", "unknown_sensor", "site_unknown"):
        extra = bool(re.search(r"not on this device|cannot find|no incident|no sensor|no node|not find|there is no|could not|can't find|no such", fin, re.I))
    if k == "forecast":
        extra = bool(re.search(r"no forecast|cannot|can't|not able|trend|only", fin, re.I))
    if r.get("nocall"):
        args = not calls
    ok = bool(fin) and seq and args and grounded and short and fok and extra
    return {"nonempty": bool(fin), "calls": seq, "args": bool(args), "grounded": grounded, "short": short, "fmt": fok, "extra": extra, "ok": ok}


def load(d):
    out = {}
    for f in os.listdir(d) if os.path.isdir(d) else []:
        if f.endswith(".jsonl"):
            for l in open(os.path.join(d, f)):
                o = json.loads(l)
                out[o["id"]] = o
    return out


def sub_of(r):
    if r["slice"] == "report_all":
        return r.get("src_test", "?")
    if r["slice"] == "new_family":
        return r.get("big_family") or ("dev_p2:" + str(r.get("p2_family", "?")).replace("p2_", ""))
    return r.get("kind") or "?"


def run(d):
    res = load(d)
    S = collections.defaultdict(lambda: collections.Counter())
    for rid, r in rows.items():
        o = res.get(rid)
        sl = r["slice"]
        if o is None:
            S[(sl, "ALL")]["missing"] += 1
            continue
        m = score_report(r, o) if sl in ("report_all", "new_family") else score_chat(r, o)
        for key in ((sl, "ALL"), (sl, sub_of(r))):
            S[key]["n"] += 1
            for kk, vv in m.items():
                S[key][kk] += bool(vv)
    out = {}
    for (sl, sub), c in sorted(S.items()):
        n = max(c["n"], 1)
        out.setdefault(sl, {})[sub] = {"n": c["n"], "missing": c["missing"], **{k: round(v / n, 4) for k, v in c.items() if k not in ("n", "missing")}}
    return out


print(json.dumps({"p2": run(RP), "new": run(RN)}))
