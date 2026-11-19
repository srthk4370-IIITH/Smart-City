"""gen_tools.py: multi-turn tool-protocol scenarios of the agt_v3 top-up v2 (PROTOCOL.md). Built on gen_v2 / gen_agt (simulator, teacher, builder).
A scenario is turned into TRAINING ROWS, one per assistant turn (the trainer only knows prompt -> completion, loss on the completion):
  turn 'call'   prompt = turn-1 prompt (the ordinary agent prompt)                     completion = {"tool": ..., "args": ...}<eot>
  turn 'final'  prompt = turn-1 prompt + call + <eot> + ipython header + RESULT + <eot> + assistant header   completion = agent JSON<eot>
  (chain)       the middle turn has completion = the second call.
Tools: get_history {hours: 6|12}, get_neighbors {}, get_card {}.  Result renderers (render_*) are the exact app specification.
Gold: simulator truth (teacher label of the long window / the confirmed or faulty truth of the neighbours / the full card)."""
from __future__ import annotations

import copy
import json
import re

import gen_v2 as G

GA, EV, CD, F, V, SM, TV = G.GA, G.EV, G.CD, G.F, G.V, G.SM, G.TV
IPY = "<|start_header_id|>ipython<|end_header_id|>\n\n"
ASSIST = "<|start_header_id|>assistant<|end_header_id|>\n\n"
CARD_MARK = "  details withheld (limits, noise, behaviour): call get_card"


def call_json(tool, **args):
    return json.dumps({"tool": tool, "args": args}, ensure_ascii=False)


# ---------------------------------------------------------------------------------------------------- result renderers
def series_k(xs, k):
    """k equal-width means of xs (F.downsample)"""
    return F.downsample(xs, k)


def render_history(card, hist, hours, end, missing=None):
    """get_history result: window of `hours` h ending at `end`, 12 series values (30-min means for 6 h, hourly means for 12 h), the long-window
    evidence lines E2 E3 E4 E8 re-labelled H2 H3 H4 H8 (E1 and the 12 h view E9/E10 are identical to the first prompt), GAPS if any."""
    n = hours * 12
    key = EV.register(card)
    dec = F.METRICS[key]["dec"]
    from datetime import datetime, timedelta
    e = datetime.fromtimestamp(end, V.IST)
    s = e - timedelta(minutes=5 * (n - 1))
    user, st, ev, info = EV.agent_user(card, "x", "x", hist[-V.HIST:], n, end, missing=(missing[-n:] if missing else None))
    lines = ["HISTORY %d h: %s -> %s IST, %d x 5 min" % (hours, s.strftime("%a %d %b %H:%M"), e.strftime("%H:%M"), n)]
    g = EV.gaps_line(missing[-n:] if missing else None, n)
    if g:
        lines.append(g)
    lines.append("SERIES (%s means): %s" % ("30-min" if hours == 6 else "hourly", " ".join(F.fmt(v, dec) for v in series_k(hist[-n:], 12))))
    by = {i: t for i, _, t in ev}
    for i in (2, 3, 4, 8):
        lines.append("H%d %s" % (i, by["E%d" % i]))
    return "\n".join(lines)


def render_neighbors(rows):
    """get_neighbors result. rows: [(node, short, status, pattern, last_text)] -> one line per related sensor"""
    if not rows:
        return "no related sensors"
    return "\n".join("N%d %s | %s | %s | %s | last %s" % (i + 1, *r) for i, r in enumerate(rows))


def render_card(card, place):
    return CD.render_full(card, place)


def short_card_prompt(prompt, card, place):
    """turn-1 prompt with the CARD block cut to its first line + the get_card marker (token budget mode)"""
    full = CD.render_full(card, place)
    head = full.split("\n")[0]
    assert full in prompt
    return prompt.replace(full, head + "\n" + CARD_MARK, 1)


# ---------------------------------------------------------------------------------------------------- turn assembly
def turn_prompt(p1, steps):
    """p1 = turn-1 prompt; steps = [(call_text, result_text), ...] already executed"""
    p = p1
    for c, r in steps:
        p += c + G.EOT + IPY + r + G.EOT + ASSIST
    return p


def mkrow(base, turn, prompt, completion, gold, grp, k, kind, extra_slices=()):
    r = {"id": "", "family": "tool_" + kind, "role": base["role"], "stage": G.wname(base["n"]), "synthetic": True, "source": "synthetic_sim_v2",
         "slices": list(base.get("slices", [])) + ["tool", "tool_" + kind, "turn_" + turn] + list(extra_slices), "prompt": prompt,
         "completion": completion + G.EOT if not completion.endswith(G.EOT) else completion, "gold": gold, "turn": turn, "group": grp,
         "tool_kind": kind, "n": base["n"], "end_epoch": base["end_epoch"], "node": base["node"], "card": base["card"], "hist": base["hist"],
         "place": base.get("place")}
    r["id"] = G.rid("v2-tool-%s-%s%d" % (kind, turn, k), prompt + completion)
    return r


def remap(gold, mapping_ids):
    """E-ids that now live in the result (H lines): E2 E3 E4 E5 E8 -> H*"""
    t = json.dumps(gold, ensure_ascii=False)
    t = re.sub(r"\bE(%s)\b" % "|".join(map(str, mapping_ids)), r"H\1", t)
    return json.loads(t)


NUM = re.compile(r"-?\d+(?:\.\d+)?")


def grounded(gold, prompt):
    """numbers of the text fields appear in the prompt, cited ids exist as line labels"""
    ctx = set(NUM.findall(prompt))
    txt = [gold.get("severity_reason", ""), gold.get("data_quality", {}).get("why", "")] + list(gold.get("observations", []))
    for t in txt:
        for x in NUM.findall(re.sub(r"\b[EHN]\d+\b", " ", t)):
            if x not in ctx and x.lstrip("-+") not in ctx:
                return False
    ids = set(gold.get("evidence", [])) | set(gold.get("data_quality", {}).get("src", []))
    for t in txt:
        ids |= set(re.findall(r"\b([EHN]\d+)\b", t))
    have = set(re.findall(r"(?m)^([EHN]\d+) ", prompt)) | ({"GAPS"} if "GAPS:" in prompt else set())
    return ids <= have


# ---------------------------------------------------------------------------------------------------- scenarios
HIST_PATTERNS = ("step_increase", "step_decrease", "gradual_increase", "gradual_decrease", "exponential_increase", "spike", "oscillation")


def sc_history(T):
    """onset before the short window / slow ramp ambiguous in the short window / data gap: ask for the longer history"""
    rng = T.rng
    kind = rng.choices(("onset", "ramp", "gap"), weights=(45, 30, 25))[0]
    n_short = rng.choice((18, 18, 24, 36))
    hours = 12 if kind == "gap" else rng.choice((6, 12, 12))
    G.NF["n"] = hours * 12
    if kind == "gap":
        r = None
        for _ in range(8):
            r = GA.gen_dq_row(T)
            if r and r["n"] == 144 and r["sub"] in ("recovery_gap", "insufficient", "small_gap") and r.get("missing"):
                break
            r = None
        if not r:
            return None
        mask = [False] * (len(r["hist"]) - len(r["missing"])) + list(r["missing"])
        if sum(mask[-n_short:]) < 2:
            return None
        G.tag(r, "tool_history", "x", [])
    else:
        sn = T.sensor_for(GA.wchoice(rng, GA.EX_W))
        if sn is None or sn.card["kind"] != "continuous":
            return None
        if rng.random() < 0.35:
            sn.card = GA._jit(sn.card, rng)
        p = rng.choice(("gradual_increase", "gradual_decrease") if kind == "ramp" else HIST_PATTERNS)
        tg = rng.choices(("normal", "warning", "critical"), weights=(25, 40, 35))[0]
        r = GA.gen_event_row(T, sn, "tool_history", p, tg)
        if not r or r["n"] != hours * 12:
            return None
        need = (n_short + 8) if kind == "onset" else max(40, 2 * n_short)
        if (r.get("d") or 0) < need:
            return None
        mask = None
    card = r["card"]
    if card["kind"] != "continuous" or len(r["hist"]) < hours * 12:
        return None
    hist, end = r["hist"], r["end_epoch"]
    xs_short = hist[-n_short:]
    user1, st1, ev1, info1 = EV.agent_user(card, r["node"], r["location"], hist[-V.HIST:], n_short, end, place=r["place"],
                                           missing=(mask[-n_short:] if mask else None))
    p1 = F.llama3_prompt(EV.agent_system(card, n_short), user1)
    res = render_history(card, hist, hours, end, mask)
    gold = remap(r["gold"], (2, 3, 4, 5, 8))
    call = call_json("get_history", hours=hours)
    p2 = turn_prompt(p1, [(call, res)])
    if not grounded(gold, p2):
        return None
    base = dict(r, n=n_short)
    grp = G.rid("grp", p1)
    return [mkrow(base, "call", p1, call, {"tool": "get_history", "args": {"hours": hours}}, grp, 1, "history_" + kind),
            mkrow(base, "final", p2, json.dumps(gold, ensure_ascii=False), gold, grp, 2, "history_" + kind)], {"kind": "history_" + kind}


def neighbor_rows(T, sn, r, confirmed):
    rng = T.rng
    site, ix = sn.site, sn.ix
    nodes = [n for n in site["nodes"] if n["kind"] == "sensor" and n["id"] != sn.sid and n["card"] in GA.EC]
    same = [n for n in nodes if n["parent"] == sn.host]
    gp = ix.parent(sn.host)
    peers = [n for n in nodes if n["card"] == sn.card["card_id"] and n["parent"] != sn.host and gp and ix.parent(n["parent"]) == gp]
    cand = [n for n in same + peers if GA.EC[n["card"]]["kind"] in ("continuous", "binary_state")]
    if not cand:
        return None
    rng.shuffle(cand)
    pick = []
    if confirmed:
        same_card = [n for n in cand if n["card"] == sn.card["card_id"]]
        first = same_card[0] if same_card else cand[0]
        pick.append(first)
    for n in cand:
        if n not in pick and len(pick) < rng.choice((2, 3)):
            pick.append(n)
    rows = []
    for j, n in enumerate(pick):
        c = GA.EC[n["card"]]
        nd = c["decimals"]
        if c["kind"] == "binary_state":
            last, stt, pat = "1" if rng.random() < 0.5 else "0", "normal", "stable"
        else:
            lo, hi = (c.get("normal") or [0, 1])[:2]
            val = lo + (hi - lo) * rng.uniform(0.25, 0.75)
            stt, pat = "normal", "stable"
            if confirmed and j == 0:
                same_c = n["card"] == sn.card["card_id"]
                shift = r["gold"]["pattern"]
                pat = shift if same_c else ("step_increase" if shift.endswith("increase") else "step_decrease")
                stt = r["gold"]["status"] if same_c and r["gold"]["status"] in ("normal", "warning", "critical") else "normal"
                if same_c:
                    val = max(r["hist"][-1] * rng.uniform(0.93, 1.07), 0)
            last = F.fmt(val, nd)
        short = c.get("short") or c["quantity"]
        rows.append((n["device"], short, stt, pat, ("%s %s" % (last, c["unit"] or "")).strip()))
    return rows


def sc_neighbors(T, with_card=False):
    """lone step (inside max_step) of unclear origin: real event (a neighbour shows it) or sensor bias (all neighbours calm)"""
    rng = T.rng
    sn = T.sensor_for(GA.wchoice(rng, GA.EX_W))
    if sn is None or sn.card["kind"] != "continuous":
        return None
    if rng.random() < 0.35:
        sn.card = GA._jit(sn.card, rng)
    n = rng.choice((18, 24, 36, 48))
    G.NF["n"] = n
    p = rng.choice(("step_increase", "step_decrease"))
    tg = rng.choices(("normal", "warning", "critical"), weights=(25, 40, 35))[0]
    r = GA.gen_event_row(T, sn, "tool_neighbors", p, tg)
    if not r or r["n"] != n or r["gold"]["status"] == "sensor_fault" or r["card"]["kind"] != "continuous":
        return None
    ms = r["card"].get("max_step")
    st = F.compute_stats(r["hist"][-n:], r["card"]["decimals"])
    if abs(st["max_jump_signed"]) <= 0 or (ms and abs(st["max_jump_signed"]) > ms):
        return None
    confirmed = rng.random() < 0.5
    rows = neighbor_rows(T, sn, r, confirmed)
    if not rows:
        return None
    card = r["card"]
    gold = copy.deepcopy(r["gold"])
    jump = F.fmt(abs(st["max_jump_signed"]), card["decimals"])
    unit = card["unit"] or ""
    if confirmed:
        gold["data_quality"] = {"verdict": "ok", "why": "the %s %s step is also seen by neighbour N1" % (jump, unit), "src": ["E5", "N1"]}
        gold["evidence"] = sorted(set(gold["evidence"]) | {"N1"}, key=lambda s: (s[0] != "E", int(s[1:])))
    else:
        gold["status"], gold["likely_cause"], gold["action"] = "sensor_fault", "sensor_fault", "check_sensor"
        gold["fault_kind"] = "bias"
        gold["data_quality"] = {"verdict": "fault", "why": "step of %s %s not seen by neighbour N1: offset, not an event" % (jump, unit),
                                "src": ["E5", "N1"]}
        gold["severity_reason"] = "E5 jump %s %s with all neighbours N1 calm: sensor fault (card faults)" % (jump, unit)
        gold["observations"] = ["lone step of %s %s, neighbours unchanged [E5,N1]" % (jump, unit)]
        gold["evidence"] = ["E5", "N1"]
        gold["event_active"] = True
        gold["confidence"] = round(rng.choice((0.7, 0.75, 0.8, 0.85)), 2)
        gold = {k: gold[k] for k in ("pattern", "status", "data_quality", "severity_reason", "evidence", "observations", "likely_cause",
                                     "confidence", "event_active", "onset", "fault_kind", "action")}
    hist, end = r["hist"], r["end_epoch"]
    user1, _, _, _ = EV.agent_user(card, r["node"], r["location"], hist[-V.HIST:], n, end, place=r["place"])
    p1 = F.llama3_prompt(EV.agent_system(card, n), user1)
    steps = []
    calls = []
    if with_card:
        p1 = short_card_prompt(p1, card, r["place"])
        c1 = call_json("get_card")
        steps.append((c1, render_card(card, r["place"])))
        calls.append(c1)
    c2 = call_json("get_neighbors")
    steps.append((c2, render_neighbors(rows)))
    calls.append(c2)
    base = dict(r, n=n)
    grp = G.rid("grp", p1)
    kind = "card_neighbors" if with_card else "neighbors_" + ("event" if confirmed else "fault")
    out = []
    done = []
    for i, c in enumerate(calls):
        out.append(mkrow(base, "call", turn_prompt(p1, done), c, json.loads(c), grp, i + 1, kind))
        done.append(steps[i])
    pf = turn_prompt(p1, done)
    if not grounded(gold, pf):
        return None
    out.append(mkrow(base, "final", pf, json.dumps(gold, ensure_ascii=False), gold, grp, len(calls) + 1, kind))
    return out, {"kind": kind}


def sc_card(T):
    """short CARD (limits withheld): get_card, then the status follows the card limits (wide jitter)"""
    rng = T.rng
    lim = [c for c in GA.EX_W if GA.EC[c]["warning"] is not None]
    sn = T.sensor_for(rng.choice(lim))
    if sn is None:
        return None
    sn.card = G.wide_jit(sn.card, rng)
    n = rng.choice((18, 24, 36, 48))
    G.NF["n"] = n
    d = sn.card["warning"]["dir"]
    up = ("spike", "step_increase", "gradual_increase", "exponential_increase", "throttling")
    dn = ("dip", "step_decrease", "gradual_decrease")
    p = rng.choice(up if d == "high" else dn if d == "low" else up + dn)
    r = GA.gen_event_row(T, sn, "tool_card", p, rng.choice(("normal", "warning", "warning", "critical")))
    if not r or r["n"] != n:
        return None
    card, hist, end = r["card"], r["hist"], r["end_epoch"]
    p1 = short_card_prompt(r["prompt"], card, r["place"])
    c1 = call_json("get_card")
    p2 = turn_prompt(p1, [(c1, render_card(card, r["place"]))])
    gold = r["gold"]
    base = dict(r)
    grp = G.rid("grp", p1)
    return [mkrow(base, "call", p1, c1, json.loads(c1), grp, 1, "card"),
            mkrow(base, "final", p2, json.dumps(gold, ensure_ascii=False), gold, grp, 2, "card")], {"kind": "card"}


SC = {"history": (sc_history, 0.55), "neighbors": (sc_neighbors, 0.28), "card": (sc_card, 0.10),
      "card_neighbors": (lambda T: sc_neighbors(T, with_card=True), 0.07)}
