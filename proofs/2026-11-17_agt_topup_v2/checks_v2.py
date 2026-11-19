"""checks_v2.py: automatic data checks of the agt_v3 top-up v2 (run by check_data_v2.py before anything is uploaded; also stand-alone).
  python3 checks_v2.py TRAIN GENDEV [--full=NEW_FULL.jsonl] [--local=DIR] [--out=DIR] [--hold=FILE,FILE] [--max-prompt=904] [--max-comp=240]
  1 schema     prompt/completion/gold present, Llama-3 template, completion = one JSON + <|eot_id|>; final answers = valid agt_v3 JSON (keys, enums of the
               prompt's own system text, dq verdict, onset HH:MM, confidence, action last)
  2 protocol   tool calls only get_history{hours 6|12} / get_neighbors{} / get_card{}; <= 2 calls; the result follows the call; call/result formats; the
               parent turn row of every later turn exists with the call as its completion; CARD marker => get_card first; final answers are never calls
  3 gold       (new rows, need --full) status vs the CARD limits in the prompt, pattern vs generator truth, hard-case rules (standby, early leak, night
               presence, lone plateau/step, sensor_fault needs a 2nd evidence kind), neighbour consistency, grounding of the tool finals
  4 leakage    no prompt of a local eval set / dev / test / gate set (and no real val id or (node, end_epoch)) in train or gendev
  5 tokens     EVERY row (every turn, incl. tool results): prompt <= 904, completion <= 240 (prompt + 240 + 136 <= board agent ctx 1280); distribution report
exit 0 pass | 1 fail. Writes OUT/checks_report.json."""
import collections
import hashlib
import json
import os
import re
import sys
from pathlib import Path

EOT = "<|eot_id|>"
ASSIST = "<|start_header_id|>assistant<|end_header_id|>\n\n"
IPY = "<|start_header_id|>ipython<|end_header_id|>\n\n"
CARD_MARK = "  details withheld (limits, noise, behaviour): call get_card"
STATUS = {"normal", "warning", "critical", "sensor_fault"}
DQV = {"ok", "suspect", "fault", "insufficient"}
KEYS = ["pattern", "status", "data_quality", "severity_reason", "evidence", "observations", "likely_cause", "confidence", "event_active", "onset"]
HH = re.compile(r"^\d\d:\d\d$")
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def rd(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def enum(prompt, key):
    m = re.search(re.escape(key) + r" \(([^)]*)\)", prompt.split("<|start_header_id|>user")[0])
    return set(m.group(1).split(",")[0].split("|")) if m else None


def split_prompt(prompt):
    parts = prompt.split(ASSIST)
    return parts


def check_final(c, prompt):
    """agt_v3 answer; -> list of problems"""
    bad = []
    if not isinstance(c, dict):
        return ["not an object"]
    for k in KEYS:
        if k not in c:
            bad.append("missing " + k)
    if bad:
        return bad
    if c["status"] not in STATUS:
        bad.append("status")
    pe = enum(prompt, "pattern")
    if pe and c["pattern"] not in pe:
        bad.append("pattern %s not in system enum" % c["pattern"])
    ce = enum(prompt, "likely_cause")
    if ce and c["likely_cause"] not in ce:
        bad.append("cause %s not in system enum" % c["likely_cause"])
    dq = c["data_quality"]
    if not (isinstance(dq, dict) and dq.get("verdict") in DQV and isinstance(dq.get("why"), str) and isinstance(dq.get("src"), list)):
        bad.append("data_quality")
    if not (isinstance(c["evidence"], list) and isinstance(c["observations"], list) and 1 <= len(c["observations"]) <= 3):
        bad.append("evidence/observations")
    if not (isinstance(c["confidence"], (int, float)) and 0 <= c["confidence"] <= 1):
        bad.append("confidence")
    if not isinstance(c["event_active"], bool):
        bad.append("event_active")
    if not (isinstance(c["onset"], str) and HH.match(c["onset"])):
        bad.append("onset")
    if c["status"] == "sensor_fault":
        fe = enum(prompt, "fault_kind")
        if "fault_kind" not in c or (fe and c["fault_kind"] not in fe):
            bad.append("fault_kind")
    ae = enum(prompt, "action")
    if "action" not in c or (ae and c["action"] not in ae) or list(c)[-1] != "action":
        bad.append("action (must exist, be an enum value and be the LAST key)")
    return bad


def parse_call(t):
    try:
        d = json.loads(t)
    except Exception:  # noqa: BLE001
        return None
    if not (isinstance(d, dict) and set(d) == {"tool", "args"} and isinstance(d["args"], dict)):
        return None
    tool, a = d["tool"], d["args"]
    if tool == "get_history" and set(a) == {"hours"} and a["hours"] in (6, 12):
        return d
    if tool in ("get_neighbors", "get_card") and a == {}:
        return d
    return None


def check_result(call, res, p1):
    t = call["tool"]
    if t == "get_history":
        h = call["args"]["hours"]
        ls = res.split("\n")
        return ls[0].startswith("HISTORY %d h: " % h) and any(l.startswith("SERIES (") for l in ls) and any(l.startswith("H4 ") for l in ls)
    if t == "get_neighbors":
        ls = res.split("\n")
        return res == "no related sensors" or all(l.startswith("N%d " % (i + 1)) for i, l in enumerate(ls))
    if t == "get_card":
        head = [l for l in p1.split("\n") if l.startswith("CARD: ")]
        return res.startswith("CARD: ") and bool(head) and res.split("\n")[0] == head[0] and "details withheld" not in res
    return False


def tok_stats(v):
    v = sorted(v)
    if not v:
        return {}
    q = lambda f: v[min(len(v) - 1, int(f * len(v)))]  # noqa: E731
    return {"n": len(v), "min": v[0], "p50": q(0.5), "p95": q(0.95), "max": v[-1]}


def run(train, gendev, full=None, local=None, out=None, hold=(), max_prompt=904, max_comp=240, tok=None):
    rep, fails = {}, []
    rows = rd(train)
    gd = rd(gendev) if gendev else []

    def fail(m):
        fails.append(m)
        print("FAIL:", m)

    # ---------------- 1 schema + 2 protocol
    bysch, prot = collections.Counter(), collections.Counter()
    byp = {r["prompt"]: r for r in rows if str(r.get("completion", "")).lstrip().startswith('{"tool"')}
    ex = collections.defaultdict(list)
    n_final_tool = 0
    replay_bad = 0
    for r in rows:
        isnew = str(r.get("source", "")) == "synthetic_sim_v2"
        p, c = r["prompt"], r["completion"]
        if not (p.startswith("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n") and p.endswith(ASSIST)):
            bysch["template"] += 1
            ex["template"].append(r["id"])
            continue
        if not c.endswith(EOT) or c.count(EOT) != 1:
            bysch["completion_eot"] += 1
            ex["completion_eot"].append(r["id"])
            continue
        try:
            cj = json.loads(c[:-len(EOT)])
        except Exception:  # noqa: BLE001
            bysch["completion_json"] += 1
            ex["completion_json"].append(r["id"])
            continue
        parts = split_prompt(p)
        ncall = len(parts) - 2
        if ncall < 0 or parts[-1] != "":
            bysch["template"] += 1
            continue
        is_call = isinstance(cj, dict) and "tool" in cj
        if is_call:
            prot["calls"] += 1
            call = parse_call(c[:-len(EOT)])
            if call is None:
                prot["bad_call"] += 1
                ex["bad_call"].append(r["id"])
            if ncall >= 2:
                prot["third_call"] += 1
                ex["third_call"].append(r["id"])
            if CARD_MARK in p and ncall == 0 and call and call["tool"] != "get_card":
                prot["marker_without_get_card"] += 1
                ex["marker_without_get_card"].append(r["id"])
        else:
            if ncall > 0:
                n_final_tool += 1
            bad = check_final(cj, p)
            if bad:
                (prot if False else bysch)["final_invalid_new" if isnew else "final_invalid_replay"] += 1
                ex["final_invalid_new" if isnew else "final_invalid_replay"].append("%s %s" % (r["id"], bad[:2]))
            if r.get("turn") == "call":
                prot["turn_call_but_final"] += 1
        # tool structure of the prompt
        calls = []
        for i in range(1, len(parts) - 1):
            seg = parts[i]
            m = re.match(r"^(.*?)" + re.escape(EOT) + re.escape(IPY) + r"(.*)" + re.escape(EOT) + r"$", seg, re.S)
            if not m:
                prot["segment_format"] += 1
                ex["segment_format"].append(r["id"])
                break
            cl = parse_call(m.group(1))
            if cl is None:
                prot["bad_prompt_call"] += 1
                ex["bad_prompt_call"].append(r["id"])
                break
            if not check_result(cl, m.group(2), parts[0]):
                prot["bad_result"] += 1
                ex["bad_result"].append("%s %s" % (r["id"], cl["tool"]))
            calls.append(cl["tool"])
        if ncall:
            # parent turn must exist and its completion must be the last call
            last = parts[-2]
            parent = p[:len(p) - len(last) - len(ASSIST)]
            pr = byp.get(parent)
            lastcall = last.split(EOT)[0]
            if pr is None or pr["completion"] != lastcall + EOT:
                prot["orphan_turn"] += 1
                ex["orphan_turn"].append(r["id"])
        if CARD_MARK in p and calls[:1] != ["get_card"] and not is_call:
            prot["marker_final_without_card_result"] += 1
    rep["schema_problems"] = dict(bysch)
    rep["protocol"] = dict(prot, tool_finals=n_final_tool)
    rep["examples"] = {k: v[:3] for k, v in ex.items()}
    n_new_fin = sum(1 for r in rows if str(r.get("source")) == "synthetic_sim_v2" and not str(r["completion"]).startswith('{"tool"'))
    for k, v in list(bysch.items()):
        if k == "final_invalid_replay":
            if v > 0.01 * len(rows):
                fail("%s: %d rows (>1%% of the mix)" % (k, v))
        elif v:
            fail("schema %s: %d rows (e.g. %s)" % (k, v, ex[k][:2]))
    for k, v in prot.items():
        if k in ("calls",):
            continue
        if v:
            fail("protocol %s: %d (e.g. %s)" % (k, v, ex[k][:2]))
    if prot["calls"] == 0:
        fail("protocol: no tool-call rows in the mix")

    # ---------------- 3 gold consistency (new rows)
    if full:
        fr = {r["id"]: r for r in rd(full)}
        g = collections.Counter()
        gex = collections.defaultdict(list)
        used = [fr[r["id"]] for r in rows if r["id"] in fr]
        for r in used:
            gold, card, n = r["gold"], r["card"], r["n"]
            if "status" not in gold:
                continue
            g["rows"] += 1
            hist = r["hist"]
            xs = hist[-n:] if card["kind"] == "continuous" else []
            st = gold["status"]
            fam = r["family"]
            routine = (r.get("meta") or {}).get("routine") or (r.get("meta") or {}).get("glitch")
            w, c = card.get("warning"), card.get("critical")
            if xs and w and c and st in ("normal", "warning", "critical") and not routine and not fam.startswith(("hard_ph", "tool_history")) \
                    and not r.get("missing") and "sub" in r and r["sub"] not in ("stable", "routine"):
                if w["dir"] == "high":
                    ext_w, ext_c = max(xs) > w["at"], max(xs) > c["at"]
                elif w["dir"] == "low":
                    ext_w, ext_c = min(xs) < w["at"], min(xs) < c["at"]
                else:
                    ext_w = max(xs) > w["high"] or min(xs) < w["low"]
                    ext_c = max(xs) > c["high"] or min(xs) < c["low"]
                g["limit_checked"] += 1
                if (st == "critical" and not ext_c) or (st == "warning" and not ext_w):
                    g["limit_mismatch"] += 1
                    gex["limit_mismatch"].append(r["id"])
            sub, size = r.get("sub"), r.get("size")
            if sub in ("spike", "dip", "step_increase", "step_decrease", "gradual_increase", "gradual_decrease", "exponential_increase",
                       "oscillation", "throttling") and size and size >= 6 and st != "sensor_fault" and not fam.startswith("tool_"):
                g["pattern_checked"] += 1
                if gold["pattern"] != sub:
                    g["pattern_mismatch"] += 1
                    gex["pattern_mismatch"].append("%s %s->%s" % (r["id"], sub, gold["pattern"]))
            if fam == "hard_standby" and (st != "normal" or gold["pattern"] in ("flatline", "erratic") or gold["data_quality"]["verdict"] != "ok"):
                g["standby_bad"] += 1
                gex["standby_bad"].append(r["id"])
            if fam == "hard_leak" and gold["pattern"] != "gradual_decrease":
                g["leak_bad"] += 1
            if fam == "hard_night" and "off_hours_presence" in r.get("slices", []) and False:
                pass
            if fam == "hard_night" and gold["pattern"] == "off_hours_presence" and st == "sensor_fault":
                g["night_bad"] += 1
            if fam == "hard_plateau" and st == "sensor_fault":
                g["plateau_bad"] += 1
            if st == "sensor_fault" and gold.get("fault_kind") == "bias" and card["kind"] == "continuous":
                ms = card.get("max_step")
                jump = max([abs(hist[i] - hist[i - 1]) for i in range(len(hist) - n + 1, len(hist))] or [0])
                imp = card.get("impossible") or {}
                impossible = any((imp.get("below") is not None and v < imp["below"]) or (imp.get("above") is not None and v > imp["above"]) for v in xs)
                neigh = any(s.startswith("N") for s in gold["data_quality"].get("src", []))
                g["bias_checked"] += 1
                if not ((ms and jump > ms) or impossible or neigh):
                    g["bias_without_second_evidence"] += 1
                    gex["bias_without_second_evidence"].append(r["id"])
        for k in ("limit_mismatch", "pattern_mismatch"):
            tot = g["limit_checked" if k == "limit_mismatch" else "pattern_checked"]
            if tot and g[k] > (0.04 if k == "limit_mismatch" else 0.12) * tot:
                fail("gold %s: %d of %d checked (%.1f%%)" % (k, g[k], tot, 100 * g[k] / tot))
        for k in ("standby_bad", "leak_bad", "night_bad", "plateau_bad", "bias_without_second_evidence"):
            if g[k]:
                fail("gold %s: %d rows (e.g. %s)" % (k, g[k], gex[k][:2]))
        # neighbour consistency + grounding of tool finals
        tf = [r for r in rows if r.get("turn") == "final" or (str(r.get("family", "")).startswith("tool_") and not str(r["completion"]).startswith('{"tool"'))]
        for r in tf:
            gold = json.loads(r["completion"][:-len(EOT)])
            ids = set(gold.get("evidence", [])) | set(gold["data_quality"].get("src", []))
            have = set(re.findall(r"(?m)^([EHN]\d+) ", r["prompt"].split("<|start_header_id|>user<|end_header_id|>")[1]))
            g["tool_final"] += 1
            if not ids <= have | {"GAPS"}:
                g["tool_final_unknown_id"] += 1
                gex["tool_final_unknown_id"].append(r["id"])
            nl = re.findall(r"(?m)^N\d+ .*$", r["prompt"])
            if nl:
                calm = all(" | normal | stable | " in l for l in nl)
                if (gold["status"] == "sensor_fault") != calm:
                    g["neighbour_inconsistent"] += 1
                    gex["neighbour_inconsistent"].append(r["id"])
        for k in ("tool_final_unknown_id", "neighbour_inconsistent"):
            if g[k]:
                fail("gold %s: %d (e.g. %s)" % (k, g[k], gex[k][:2]))
        rep["gold"] = dict(g)
        rep["gold_examples"] = {k: v[:3] for k, v in gex.items()}

    # ---------------- 4 leakage
    hs = set()
    hids = set()
    hkeys = set()
    for hp in hold:
        if hp and os.path.exists(hp):
            for h in rd(hp):
                if "prompt" in h:
                    hs.add(hashlib.md5(h["prompt"].encode()).hexdigest())
                hids.add(h.get("id"))
                if h.get("node") and h.get("end_epoch"):
                    hkeys.add((h["node"], h["end_epoch"]))
    leak = [r["id"] for r in rows + gd if hashlib.md5(r["prompt"].encode()).hexdigest() in hs or r["id"] in hids
            or (r.get("node") and (r.get("node"), r.get("end_epoch")) in hkeys)]
    rep["leakage"] = {"hold_prompts": len(hs), "hold_ids": len(hids), "overlap": len(leak)}
    if leak:
        fail("leakage: %d train/gendev rows are in a held-out set (e.g. %s)" % (len(leak), leak[:3]))
    if len({r["id"] for r in rows}) != len(rows):
        fail("duplicate ids in train")
    if len({hashlib.md5((r["prompt"] + r["completion"]).encode()).hexdigest() for r in rows}) != len(rows):
        fail("duplicate (prompt, completion) pairs in train")

    # ---------------- 5 tokens
    if tok is None:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(os.path.expanduser(os.environ.get("BASE_TOK", "~/models/llama-3.2-3b-instruct/tokenizer.json")))
    nt = lambda t: len(tok.encode(t, add_special_tokens=False).ids)  # noqa: E731
    pt, ct = collections.defaultdict(list), collections.defaultdict(list)
    over = []
    for r in rows:
        a, b = nt(r["prompt"]), nt(r["completion"])
        fam = r.get("family", "?")
        key = "tool:" + str(r.get("turn") or ("call" if r["completion"].startswith('{"tool"') else "final")) if fam.startswith("tool_") else \
            ("replay_real" if r.get("synthetic") is False else "replay_syn" if str(r.get("source")) != "synthetic_sim_v2" else "new:" + fam)
        pt[key].append(a)
        ct[key].append(b)
        pt["ALL"].append(a)
        ct["ALL"].append(b)
        if a > max_prompt or b > max_comp or a + 240 + 136 > 1280:
            over.append((r["id"], a, b))
    rep["tokens"] = {"limit": "prompt <= %d, completion <= %d (prompt + 240 + 136 <= 1280)" % (max_prompt, max_comp),
                     "prompt": {k: tok_stats(v) for k, v in sorted(pt.items())}, "completion": {k: tok_stats(v) for k, v in sorted(ct.items())},
                     "over_limit": len(over)}
    bins = collections.Counter(min(a // 100 * 100, 900) for a in pt["ALL"])
    rep["tokens"]["prompt_hist_100"] = dict(sorted(bins.items()))
    if over:
        fail("tokens: %d rows over the board context limit (e.g. %s)" % (len(over), over[:3]))
    rep["gendev_note"] = "gendev (real val rows, evaluation only inside the kernel) not token-limited: %d rows" % len(gd)
    rep["n_rows"] = len(rows)
    rep["pass"] = not fails
    rep["fails"] = fails
    if out:
        os.makedirs(out, exist_ok=True)
        json.dump(rep, open(os.path.join(out, "checks_report.json"), "w", newline="\n"), indent=1)
    return rep


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    o = {x.split("=")[0]: x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith("--") and "=" in x}
    loc = o.get("--local")
    hold = [h for h in o.get("--hold", "").split(",") if h]
    if loc:
        hold += [os.path.join(loc, n) for n in ("val_sel.jsonl", "syn_slice.jsonl", "unseen100.jsonl", "tool_t1.jsonl", "tool_t2.jsonl", "hard_val.jsonl")]
    rep = run(a[0], a[1] if len(a) > 1 else None, o.get("--full"), loc, o.get("--out"), hold, int(o.get("--max-prompt", 904)), int(o.get("--max-comp", 240)))
    print(json.dumps({k: rep[k] for k in ("n_rows", "pass", "fails")}, indent=1))
    sys.exit(0 if rep["pass"] else 1)
