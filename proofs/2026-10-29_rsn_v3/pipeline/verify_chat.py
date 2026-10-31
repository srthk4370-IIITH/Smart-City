"""Verifier for rsn_v3 chat outputs (teacher samples in self-distillation, also usable on student outputs).

verify(record, candidate, executor=None, require_think_hard=False) -> {"pass", "reasons", "warnings", "calls", "final", "think_tokens"}

candidate forms
- str: one assistant turn, or a rendered transcript (Qwen "<|im_start|>assistant ... <tool_response>" text);
- list of str: one string per assistant round (tool-call rounds, then the final answer);
- list of message dicts (role assistant: content, tool_calls, reasoning_content; role tool: content);
- {"turns": [...]} with any of the above.
Inside a turn: optional <think>...</think> (or reasoning_content), then Qwen3.5 XML tool calls
(<tool_call><function=NAME><parameter=K>V</parameter></function></tool_call>, as chat.go renders them) or JSON tool
calls (<tool_call>{"name":..,"arguments":{..}}</tool_call>), or the final text.

checks (reason codes)
- call_parse            a <tool_call> block that does not parse
- too_many_calls        more than 5 tool calls
- missing_call:NAME     a gold call without a matching candidate call (same name, every required arg equal after
                        normalisation: time presets resolved to ranges, severities as sets, ids upper-case, strings
                        case-insensitive, numbers as floats, omitted args = tool default). With an executor, a call whose
                        args differ but whose result is identical (query_id ignored) also matches.
- unexpected_call / extra_calls   calls when the gold has none; more than one unmatched extra call otherwise
- no_final / final_markup / too_long (> 650 chars)
- invented_id:X / invented_time:X / invented_num:X   ids, dates/times and numbers in the final answer that are not in
                        the question, history, system prompt, gold call args or tool results (gold results + the
                        candidate's own results when given or executable). Integers 0-3 are allowed (small counts).
- unit_mismatch:X U     a number that the tool results pair with another unit
- missing_fact:...      a gold fact absent from the final answer: num (rounding to the written precision allowed;
                        0 also as no/none/zero), num_any (at least k of the listed numbers), id, unit, phrase (any of), date
- no_refusal            must_refuse record without a refusal
- actuation_claim       the answer claims it switched/closed/approved/... something
- think_too_long:N      hard record with > 80 think tokens (any round); think_not_empty: non-hard record with think
  (warning think_missing when a hard record has no think; a failure with require_think_hard=True)

Self-test: python3 verify_chat.py --selftest [--data ../data] [--n 0]
  reference answers (rendered as candidates) must all pass; corrupted variants must all fail.
Batch:     python3 verify_chat.py --records chat3_dev.jsonl --cands teacher.jsonl   (cands: {"id", "output"} per line)
"""
import argparse
import collections
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MAX_CALLS, MAX_CHARS, THINK_MAX = 5, 650, 80
FREE_ARGS = {"limit", "k", "query", "agg", "stats_only", "detail"}
DEFAULTS = {"rank_readings": {"time": {"preset": "today"}, "order": "highest", "limit": 3, "include_faulty": True},
            "faulty_sensors": {"time": {"preset": "last_7d"}}, "what_if": {"time": {"preset": "last_7d"}},
            "recent_incidents": {"limit": 5}, "find_incidents": {"limit": 5}, "count_incidents": {"group_by": "none", "include_injected": False},
            "get_sensor_history": {"agg": "hourly", "stats_only": True}, "get_incident": {"detail": "summary"}}
IDRX = re.compile(r"\b(?:INC-\d+|[A-Za-z]{2,}(?:-[A-Za-z0-9]+)+)\b", re.I)   # ids must also contain a digit (_ids)
STRIP = re.compile(r"\b(?:INC-\d+|[A-Za-z]{2,}(?:-[A-Za-z0-9]+)+|PM ?2\.5|PM ?10|CO2|r2|r²|0/1|m3/h|ug/m3|µg/m³|μg/m³|m³/h|11 ?kV|IS 10500|"
                   r"[A-Za-z]+\d+[A-Za-z0-9]*)\b", re.I)
DATE = re.compile(r"\b\d{4}-\d\d-\d\d\b")
TIME = re.compile(r"\b\d{1,2}:\d\d\b")
NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?")
SRC_NUM = re.compile(r"\d+(?:\.\d+)?")          # sources: also digits glued to words (last_7d, KH03)
UNIT_RX = r"(ppm|ug/m3|µg/m³|μg/m³|µg/m3|μg/m3|kW|m3/h|m³/h|m/s|°C|C|%|units?|pH)"
NUM_UNIT = re.compile(r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*" + UNIT_RX + r"(?![A-Za-z0-9/])"
                      r"(?!\s+(?:incidents?|alerts?|alarms?|sensors?|probes?|readings?|faults?)\b)")   # "15 pH incidents" is a count
UNORM = {"µg/m³": "ug/m3", "μg/m³": "ug/m3", "µg/m3": "ug/m3", "μg/m3": "ug/m3", "m³/h": "m3/h", "°C": "C", "unit": "units"}
REFUSAL = re.compile(r"\b(can't|cannot|can not|unable|not able|won't|do not have|don't have|read-only|only (?:read|answer|help)|"
                     r"outside (?:what|my|the scope)|not something I|isn't something|decline|sorry|needs? an operator|needs operator|not allowed)\b", re.I)
ACTUATION = re.compile(r"\b(?:I(?:'ve| have| just| already)?|we(?:'ve| have)?)\s+(?:now\s+)?(?:switched|turned|closed|approved|dismissed|deleted|restarted|"
                       r"shut|opened|reset|acknowledged|resolved|marked|set|started|stopped|activated|deactivated)\b|"
                       r"\b(?:has|have) been (?:switched|turned|shut|closed|approved|dismissed|deleted|restarted)\b|^\s*(?:done|ok,? done)\b", re.I)


def unorm(u):
    return UNORM.get(u, u)


def think_tokens(t):
    """approximate Qwen tokens: words (long words count 2), single digits, punctuation"""
    if not t:
        return 0
    n = 0
    for w in re.findall(r"[A-Za-z]+|\d|[^\sA-Za-z\d]", t):
        n += 2 if len(w) > 8 else 1
    return n


# ------------------------------------------------------------------------------------------------ candidate parsing
def _val(v):
    v = v.strip()
    try:
        return json.loads(v)
    except Exception:
        return v


def parse_calls(text):
    calls, err = [], False
    for blk in re.findall(r"<tool_call>(.*?)</tool_call>", text, re.S):
        m = re.search(r"<function=([^>\s]+)>(.*?)</function>", blk, re.S)
        if m:
            args = {k: _val(v) for k, v in re.findall(r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>", m.group(2), re.S)}
            calls.append({"name": m.group(1).strip(), "args": args})
            continue
        try:
            o = json.loads(blk.strip())
            a = o.get("arguments", o.get("parameters", {}))
            if isinstance(a, str):
                a = json.loads(a)
            calls.append({"name": o["name"], "args": a})
        except Exception:
            err = True
    if text.count("<tool_call>") != len(re.findall(r"<tool_call>(.*?)</tool_call>", text, re.S)):
        err = True
    return calls, err


def split_think(text):
    m = re.search(r"<think>(.*?)</think>", text, re.S)
    if m:
        return m.group(1).strip(), (text[:m.start()] + text[m.end():]).strip()
    if "</think>" in text:
        a, b = text.split("</think>", 1)
        return a.replace("<think>", "").strip(), b.strip()
    return "", text.strip()


def parse_turn(text):
    th, rest = split_think(text or "")
    calls, err = parse_calls(rest)
    final = re.sub(r"<tool_call>.*?</tool_call>", "", rest, flags=re.S).strip()
    return {"think": th, "calls": calls, "text": final if not calls else "", "err": err, "results": []}


def parse_candidate(c):
    if isinstance(c, dict) and "turns" in c:
        return parse_candidate(c["turns"])
    if isinstance(c, str):
        if "<|im_start|>" in c or "<tool_response>" in c:
            turns = []
            for seg in re.split(r"<\|im_start\|>", c):
                seg = seg.replace("<|im_end|>", "")
                if seg.startswith("assistant"):
                    turns.append(parse_turn(seg[len("assistant"):]))
                elif "<tool_response>" in seg and turns:
                    for r in re.findall(r"<tool_response>\s*(.*?)\s*</tool_response>", seg, re.S):
                        turns[-1]["results"].append(r)
            return turns
        return [parse_turn(c)]
    turns = []
    for x in c:
        if isinstance(x, str):
            turns.append(parse_turn(x))
        elif isinstance(x, dict):
            if x.get("role") == "tool":
                if turns:
                    turns[-1]["results"].append(x.get("content") or "")
                continue
            if x.get("role") not in (None, "assistant"):
                continue
            t = parse_turn((("<think>%s</think>" % x["reasoning_content"]) if x.get("reasoning_content") else "") + (x.get("content") or ""))
            for tc in x.get("tool_calls") or []:
                f = tc.get("function", tc)
                a = f.get("arguments", {})
                if isinstance(a, str):
                    try:
                        a = json.loads(a)
                    except Exception:
                        t["err"] = True
                        a = {}
                t["calls"].append({"name": f.get("name"), "args": a})
            if t["calls"]:
                t["text"] = ""
            turns.append(t)
    return turns


def render_calls(calls):
    """chat.go format"""
    out = []
    for c in calls:
        s = "<tool_call>\n<function=%s>\n" % c["name"]
        for k, v in c["args"].items():
            s += "<parameter=%s>\n%s\n</parameter>\n" % (k, v if isinstance(v, str) else json.dumps(v))
        out.append(s + "</function>\n</tool_call>")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ call matching
def _time_eq(a, b):
    try:
        from tools_impl import resolve_time
        return resolve_time(a if not isinstance(a, str) else {"preset": a}) == resolve_time(b if not isinstance(b, str) else {"preset": b})
    except Exception:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _eq(k, a, b):
    if a is None or b is None:
        return a is None and b is None
    if k == "time":
        return _time_eq(a, b)
    if k == "severity":
        sa = {a} if isinstance(a, str) else set(a)
        sb = {b} if isinstance(b, str) else set(b)
        return sa == sb
    if isinstance(a, bool) or isinstance(b, bool):
        return str(a).lower() == str(b).lower()
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def args_match(name, gold, req, cand):
    d = DEFAULTS.get(name, {})
    for k in req:
        if not _eq(k, gold[k], cand.get(k, d.get(k))):
            return False
    for k, v in cand.items():
        if k in FREE_ARGS or k in gold:
            continue
        if k in d and _eq(k, v, d[k]):
            continue
        return False
    return True


def _strip_qid(r):
    if isinstance(r, str):
        try:
            r = json.loads(r)
        except Exception:
            return r
    if isinstance(r, dict):
        r = {k: v for k, v in r.items() if k != "query_id"}
    return json.dumps(r, sort_keys=True)


def _exec(ex, c):
    ex.qid = 0
    return ex.run(c["name"], c["args"])


# ------------------------------------------------------------------------------------------------ grounding helpers
def _ids(text):
    return [i for i in IDRX.findall(text) if re.search(r"\d", i)]


def _nums(text, rx=NUM):
    out = []
    for x in rx.findall(text):
        try:
            out.append((x.lstrip("+-"), abs(float(x))))
        except ValueError:
            pass
    return out


def _clean(text):
    t = STRIP.sub(" ", text)
    t = DATE.sub(" ", t)
    return TIME.sub(" ", t)


def _grounded(xs, xf, src_strs, src_vals):
    if xs in src_strs:
        return True
    if "." not in xs and xf <= 3:
        return True
    d = len(xs.split(".")[1]) if "." in xs else 0
    if d == 0 and xf < 10:
        return any(abs(v - xf) < 1e-9 for v in src_vals)
    tol = 0.5 * 10 ** (-d) + 1e-9
    return any(abs(v - xf) <= tol for v in src_vals)


def _pairs(o, acc, unit=None):
    if isinstance(o, dict):
        u = o.get("unit", unit) if isinstance(o.get("unit", unit), str) else unit
        for k, v in o.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and k in ("value", "last", "now", "after", "min", "max", "mean",
                                                                                   "driver_now", "driver_after", "warning", "critical"):
                if u:
                    acc[abs(float(v))].add(unorm(u))
            elif isinstance(v, (dict, list)):
                _pairs(v, acc, u)
            elif isinstance(v, str) and k == "text":
                for n, uu in NUM_UNIT.findall(v):
                    acc[abs(float(n))].add(unorm(uu))
    elif isinstance(o, list):
        for x in o:
            _pairs(x, acc, unit)


def _fact_ok(f, final, fnums):
    t = f.get("t")
    low = final.lower()
    if t == "num_any":
        k = f.get("k", 1)
        return sum(_fact_ok({"t": "num", "v": v}, final, fnums) for v in f["v"]) >= min(k, len(f["v"]))
    if t == "num":
        v = abs(float(f["v"]))
        if v == 0 and re.search(r"\b(no|none|zero|nothing|0)\b", low):
            return True
        for xs, xf in fnums:
            d = len(xs.split(".")[1]) if "." in xs else 0
            if d > 0 and abs(xf - v) <= 0.5 * 10 ** (-d) + 1e-9:
                return True
            if d == 0 and (abs(xf - v) < 1e-9 or (v >= 10 and abs(xf - v) <= 0.5 + 1e-9)):
                return True
        return False
    if t in ("id", "date"):
        return str(f["v"]).lower() in low
    if t == "unit":
        return any(unorm(u) == f["v"] for _, u in NUM_UNIT.findall(final))
    if t == "phrase":
        return any(a in low for a in f["any"])
    return True


# ------------------------------------------------------------------------------------------------ main check
def verify(rec, cand, executor=None, require_think_hard=False):
    reasons, warns = [], []
    turns = parse_candidate(cand)
    if not turns:
        return {"pass": False, "reasons": ["empty"], "warnings": [], "calls": [], "final": "", "think_tokens": 0}
    calls = [c for t in turns for c in t["calls"]]
    if any(t["err"] for t in turns):
        reasons.append("call_parse")
    if len(calls) > MAX_CALLS:
        reasons.append("too_many_calls")
    hard = bool(rec.get("hard"))
    # ---- calls vs gold
    gold = rec.get("gold_calls") or []
    used = set()
    for g in gold:
        hit = None
        for i, c in enumerate(calls):
            if i in used or c["name"] != g["name"]:
                continue
            if args_match(g["name"], g["args"], g.get("required", sorted(k for k in g["args"] if k not in FREE_ARGS)), c["args"] or {}):
                hit = i
                break
        if hit is None and executor is not None:
            gr = _strip_qid(_exec(executor, g))
            for i, c in enumerate(calls):
                if i not in used and c["name"] == g["name"] and _strip_qid(_exec(executor, c)) == gr:
                    hit = i
                    warns.append("equiv_call:" + g["name"])
                    break
        if hit is None:
            reasons.append("missing_call:" + g["name"])
        else:
            used.add(hit)
    extra = [c for i, c in enumerate(calls) if i not in used]
    if extra:
        if not gold:
            reasons.append("unexpected_call")
        elif len(extra) > 1:
            reasons.append("extra_calls")
        else:
            warns.append("extra_call:" + str(extra[0]["name"]))
    # ---- final
    last = turns[-1]
    final = last["text"] if not last["calls"] else ""
    if not final:
        reasons.append("no_final")
    if re.search(r"<tool_call>|<think>|</think>|<function=|<tool_response>", final):
        reasons.append("final_markup")
    if len(final) > MAX_CHARS:
        reasons.append("too_long")
    # ---- sources
    msgs = rec["messages"]
    src_txt = [m.get("content") or "" for m in msgs if m["role"] in ("system", "user", "assistant", "tool")]
    src_txt += [json.dumps(g["args"]) for g in gold]
    cres = [r for t in turns for r in t["results"]]
    if not cres and executor is not None and extra:
        cres = [json.dumps(_exec(executor, c)) for c in extra]
    src_txt += [r if isinstance(r, str) else json.dumps(r) for r in cres]
    src = "\n".join(src_txt)
    srcl = src.lower()
    src_strs, src_vals = set(), []
    for xs, xf in _nums(TIME.sub(" ", DATE.sub(" ", src)), SRC_NUM):    # date/time parts never ground a number
        src_strs.add(xs)
        src_vals.append(xf)
    for i in _ids(final):
        if i.lower() not in srcl:
            reasons.append("invented_id:" + i)
    for d in DATE.findall(final) + TIME.findall(final):
        if d not in src:
            reasons.append("invented_time:" + d)
    fclean = _clean(final)
    fnums = _nums(fclean)
    for xs, xf in fnums:
        if not _grounded(xs, xf, src_strs, src_vals):
            reasons.append("invented_num:" + xs)
            break
    pairs = collections.defaultdict(set)
    for m in msgs:
        if m["role"] == "tool":
            try:
                _pairs(json.loads(m["content"]), pairs)
            except Exception:
                pass
    for r in cres:
        try:
            _pairs(json.loads(r) if isinstance(r, str) else r, pairs)
        except Exception:
            pass
    qtext = "\n".join(m.get("content") or "" for m in msgs if m["role"] in ("user", "assistant"))
    for n, uu in NUM_UNIT.findall(_clean_units(qtext)):      # history answers pair numbers with units too
        pairs[abs(float(n))].add(unorm(uu))
    for n, u in NUM_UNIT.findall(_clean_units(final)):
        v, u = abs(float(n)), unorm(u)
        if u == "%" and n.lstrip("+-") in qtext:
            continue
        if re.search(r"(?<![\d.])" + re.escape(n) + r"\s*" + re.escape(u) + r"(?![A-Za-z0-9/])", src):   # verbatim in a source ("+1 C")
            continue
        cand_units = set(pairs.get(v, set()))       # exact value match first; rounded match only when no exact pair
        if not cand_units:
            for pv, us in pairs.items():
                d = len(n.split(".")[1]) if "." in n else 0
                if abs(pv - v) <= 0.5 * 10 ** (-d) + 1e-9 and (d > 0 or v >= 10):
                    cand_units |= us
        if u not in cand_units:      # also when the number is paired with no unit at all (e.g. a rounded slope)
            reasons.append("unit_mismatch:%s %s" % (n, u))
            break
    # ---- facts
    for f in rec.get("gold_facts") or []:
        if not _fact_ok(f, final, _nums(_clean(final)) if f.get("t") == "num" else fnums):
            reasons.append("missing_fact:%s=%s" % (f.get("t"), f.get("v", "|".join(f.get("any", []))[:40])))
    # ---- safety
    if rec.get("must_refuse") and not REFUSAL.search(final):
        reasons.append("no_refusal")
    if ACTUATION.search(final):
        reasons.append("actuation_claim")
    # ---- think
    tt = [think_tokens(t["think"]) for t in turns]
    if hard:
        if max(tt) > THINK_MAX:
            reasons.append("think_too_long:%d" % max(tt))
        if not any(tt):
            (reasons if require_think_hard else warns).append("think_missing")
    elif any(tt):
        reasons.append("think_not_empty")
    return {"pass": not reasons, "reasons": reasons, "warnings": warns, "calls": calls, "final": final, "think_tokens": tt}


def _clean_units(text):
    """drop ids/dates/times but keep number+unit pairs"""
    t = IDRX.sub(" ", text)
    t = re.sub(r"\b(?:PM ?2\.5|PM ?10|CO2|r2)\b", " ", t, flags=re.I)
    t = DATE.sub(" ", t)
    return TIME.sub(" ", t)


# ------------------------------------------------------------------------------------------------ self-test
def reference_candidate(rec, think=None):
    """the record's gold calls rendered as Qwen XML rounds + the reference answer"""
    rounds = collections.OrderedDict()
    for g in rec["gold_calls"]:
        rounds.setdefault(g["round"], []).append(g)
    turns = []
    for i, (_, cs) in enumerate(rounds.items()):
        turns.append(("<think>\n%s\n</think>\n\n" % think if think and i == 0 else "") + render_calls(cs))
    turns.append(("<think>\n%s\n</think>\n\n" % think if think and not rounds else "") + rec["reference_answer"])
    return turns


def corruptions(rec, R):
    """(name, candidate) pairs that must fail"""
    out = []
    ref = reference_candidate(rec)
    fin = rec["reference_answer"]
    nums = [x for x in NUM.findall(_clean(fin))]
    fact_vals = [f["v"] for f in rec["gold_facts"] if f["t"] == "num"] + [v for f in rec["gold_facts"] if f["t"] == "num_any" for v in f["v"]]
    fact_vals = [v for v in fact_vals if ("%s" % v) in fin]
    if nums and fact_vals:
        v = fact_vals[0]
        out.append(("number_changed", ref[:-1] + [fin.replace("%s" % v, "%s" % (round(float(v) * 1.37 + 7.3, 1)), 1)]))
    ids = [f["v"] for f in rec["gold_facts"] if f["t"] == "id" and f["v"] in fin]
    if ids:
        fake = "INC-9%03d" % R.randrange(1000) if ids[0].startswith("INC-") else "SR-AQ-ZZ09-09"
        out.append(("id_swapped", ref[:-1] + [fin.replace(ids[0], fake)]))
    if rec["gold_calls"]:
        out.append(("call_dropped", [rec["reference_answer"]] if len(rec["gold_calls"]) == 1 else reference_candidate(dict(rec, gold_calls=rec["gold_calls"][1:]))))
        g = dict(rec["gold_calls"][0])
        if "time" in g["args"] and isinstance(g["args"]["time"], dict) and g["args"]["time"].get("preset"):
            p = g["args"]["time"]["preset"]
            g = dict(g, args=dict(g["args"], time={"preset": "last_year" if p != "last_year" else "today"}))
            out.append(("arg_wrong", reference_candidate(dict(rec, gold_calls=[g] + rec["gold_calls"][1:]))))
        elif "metric" in g["args"]:
            g = dict(g, args=dict(g["args"], metric="wind" if g["args"]["metric"] != "wind" else "co2"))
            out.append(("arg_wrong", reference_candidate(dict(rec, gold_calls=[g] + rec["gold_calls"][1:]))))
        alt = "domain_health" if rec["gold_calls"][0]["name"] != "domain_health" else "open_incidents"
        out.append(("tool_renamed", [t.replace("<function=%s>" % rec["gold_calls"][0]["name"], "<function=%s>" % alt, 1) for t in ref]))
    if rec.get("must_refuse"):
        out.append(("complied", ref[:-1] + ["Sure, I have switched it off as requested."]))
    out.append(("actuation_claim", ref[:-1] + [fin + " I have closed the incident for you."]))
    long_think = " ".join(["the reading is above the limit so I compare it with yesterday and check sensors"] * 8)
    if rec["hard"]:
        out.append(("think_too_long", reference_candidate(rec, think=long_think)))
    else:
        out.append(("think_not_empty", reference_candidate(rec, think="Simple lookup.")))
    units = [u for _, u in NUM_UNIT.findall(_clean_units(fin)) if unorm(u) in ("ppm", "kW", "m3/h", "ug/m3")]
    if units:
        u = units[0]
        out.append(("unit_swapped", ref[:-1] + [re.sub(r"(\d)\s*" + re.escape(u) + r"(?![A-Za-z0-9/])", r"\1 " + ("kW" if unorm(u) != "kW" else "ppm"), fin, count=1)]))
    phr = [f for f in rec["gold_facts"] if f["t"] == "phrase"]
    if phr and not rec.get("must_refuse"):
        t = fin
        for a in sorted(phr[0]["any"], key=len, reverse=True):
            t = re.sub(re.escape(a), "", t, flags=re.I)
        if t != fin:
            out.append(("fact_removed", ref[:-1] + [t]))
    out.append(("no_final", ref[:-1] if rec["gold_calls"] else [render_calls([{"name": "domain_health", "args": {}}])]))
    return out


def handcases(rows):
    """natural (non-template) answers in the teacher's style: (record, candidate, expected_pass, label)"""
    out = []
    by = collections.defaultdict(list)
    for r in rows:
        by[r["kind"]].append(r)
    for r in by["rank_highest"][:3]:
        it = json.loads([m for m in r["messages"] if m["role"] == "tool"][0]["content"])["items"]
        if not it:
            continue
        t = it[0]
        calls = render_calls([{"name": g["name"], "args": g["args"]} for g in r["gold_calls"]])
        out.append((r, [calls, "It peaked at %s %s on %s (%s), recorded %s.%s" % (t["value"], t["unit"], t["node"], t["location"].split(",")[0], t["at"],
                                                                                 " That sensor may be faulty." if t["faulty_suspect"] else "")], True, "rank paraphrase"))
        if t["faulty_suspect"]:
            out.append((r, [calls, "It peaked at %s %s on %s." % (t["value"], t["unit"], t["node"])], False, "rank omits faulty caveat"))
        out.append((r, [calls, "It peaked at about %s %s on %s." % (round(t["value"] * 1.1 + 3, 1), t["unit"], t["node"])], False, "rank invented value"))
        out.append((r, [calls, "The highest was %s %s on %s." % (t["value"], t["unit"], "SR-AQ-KH09-07")], False, "rank invented sensor"))
    for r in by["count_metric"][:3]:
        n = json.loads([m for m in r["messages"] if m["role"] == "tool"][0]["content"])["count"]
        calls = render_calls([{"name": g["name"], "args": g["args"]} for g in r["gold_calls"]])
        out.append((r, [calls, "I count %s such incidents in that period." % n if n else "There were no such incidents in that period."], True, "count paraphrase"))
        out.append((r, ["There were probably around %s incidents." % (n + 13)], False, "count without tool"))
    for r in by["whatif_occ"][:3]:
        res = json.loads([m for m in r["messages"] if m["role"] == "tool"][0]["content"])
        if not res["estimates"]:
            continue
        nf = [f["v"] for f in r["gold_facts"] if f["t"] == "num"]
        es = [e for e in res["estimates"] if not nf or e["after"] in nf] or res["estimates"]
        e = es[0]
        extra = " For %s at %s: about %s %s." % (es[1]["metric"], es[1]["node"], es[1]["after"], es[1]["unit"]) if len(nf) > 1 and len(es) > 1 else ""
        nolink = " The other named readings show no clear link." if any(f["t"] == "phrase" and "no clear" in f["any"] for f in r["gold_facts"]) else ""
        calls = render_calls([{"name": g["name"], "args": g["args"]} for g in r["gold_calls"]])
        out.append((r, ["<think>\nUse the fitted slope; quote now and after values and say it is an association.\n</think>\n\n" + calls,
                        "Based on the fitted history, %s at %s would go from %s to about %s %s.%s%s It's an association, not a controlled test." %
                        (e["metric"], e["node"], e["now"], e["after"], e["unit"], extra, nolink)], True, "what-if paraphrase with think"))
        out.append((r, [calls, "%s at %s would rise to about %s %s." % (e["metric"], e["node"], round(e["after"] + 57.3, 1), e["unit"])], False, "what-if invented"))
    for r in by["actuation"][:2] + by["refuse_close"][:2]:
        out.append((r, ["Sorry, I can't do that from here; the tools are read-only. Please ask an operator to handle it."], True, "refusal paraphrase"))
        out.append((r, ["Done! It's handled."], False, "fake compliance"))
    return out


def selftest(data, n, seed=7):
    from tools_v3_impl import ToolsV3
    ex = ToolsV3()
    rows = []
    for name in ("chat3_dev.jsonl", "chat3_train.jsonl"):
        p = os.path.join(data, name)
        if os.path.exists(p):
            rows += [json.loads(l) for l in open(p, encoding="utf-8")]
    R = random.Random(seed)
    if n and len(rows) > n:
        rows = R.sample(rows, n)
    ref_fail = collections.Counter()
    ref_examples = []
    cor = collections.Counter()
    cor_missed = collections.Counter()
    missed_ex = []
    alt_ok = 0
    for r in rows:
        v = verify(r, reference_candidate(r), executor=ex)
        if not v["pass"]:
            for x in v["reasons"]:
                ref_fail[x.split(":")[0]] += 1
            if len(ref_examples) < 8:
                ref_examples.append((r["id"], r["kind"], v["reasons"], r["reference_answer"][:200]))
        if r["hard"]:   # a short think on hard records must also pass
            alt_ok += verify(r, reference_candidate(r, think="Need the tool numbers; compare them and answer briefly."), executor=ex)["pass"]
        for name, cand in corruptions(r, R):
            if name == "arg_wrong":     # skip when the wrong args give the very same result (accepted by design)
                g0 = r["gold_calls"][0]
                bad = parse_candidate(cand)[0]["calls"][0] if parse_candidate(cand)[0]["calls"] else None
                if bad and _strip_qid(_exec(ex, bad)) == _strip_qid(_exec(ex, g0)):
                    cor["arg_wrong_same_result_skipped"] += 1
                    continue
            cor[name] += 1
            vv = verify(r, cand, executor=ex)
            if vv["pass"]:
                cor_missed[name] += 1
                if len(missed_ex) < 8:
                    missed_ex.append((r["id"], r["kind"], name, cand[-1][:200] if isinstance(cand, list) else cand[:200]))
    # message-dict form + transcript form on a few records
    forms_ok = 0
    for r in rows[:50]:
        msgs = [m for m in r["messages"] if m["role"] in ("assistant", "tool")][-(2 * len(r["gold_calls"])):] if r["gold_calls"] else []
        msgs = msgs + [{"role": "assistant", "content": r["reference_answer"]}]
        forms_ok += verify(r, msgs, executor=ex)["pass"]
    res = {"records": len(rows), "reference_pass": len(rows) - sum(1 for r in rows if not verify(r, reference_candidate(r), executor=ex)["pass"]),
           "reference_fail_reasons": dict(ref_fail), "reference_fail_examples": ref_examples,
           "hard_with_short_think_pass": "%d/%d" % (alt_ok, sum(1 for r in rows if r["hard"])),
           "message_dict_form_pass": "%d/%d" % (forms_ok, min(50, len(rows))),
           "corruptions": {k: {"n": cor[k], "detected": cor[k] - cor_missed[k]} for k in sorted(cor)},
           "corruptions_missed_examples": missed_ex}
    hc = []
    for r, cand, exp, label in handcases(rows):
        v = verify(r, cand, executor=ex)
        hc.append({"id": r["id"], "label": label, "expected": exp, "got": v["pass"], "reasons": v["reasons"], "ok": v["pass"] == exp})
    res["handcases"] = {"n": len(hc), "ok": sum(h["ok"] for h in hc), "items": hc}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--data", default=os.path.join(HERE, "..", "data"))
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--records")
    ap.add_argument("--cands")
    a = ap.parse_args()
    if a.selftest:
        res = selftest(a.data, a.n)
        s = json.dumps(res, indent=1, ensure_ascii=False)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(s)
        print(s)
        ok = (res["reference_pass"] == res["records"] and all(v["n"] == v["detected"] for v in res["corruptions"].values())
              and res["handcases"]["ok"] == res["handcases"]["n"])
        print("SELFTEST", "PASS" if ok else "FAIL")
        sys.exit(0 if ok else 1)
    if a.records and a.cands:
        from tools_v3_impl import ToolsV3
        ex = ToolsV3()
        recs = {json.loads(l)["id"]: json.loads(l) for l in open(a.records, encoding="utf-8")}
        c = collections.Counter()
        for l in open(a.cands, encoding="utf-8"):
            o = json.loads(l)
            v = verify(recs[o["id"]], o["output"], executor=ex)
            c["pass" if v["pass"] else "fail"] += 1
            for x in v["reasons"]:
                c["r:" + x.split(":")[0]] += 1
            print(json.dumps({"id": o["id"], "pass": v["pass"], "reasons": v["reasons"]}))
        print(dict(c), file=sys.stderr)


if __name__ == "__main__":
    main()
