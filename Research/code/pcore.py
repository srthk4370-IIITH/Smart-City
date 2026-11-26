"""pcore.py: case -> app-identical agent prompts, rule view, orchestrator context, reasoner prompt (incident_v4), cheap-arm templates.
All the incident text goes through the same renderers the reasoner was trained and gated with (fmt_v4.render_v4 + Place on the IIITH campus tree)."""
import datetime as dt, json, random, re, sys, math, collections
import env_setup as ES
import pdata as D
from env_setup import G, FM, CD, EV, SG, L, M, G2, Q
import place as PL
sys.path.insert(0, Q + "/Code/smart-city-edge-agent/training")
import features as F          # noqa: E402  (training/app shared window spec + rule_pattern)
import generate_dataset as GD  # noqa: E402  (teacher rules = Mode 1: status_of / cause_of / action_of / observations)

IST = L.IST
dtime = lambda e: dt.datetime.fromtimestamp(e, IST)
SEV = {"normal": 0, "warning": 1, "sensor_fault": 2, "critical": 3}     # engine.go sevRank
CAUSAL = {   # orchestrator.go causal map (flagged role/metric -> related)
    "air_quality/co2": [("occupancy", "occ", "people in the room raise CO2"), ("hvac", "ac_units_on", "AC/ventilation state"), ("power", "power_kw", "room load follows occupancy and HVAC"), ("weather", "temp", "outdoor conditions")],
    "air_quality/temp": [("hvac", "room_temp", "AC controls room temperature"), ("weather", "temp", "outdoor heat load"), ("occupancy", "occ", "people add heat"), ("power", "power_kw", "cooling load")],
    "air_quality/rh": [("hvac", "ac_units_on", "AC dehumidifies"), ("weather", "rh", "outdoor humidity")],
    "air_quality/pm25": [("weather", "wind", "wind disperses/brings particles"), ("air_quality", "pm25", "other station shows if it is campus-wide"), ("weather", "rh", "humidity affects particle readings")],
    "air_quality/pm10": [("weather", "wind", "wind-blown dust"), ("air_quality", "pm10", "other station shows if it is campus-wide")],
    "water/level": [("water", "flow", "inflow/outflow explains level changes"), ("occupancy", "occ", "usage follows occupancy"), ("weather", "temp", "heat raises consumption")],
    "water/flow": [("water", "level", "tank level confirms consumption or leak"), ("occupancy", "occ", "usage follows occupancy")],
    "water/tds": [("water", "flow", "low flow / stagnation"), ("water", "level", "tank state")],
    "water/ph": [("water", "flow", "low flow / stagnation"), ("water", "tds", "water quality context")],
    "power/power_kw": [("hvac", "ac_units_on", "AC is the main load"), ("occupancy", "occ", "load follows occupancy"), ("weather", "temp", "heat drives cooling load")],
    "power/pf": [("power", "power_kw", "load level"), ("hvac", "ac_units_on", "inductive AC compressors")],
    "weather/temp": [("power", "power_kw", "cooling load"), ("air_quality", "temp", "indoor temperature"), ("hvac", "ac_units_on", "AC response")],
    "weather/rh": [("air_quality", "rh", "indoor humidity"), ("weather", "temp", "dew/temperature")],
    "weather/wind": [("air_quality", "pm25", "particle dispersion"), ("air_quality", "pm10", "dust")],
    "occupancy/occ": [("air_quality", "co2", "CO2 confirms presence"), ("power", "power_kw", "load confirms presence"), ("hvac", "ac_units_on", "AC use confirms presence")],
}
NICE = dict(GD.NICE)
NICE.setdefault("occ", "Occupancy")


# ------------------------------------------------------------------ sensors, windows, prompts
def rnd(xs, role, metric):
    if role == "occupancy":
        return [int(round(v)) for v in xs]
    if role == "hvac":
        return [int(round(v)) if metric == "ac_units_on" else round(v, 1) for v in xs]
    dec = F.METRICS[(role, metric)]["dec"]
    return [round(v, dec) for v in xs]


def agent_prompt_for(sdef, hist, end):
    """app-identical agent prompt (core/evidence.py == Go parity fixtures) for a flagged sensor; returns (prompt, card)"""
    cid = CD.metric_to_card(sdef["role"], sdef["metric"], sdef["node"], sdef["location"])
    card = json.loads(json.dumps(CD.existing_cards()[cid]))
    prompt, _st, _ev, _info = EV.agent_prompt(card, sdef["node"], sdef["location"], hist[-144:], 48, end)
    return prompt, card


def lim_head(card):
    w, c = card.get("warning"), card.get("critical")
    if not w or not c or "at" not in w:
        return []
    d = "above" if w["dir"] == "high" else "below"
    return ["LIMITS: warning %s %g, critical %s %g" % (d, w["at"], d, c["at"])]


def elines(prompt):
    u = prompt.split("user<|end_header_id|>", 1)[1].split("<|eot_id|>", 1)[0]
    return [[m.group(1), m.group(2)] for m in re.finditer(r"^(E\d+) (.*)$", u, re.M)]


# ------------------------------------------------------------------ rule view (Mode 1; python mirror of rules.go / hvacFinding)
def rule_finding(role, metric, xs48, end):
    if role == "hvac":
        return hvac_finding(metric, xs48, end)
    pat = F.rule_pattern(role, metric, xs48, end)
    if role == "occupancy":
        return occ_finding(pat, xs48, end)
    m = F.METRICS[(role, metric)]
    st = F.compute_stats(xs48, m["dec"])
    zero = max(abs(v) for v in xs48) < 1e-6 or (pat == "flatline" and abs(st["last"]) < 1e-6)
    status = GD.status_of(role, metric, pat, st, sum(xs48[:12]) / 12.0)
    if role == "air_quality" and metric == "co2" and st["last"] < 350 and status != "sensor_fault":
        status = "sensor_fault"      # rules.go plausibility check (indoor CO2 cannot sit below outdoor air)
    cause = GD.cause_of(role, metric, pat, status, F.is_off_hours(end), False, zero)
    obs = GD.observations(role, metric, pat, status, st, end, random.Random(0), F.is_off_hours(end), zero)
    return dict(pattern=pat, status=status, observations=list(obs)[:2], likely_cause=cause, confidence=0.8 if pat == "stable" else 0.7,
                action=GD.action_of(cause, status))


def occ_finding(pat, xs, end):
    st = F.occ_stats(xs)
    fr = "%.2f" % st["occupied_frac"]
    def mk(status, ob, cause, conf, act):
        return dict(pattern=pat, status=status, observations=ob, likely_cause=cause, confidence=conf, action=act)
    if pat == "vacant": return mk("normal", ["Room unoccupied for the whole 4-hour window [E2,E1]"], "vacant", 0.95, "none")
    if pat == "occupied": return mk("normal", ["Room occupied for most of the window (fraction %s) [E2]" % fr], "normal_occupancy", 0.92, "none")
    if pat == "arrival": return mk("normal", ["Room became occupied and is still occupied [E4,E1]"], "arrival", 0.9, "none")
    if pat == "departure": return mk("normal", ["Room was occupied earlier and is now empty [E5,E1]"], "departure", 0.9, "none")
    if pat == "intermittent":
        if st["toggles"] >= 12:
            return mk("sensor_fault", ["State flips %d times in 4 hours, too often for real movement [E3]" % st["toggles"]], "sensor_fault", 0.75, "check_sensor")
        return mk("normal", ["Presence comes and goes: %d state changes, occupied fraction %s [E3,E2]" % (st["toggles"], fr)], "intermittent_presence", 0.85, "monitor")
    return mk("warning", ["Presence detected during off-hours (occupied fraction %s) [E6,E2]" % fr], "off_hours_presence", 0.85, "request_facility_review")


def hvac_finding(metric, xs, end):
    st = F.compute_stats([float(v) for v in xs], 0 if metric == "ac_units_on" else 1)
    pat = "stable"
    try:
        pat = F.rule_pattern("power", "power_kw", xs, end) if metric == "ac_units_on" else F.rule_pattern("air_quality", "temp", xs, end)
    except Exception:
        pass
    if metric == "ac_units_on" and pat == "flatline":
        pat = "stable"
    status = "warning" if (metric == "room_temp" and st["last"] >= 30) else "normal"
    ob = ("AC units running: now %d, 1h average %.1f, max %d [E1,E6,E2]" % (round(st["last"]), st["sma_1h"], round(st["max"]))) if metric == "ac_units_on" else \
         ("Room temperature (AC sensors) %.1f C, trend %+.1f C/h [E1,E4]" % (st["last"], st["slope_per_h"]))
    return dict(pattern=pat, status=status, observations=[ob], likely_cause="hvac_context", confidence=0.8, action="none")


def informative(f):
    if f["status"] in ("warning", "critical"):
        return True
    return f["status"] == "normal" and f["pattern"] not in ("stable", "vacant", "-", "context")


# ------------------------------------------------------------------ orchestrator context (orchestrator.go ContextFor, max 4)
def pick_context(flagged, end, series, mx=4):
    """flagged: sensor defs; series: {key: 144-window} of every sensor available at `end` (injected values included)
    -> [(sdef, why, score, rule_finding)]"""
    taken = {s["key"] for s in flagged}
    opts = []
    for c in flagged:
        for (role, metric, why) in CAUSAL.get(c["role"] + "/" + c["metric"], []):
            best = None
            for sd in sorted(D.SENSORS, key=lambda x: x["node"]):
                if sd["role"] != role or sd["metric"] != metric or sd["key"] in taken or sd["key"] not in series:
                    continue
                sc = 0.0
                if sd["building"] == c["building"]:
                    sc += 3 + (1 if sd["level"] == c["level"] else 0)
                if role == "weather":
                    sc += 2
                if best is None or sc > best[2]:
                    best = (sd, why, sc)
            if best:
                taken.add(best[0]["key"]); opts.append(best)
    out = []
    for sd, why, sc in opts:
        f = rule_finding(sd["role"], sd["metric"], series[sd["key"]][-48:], end)
        if informative(f):
            sc += 2 + SEV[f["status"]]
        out.append((sd, why, sc, f))
    out.sort(key=lambda t: -t[2])
    return out[:mx]


# ------------------------------------------------------------------ agent output -> finding (Go Finding + enum gate)
PATS = set(F.CONT_PATTERNS) | set(F.OCC_PATTERNS)


def parse_agent(text):
    t = (text or "").strip()
    i = t.find('"action"')
    if i >= 0:
        t = t[:i]
    t = re.sub(r",\s*$", "", t.strip())
    for cand in (t, t + "}", t + "]}", t + '"}'):
        try:
            o = json.loads(cand)
            if isinstance(o, dict):
                return o
        except Exception:
            pass
    return None


def agent_finding(text, role):
    """-> (finding or None, valid): valid = parses and status / pattern / cause are in the role whitelists (policy-gate enum checks)"""
    o = parse_agent(text)
    if not o:
        return None, False
    f = dict(pattern=str(o.get("pattern", "")), status=str(o.get("status", "")), observations=[str(x) for x in (o.get("observations") or [])][:2],
             likely_cause=str(o.get("likely_cause", "")), confidence=o.get("confidence", 0.5), action=str(o.get("action") or "none"),
             data_quality=o.get("data_quality"), severity_reason=o.get("severity_reason"))
    try:
        f["confidence"] = max(0.0, min(1.0, float(f["confidence"])))
    except Exception:
        f["confidence"] = 0.5
    ok = f["status"] in SEV and f["pattern"] in PATS and f["likely_cause"] in F.CAUSES.get(role, ()) and bool(f["observations"])
    return f, ok


DQ = {"ok": "ok", "suspect": "suspect", "fault": "bad", "insufficient": "bad"}


def agent_data_line(f):
    dq = DQ.get(((f.get("data_quality") or {}).get("verdict") or "ok"), "suspect")
    rs = re.sub(r"\s+", " ", str(f.get("severity_reason") or "no reason given")).strip()[:140]
    return "dq=%s | reason: %s" % (dq, rs)
