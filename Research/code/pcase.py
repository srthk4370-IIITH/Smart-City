"""pcase.py: frozen case -> assembled incident (flagged + context sensors, agent prompts, rule view), reasoner user prompt, cheap-arm reports, trigger signals.
A frozen case (sets/*.jsonl) = {id, set, kind, family, end, flagged: [key..], series: {key: 144 values}, gold, ...}."""
import hashlib, json, random, re
import pcore as C
import pdata as D
from pcore import F, FM, G, SG, L, PL, CD, EV, dtime, SEV, NICE

SITE = {"site": None}
CAUSE_TO_LABEL = {   # reason.go causeToLabel
    "ventilation_insufficient": "ventilation_issue", "occupancy_load": "occupancy_driven_load", "outdoor_pollution_ingress": "air_pollution_event",
    "indoor_emission_source": "air_pollution_event", "hvac_cooling_issue": "hvac_or_thermal_issue", "humidity_control_issue": "hvac_or_thermal_issue",
    "possible_leak": "water_leak_or_overuse", "high_demand": "water_leak_or_overuse", "tank_draining": "water_leak_or_overuse",
    "supply_interruption": "water_supply_issue", "pump_cycling": "water_supply_issue", "tank_filling": "normal_operation",
    "water_quality_issue": "water_quality_issue", "load_surge": "power_load_anomaly", "equipment_startup": "power_load_anomaly",
    "load_drop_or_outage": "power_load_anomaly", "capacity_limit_throttling": "power_load_anomaly", "gradual_load_growth": "power_load_anomaly",
    "cyclic_equipment": "power_load_anomaly", "power_quality_issue": "power_quality_issue", "heat_buildup": "weather_driven",
    "cooling_trend": "weather_driven", "weather_front": "weather_driven", "gusty_wind": "weather_driven", "off_hours_presence": "occupancy_driven_load",
    "intermittent_presence": "occupancy_driven_load", "sensor_fault": "sensor_fault",
}
REPORT_LABELS = ["ventilation_issue", "hvac_or_thermal_issue", "occupancy_driven_load", "air_pollution_event", "water_leak_or_overuse", "water_supply_issue",
                 "water_quality_issue", "power_load_anomaly", "power_quality_issue", "weather_driven", "sensor_fault", "normal_operation", "unknown"]
AGENT_CAUSES = set(c for v in F.CAUSES.values() for c in v)


def case_hash_seed(cid):
    return int(hashlib.md5(cid.encode()).hexdigest()[:8], 16)


def place_env(cid):
    """Place on the IIITH campus tree; every campus device mapped to its host node (+ the AC-KH03 aggregate under KH level 03)"""
    R = random.Random(case_hash_seed(cid))
    site = SG.campus_site()
    G.set_site(site, R, agt=False)
    P = G.CUR["P"]
    for n in list(P.site["nodes"]):
        if n["kind"] == "sensor":
            P.host[n["device"]] = n["parent"]
    fl = next(n["id"] for n in P.site["nodes"] if n["kind"] == "floor" and n.get("parent") == "KH" and n.get("level") == "03")
    for m in ("ac_units_on", "room_temp"):
        if not any(x["id"] == "AC-KH03/" + m for x in P.site["nodes"]):
            P._add_node({"id": "AC-KH03/" + m, "kind": "sensor", "parent": fl, "device": "AC-KH03", "metric": m, "card": "", "dev_kind": "hvac"})
    P.host["AC-KH03"] = fl
    P.room = next((n["id"] for n in P.site["nodes"] if n["kind"] == "room"), P.room)
    return P


def assemble(case):
    """-> dict(sensors=[...], P, outdoor, end). sensors: flagged first (rule severity desc, then key), then up to 4 context sensors."""
    end = case["end"]; ser = case["series"]
    fl = [D.BY_KEY[k] for k in case["flagged"]]
    rf = {}
    for sd in fl:
        rf[sd["key"]] = C.rule_finding(sd["role"], sd["metric"], ser[sd["key"]][-48:], end)
    fl.sort(key=lambda s: (-SEV[rf[s["key"]]["status"]], s["key"]))
    ctx = C.pick_context(fl, end, ser)
    out = []
    for sd in fl:
        hist = ser[sd["key"]]
        prompt = card = None
        if sd["role"] != "hvac":
            prompt, card = C.agent_prompt_for(sd, hist, end)
        out.append(dict(sdef=sd, flagged=True, why=None, hist=hist, rule=rf[sd["key"]], prompt=prompt, card=card))
    for sd, why, _sc, f in ctx:
        out.append(dict(sdef=sd, flagged=False, why=why, hist=ser[sd["key"]], rule=f, prompt=None, card=None))
    for i, s in enumerate(out):
        s["ref"] = "S%d" % (i + 1)
    ot = None
    if "WE-VN04-00/temp" in ser:
        ot = (round(ser["WE-VN04-00/temp"][-1], 1), "WE-VN04-00", L.tstr(dtime(end)))
    return dict(sensors=out, outdoor=ot, end=end)


def agent_requests(a):
    """the NPU agent calls of this incident: flagged sensors with an LLM agent (hvac context only)"""
    return [dict(ref=s["ref"], key=s["sdef"]["key"], role=s["sdef"]["role"], prompt=s["prompt"]) for s in a["sensors"] if s["flagged"] and s["prompt"]]


def render_reasoner(case, a, findings):
    """findings: {ref: (finding|None, valid)} of the flagged agents -> the reasoner user prompt (incident_v4), sensors dicts, links"""
    P = place_env(case["id"])
    end_dt = dtime(a["end"])
    sens = []
    for s in a["sensors"]:
        sd = s["sdef"]; role, metric = sd["role"], sd["metric"]
        host = P.host.get(sd["node"], P.room)
        loc = P.loc(host)
        xs = s["hist"][-48:]
        ev = C.elines(s["prompt"]) if s["prompt"] else L.evidence(role, metric, xs, end_dt, None)
        head = C.lim_head(s["card"]) if s["card"] else []
        if s["flagged"] and s["prompt"]:
            f, ok = findings.get(s["ref"], (None, False))
            ag = None
            if f is not None and ok:
                ag = dict(pattern=f["pattern"], status=f["status"], cause=f["likely_cause"], conf=f["confidence"], obs=f["observations"])
            s["finding"] = f if ok else None
        else:
            f = s["rule"]
            ag = dict(pattern=f["pattern"], status=f["status"], cause=f["likely_cause"], conf=f["confidence"], obs=f["observations"])
            s["finding"] = f
        d = dict(ref=s["ref"], role=role, metric=metric, node=sd["node"], loc=loc, flagged=s["flagged"], why=s["why"], quality="good", head=head,
                 stale=None, ev=ev, agent=ag, unit_shown=("units" if metric == "ac_units_on" else None), rule=(s["rule"]["pattern"], s["rule"]["status"]))
        sens.append(d)
    h1 = sens[0]
    nearby = []
    n_id = "INC-%04d" % (case_hash_seed(case["id"]) % 9000 + 100)
    c = dict(end=end_dt, outdoor=a["outdoor"], inc_id=n_id, mode="early", win_h="4", sensors=sens, memory=list(case.get("memory") or []), notes=None)   # memory: retrieval-on ablation only (ablate_run --phase rt); [] = the main runs
    G.CUR.update(agt=False, nearby=[], suspect=None)
    ctx = G.build_ctx(c)
    ctx["agent_data"] = {s["ref"]: C.agent_data_line(s["finding"]) for s in a["sensors"] if s["flagged"] and s["prompt"] and s.get("finding")}
    user = FM.render_v4(c, ctx)
    return user, sens, ctx


def system_prompt():
    import prompts as PR
    return FM.system_v4(PR.SYSTEM_INCIDENT_SHORT)


# ------------------------------------------------------------------ cheap arm: Go isolatedReport / fallbackReport ports (reason.go:1090, fallback.go)
ID_RE = re.compile(r"\bE\d+\b")
FLAT_RULE = lambda s: s["rule"]


def _ev_ids(obs, ref, ev):
    for o in obs:
        for i in ID_RE.findall(o):
            x = "%s.%s" % (ref, i)
            if x not in ev:
                ev.append(x)


def isolated_report(sensors, calls):
    """Port of reason.go isolatedReport(sensors []SensorRef, calls []AgentCall).
    sensors: [{ref, role, metric, node, loc, context, rule(Finding)}]; calls[i] = (finding|None, valid) aligned with sensors."""
    s = sensors[0]
    f = s["rule"]; src = "rule finding (agent output rejected)"
    if calls[0][0] is not None and calls[0][1]:
        f = calls[0][0]; src = "domain agent finding"
    lab = CAUSE_TO_LABEL.get(f["likely_cause"], "") or "normal_operation"
    ev = []
    _ev_ids(f["observations"], s["ref"], ev)
    checked, faulty = [], []
    for c in sensors[1:]:
        if c["rule"]["status"] == "sensor_fault":
            faulty.append("%s %s (%s)" % (c["node"], NICE.get(c["metric"], ""), c["ref"]))
            continue
        checked.append("%s %s (%s)" % (NICE.get(c["metric"], ""), c["rule"]["pattern"].replace("_", " "), c["ref"]))
        x = c["ref"] + ".E1"
        if x not in ev:
            ev.append(x)
    if not ev:
        ev = [s["ref"] + ".E1"]
    expl = " ".join(f["observations"]) + " (from " + src + ")."
    if checked:
        expl += " Related domains checked and steady: " + ", ".join(checked) + ", so the cause is local to this domain."
    if faulty:
        expl += " Data quality note: related sensor(s) look faulty and were not used: " + ", ".join(faulty) + "."
    return dict(root_cause="%s %s on %s (%s)" % (NICE.get(s["metric"], ""), f["pattern"].replace("_", " "), s["loc"], f["likely_cause"].replace("_", " ")),
                label=lab, affected_domains=[s["role"]], evidence=ev, confidence=f["confidence"], action=f.get("action", "none"), explanation=expl,
                severity=f["status"], model="deterministic (related domains verified steady)")


def fallback_report(sensors, calls):
    """Port of fallback.go fallbackReport (cross-domain template from validated findings, most severe leads); rejected = nil"""
    good = []
    for s, (f, ok) in zip(sensors, calls):
        if f is not None and ok:
            good.append((s, f))
    if not good:
        good = [(s, s["rule"]) for s in sensors if not s.get("context")]
    if not good:
        return None
    good.sort(key=lambda t: (-SEV[t[1]["status"]], -t[1]["confidence"]))
    ls, lf = good[0]
    lab = CAUSE_TO_LABEL.get(lf["likely_cause"], "")
    if lab == "" and lf["likely_cause"] in AGENT_CAUSES:
        lab = "normal_operation"
    if lab not in REPORT_LABELS:
        lab = "unknown"
    doms, ev, lines = [], [], []
    for s, f in good:
        if s["role"] not in doms:
            doms.append(s["role"])
        _ev_ids(f["observations"], s["ref"], ev)
        lines.append("%s (%s): %s, %s - %s" % (NICE.get(s["metric"], ""), s["ref"], f["pattern"].replace("_", " "), f["status"], f["likely_cause"].replace("_", " ")))
    if not ev:
        ev = [ls["ref"] + ".E1"]
    expl = "Cross-domain summary assembled by policy from the domain agents that passed the safety check, because the synthesizer's own report was rejected. " + "; ".join(lines) + "."
    if len(doms) > 1:
        expl += " %d domains are involved: %s." % (len(doms), ", ".join(doms))
    conf = min([f["confidence"] for _, f in good] + [lf["confidence"]])
    return dict(root_cause="%s %s on %s (%s)" % (NICE.get(ls["metric"], ""), lf["pattern"].replace("_", " "), ls["loc"], lf["likely_cause"].replace("_", " ")),
                label=lab, affected_domains=doms, evidence=ev, confidence=conf, action=lf.get("action", "none"), explanation=expl, severity=lf["status"],
                model="deterministic (cross-domain template from validated findings)")
