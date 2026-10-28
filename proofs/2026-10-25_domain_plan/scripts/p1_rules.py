"""P1 rules, Python mirror of app/backend postrules.go (long drain + E9 keep-leak) and claimcheck.go (hvac_rule).
Importing registers into trackb_lib.RULES:
  rel_level_p1 / water_cause_p1 : the live rules with the daytime long-drain leak routine and the keep-leak guard
  hvac_rule                      : HVAC teacher (= Go ClassifyHVAC on the same window) overrides a normal model answer
ALL_P1 = the live order with those swapped in (= Go post_rules=all after P1).
regold(rows): the label-definition change applied to stored gold (daytime long drain -> warning / possible_leak)."""
import json, re
import dp_lib as D

L, C = D.L, D.C
TE, F = L.TE, L.F
DRAIN_PTS = 36
HV_EVENT = ("too_hot", "too_cold", "slow_recovery", "no_cooling_effect", "short_cycling", "stuck_on", "stuck_off",
            "running_empty_room", "unit_alarm")


def long_drain(xs, noise):
    n = len(xs or [])
    if n < DRAIN_PTS:
        return False
    seg = xs[n - DRAIN_PTS:]
    drop = seg[0] - seg[-1]
    if drop <= 0 or drop < max(10 * noise, 0.05 * abs(seg[0])):
        return False
    lo, rise = seg[0], 0.0
    for v in seg:
        lo = min(lo, v)
        rise = max(rise, v - lo)
    return rise <= max(3 * noise, 0.1 * drop)


RX_E9 = re.compile(r"^E9 [^\n]*", re.M)


def e9_falling(prompt):
    m = RX_E9.search(prompt or "")
    return bool(m) and "slow drift -" in m.group(0)


def routine_p1(c, pattern, status):
    r = TE.routine_rule(c.role, c.metric, c.node, pattern, status, c.st, c.end, c.n)
    if (r and c.role == "water" and c.metric == "level" and pattern == "gradual_decrease" and r[1] == "tank_draining"
            and long_drain(c.xs, c.st["noise"])):
        return ("warning", "possible_leak", "why_day_leak")
    return r


def keep_leak(c, p):
    return (c.role == "water" and c.metric == "level" and p["likely_cause"] == "possible_leak" and p["status"] in ("warning", "critical")
            and (e9_falling(c.prompt) or long_drain(c.xs, c.st["noise"])))


def r_rel_level_p1(c, p):
    if c.role != "water" or c.metric != "level" or c.st is None:
        return []
    if p["status"] not in ("normal", "warning", "critical") or p["pattern"] == "flatline" or keep_leak(c, p):
        return []
    L._tank_patch(c)
    s = L.status_go(c.role, c.metric, p["pattern"], c.st, c.base)
    r = routine_p1(c, p["pattern"], s)
    s = r[0] if r else s
    return [("status", s)] if s != p["status"] and s in ("normal", "warning", "critical") else []


def r_water_cause_p1(c, p):
    if c.role != "water" or c.metric not in ("flow", "level") or c.st is None or p["status"] == "sensor_fault" or keep_leak(c, p):
        return []
    L._tank_patch(c)
    s = L.status_go(c.role, c.metric, p["pattern"], c.st, c.base)
    r = routine_p1(c, p["pattern"], s)
    return [("likely_cause", r[1])] if r and r[1] != p["likely_cause"] else []


def r_hvac_rule(c, p):
    if c.role != "hvac":
        return []
    g = C.gold_of(c.row)   # HVAC gold = hvac.label_hvac on this window = Go HVACRuleFinding (parity-tested)
    if g["status"] not in ("warning", "critical") or g["pattern"] not in HV_EVENT:
        return []
    if p["status"] not in ("sensor_fault", "normal") and p["pattern"] not in D.HV_NORMAL:
        return []
    out = [(k, g[gk]) for k, gk in (("pattern", "pattern"), ("status", "status"), ("likely_cause", "likely_cause"),
                                    ("event_active", "event_active")) if p.get(k) != g[gk]]
    return out


L.RULES.update(rel_level_p1=r_rel_level_p1, water_cause_p1=r_water_cause_p1, hvac_rule=r_hvac_rule)
ALL_P1 = [{"rel_level": "rel_level_p1", "water_cause": "water_cause_p1"}.get(r, r) for r in D.ALL] + ["hvac_rule"]
NAMES = {"ALL_P1": ALL_P1}


def regold(rows):
    """label-definition change (P1a) on stored gold; returns ids changed."""
    ch = []
    for i, r in rows.items():
        if r.get("role") != "water" or r.get("metric") != "level":
            continue
        g = C.gold_of(r)
        if g["pattern"] != "gradual_decrease" or g["status"] != "normal" or g["likely_cause"] != "tank_draining":
            continue
        c = L.Ctx(r)
        if c.xs is None or F.is_off_hours(c.end) or not long_drain(c.xs, c.st["noise"]):
            continue
        g.update(status="warning", likely_cause="possible_leak", action=TE.action_of("possible_leak", "warning"))
        r["completion"] = json.dumps(g, ensure_ascii=False) + "<|eot_id|>"
        r["regold"] = "p1a_day_leak"
        ch.append(i)
    return ch
