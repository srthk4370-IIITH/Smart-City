"""Verify every generated example; write the passing ones to data/<name>.ok.jsonl and print one summary line per file.
  py -3 -I verify.py data/incidents_train.jsonl [...]
Incident checks: schema/enums, whitelist, grounded numbers/times/dates, ids exist, title names the root sensor and agrees
with severity, units match the cited sensor, direction words match the cited trend sign, severity floor.
Chat checks: final answer numbers come from tool results/question, incident ids exist in tool results, read-only."""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import TITLE_WORDS  # noqa: E402
from prompts import ACTIONS, REPORT_LABELS  # noqa: E402

SEV = {"critical", "warning", "normal", "sensor_fault"}
VERD = {"corrected", "contradicted", "stale", "unsupported"}
KEYS = ["title", "severity", "label", "root_cause", "causal_chain", "observations", "agent_checks", "affected_domains",
        "suspect_sensors", "evidence", "confidence", "checklist", "monitor_next", "needs_more_data", "needs_deeper", "explanation"]
UNITS = ["ug/m3", "m3/h", "m/s", "ppm", "kW"]
STRIP = r"\b(?:S\d+\.E\d+|S\d+|E\d+|R\d+|H\d+|M\d+|INC-\d+|PM2\.5|PM10|CO2|11 kV|IS 10500|r2)\b"


def numset(text):
    out = set()
    for x in re.findall(r"[-+]?\d+(?:\.\d+)?", text):
        x = x.lstrip("+-")
        out.add(x)
        try:
            f = float(x)
            out.add(("%g" % f))
        except ValueError:
            pass
    return out


def text_fields(rep):
    t = [rep.get("title", ""), rep.get("root_cause", ""), rep.get("causal_chain", ""), rep.get("monitor_next", ""), rep.get("explanation", "")]
    t += [o.get("text", "") for o in rep.get("observations", [])]
    for ch in rep.get("agent_checks", []):
        t += [ch.get("fact", "")]
    t += [c.get("why", "") for c in rep.get("checklist", [])]
    return t


def check_incident(ex):
    errs = []
    msgs = ex["messages"]
    try:
        rep = json.loads(msgs[-1]["content"])
    except Exception:
        return ["json"]
    def dec(m):
        c = m.get("content") or ""
        if m["role"] == "tool":
            try:
                o = json.loads(c)
                if isinstance(o, dict) and isinstance(o.get("blocks"), list):
                    c = c + "\n" + "\n".join(o["blocks"])
                for it in (o.get("items") or []) if isinstance(o, dict) else []:
                    if isinstance(it, dict) and "id" in it:
                        c += "\n%s %s" % (it["id"], it.get("text", ""))
            except Exception:
                pass
        return c
    corpus = "\n".join(dec(m) for m in msgs[:-1])
    user = "\n".join(dec(m) for m in msgs[1:-1])
    for k in KEYS:
        if k not in rep:
            errs.append("key:" + k)
    if errs:
        return errs
    if rep["severity"] not in SEV:
        errs.append("sev_enum")
    if rep["label"] not in REPORT_LABELS:
        errs.append("label_enum")
    if not (1 <= len(rep["checklist"]) <= 5) or any(c["action"] not in ACTIONS for c in rep["checklist"]):
        errs.append("checklist")
    if not (2 <= len(rep["observations"]) <= 5):
        errs.append("obs_count")
    if any(c.get("verdict") not in VERD for c in rep["agent_checks"]) or len(rep["agent_checks"]) > 4:
        errs.append("checks")
    if any(not d or not isinstance(d, str) for d in rep["affected_domains"]) or not rep["affected_domains"]:
        errs.append("domains")
    # grounding (claims quote the agent, so they are not checked; facts are)
    cn = numset(re.sub(STRIP, " ", corpus))
    for t in text_fields(rep):
        t2 = re.sub(STRIP, " ", t)
        for tm in re.findall(r"\b\d\d:\d\d\b", t2):
            if tm not in corpus:
                errs.append("time:" + tm)
        for dd in re.findall(r"\b\d{4}-\d\d-\d\d\b", t2):
            if dd not in corpus:
                errs.append("date:" + dd)
        t3 = re.sub(r"\b\d\d:\d\d\b|\b\d{4}-\d\d-\d\d\b", " ", t2)
        for x in numset(t3):
            if x not in cn:
                errs.append("num:" + x)
                break
    ids = set()
    for o in rep["observations"]:
        ids |= set(o.get("src", []))
    ids |= set(rep["evidence"])
    for c in rep["agent_checks"]:
        ids |= set(c.get("src", []))
    for i in ids:
        if not re.search(r"(?<![\w.])%s(?![\d])" % re.escape(i), user):
            errs.append("id:" + i)
    if not (2 <= len(rep["evidence"]) <= 6):
        errs.append("evidence_count")
    # title
    meta = ex.get("meta", {})
    title = rep["title"].lower()
    if len(rep["title"]) > 80:
        errs.append("title_len")
    rm = meta.get("root_metric")
    if rm and rm in TITLE_WORDS and not any(w in title for w in TITLE_WORDS[rm]):
        errs.append("title_sensor")
    if rep["severity"] != "normal" and re.search(r"\bnormal\b|judged normal|\bfine\b", title) and "abnormal" not in title:
        errs.append("title_normal")
    # units and direction per observation
    for o in rep["observations"]:
        src = [s for s in o.get("src", []) if re.match(r"S\d+\.E\d+", s)]
        if not src:
            continue
        lines = [ln for ln in user.split("\n") if any(ln.strip().startswith(s + " ") for s in src)]
        blk = "\n".join(lines)
        ref = src[0].split(".")[0]
        hdr = [ln for ln in user.split("\n") if ln.startswith(ref + " [")]
        allowed = blk + "\n".join(hdr)
        for u in UNITS:
            if re.search(r"(?<![\w/])%s(?![\w])" % re.escape(u), o["text"]) and u not in allowed:
                errs.append("unit:" + u)
        e4 = [ln for ln in lines if re.match(r"\s*S\d+\.E4 trend", ln)]
        if e4 and " from " not in o["text"] and "between" not in o["text"].lower():
            neg = re.search(r"trend =? ?-", e4[0]) is not None
            if neg and re.search(r"\b(ris|climb|increas)", o["text"], re.I) and float(re.findall(r"[-+]?\d+(?:\.\d+)?", e4[0].split("trend", 1)[1])[0]) != 0:
                errs.append("direction")
            if not neg and re.search(r"\b(fall|dropp|decreas)", o["text"], re.I) and float(re.findall(r"[-+]?\d+(?:\.\d+)?", e4[0].split("trend", 1)[1])[0]) != 0:
                errs.append("direction")
    acts = [c["action"] for c in rep["checklist"]]
    if rep["severity"] == "critical" and not any(a.startswith("inspect_") or a == "request_facility_review" for a in acts):
        errs.append("floor_critical")
    if rep["severity"] == "sensor_fault" and acts[0] not in ("check_sensor", "recalibrate_sensor", "replace_sensor", "restart_or_reconnect_sensor"):
        errs.append("floor_fault")
    if not (0 <= rep["confidence"] <= 1):
        errs.append("conf")
    return errs


def check_chat(ex):
    errs = []
    msgs = ex["messages"]
    final = msgs[-1].get("content") or ""
    if msgs[-1]["role"] != "assistant" or not final:
        return ["final"]
    q = "\n".join(m.get("content") or "" for m in msgs if m["role"] == "user")
    tools = "\n".join(m.get("content") or "" for m in msgs if m["role"] == "tool")
    sysm = msgs[0]["content"]
    cn = numset(re.sub(STRIP, " ", q + "\n" + tools + "\n" + sysm))
    t = re.sub(STRIP, " ", final)
    t = re.sub(r"\b\d\d:\d\d\b|\b\d{4}-\d\d-\d\d\b", " ", t)
    for x in numset(t):
        if x not in cn:
            errs.append("num:" + x)
            break
    for inc in re.findall(r"INC-\d+", final):
        if inc not in tools and inc not in q:
            errs.append("inc:" + inc)
    for m in msgs:
        for tc in m.get("tool_calls") or []:
            if tc["function"]["name"] not in ex.get("tool_names", [tc["function"]["name"]]):
                errs.append("tool_name")
    for m in msgs:
        if m["role"] == "tool":
            try:
                if "error" in json.loads(m["content"]):
                    errs.append("tool_error")
            except Exception:
                errs.append("tool_json")
    return errs


def main():
    for path in sys.argv[1:]:
        rows = [json.loads(l) for l in open(path, encoding="utf-8")]
        ok, bad = [], collections.Counter()
        for ex in rows:
            e = check_incident(ex) if ex.get("tools") == "incident" else check_chat(ex)
            if e:
                for x in set(x.split(":")[0] for x in e):
                    bad[x] += 1
                if os.environ.get("SHOW"):
                    print(ex["id"], ex["family"], e[:4])
            else:
                ok.append(ex)
        out = path.replace(".jsonl", ".ok.jsonl")
        with open(out, "w", encoding="utf-8") as f:
            for ex in ok:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        print("%s: %d/%d pass (%.1f%%) fails=%s" % (os.path.basename(path), len(ok), len(rows), 100.0 * len(ok) / max(1, len(rows)), dict(bad.most_common(8))))


if __name__ == "__main__":
    main()
