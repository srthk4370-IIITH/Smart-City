"""Spec cards (V3_DESIGN §2.1): schema, the cards of today's metrics, synthetic metric cards, renderers.

A card says what a sensor measures, its limits, impossible values and normal behaviour. Agents (agt_v3) read the
FULL card; the reasoner (rsn_v4) reads the ONE-LINE card. Every gold label is a function of the card + evidence.

Public API (stable; see core/API.md):
  SCHEMA_VERSION, CARD_KEYS
  existing_cards() -> {card_id: card}          today's 16 metrics (+ context variants) and the HVAC unit
  metric_to_card(role, metric, node="")        today's (role, metric[, node prefix]) -> card_id
  synthetic_card(type_name, rng, jitter=True)  one random card of a synthetic type (TRAIN_TYPES / TEST_TYPES)
  jitter_card(card, rng, frac=0.15)            +-15 % on limits (the "read the card, not memory" rows)
  render_full(card, place=None) -> str         agent CARD block (multi-line)
  render_line(card) -> str                     reasoner one-line card
  validate_card(card) -> list[str]             schema problems (empty = ok)
  patterns_for(card), metric_key(card)         pattern list by kind; (role, metric) key used by the E-line code
"""
from __future__ import annotations

import copy
import math
import random

SCHEMA_VERSION = "card-1"
CARD_KEYS = ("card_id", "quantity", "unit", "kind", "domain", "decimals", "context", "normal", "warning", "critical",
             "impossible", "noise", "floor", "max_step", "rate_rules", "dynamics", "cycle", "causes", "actions",
             "faults", "tank", "rules")
KINDS = ("continuous", "binary_state", "count", "hvac_unit")
CONT_PATTERNS = ("stable", "spike", "dip", "gradual_increase", "gradual_decrease", "step_increase", "step_decrease",
                 "exponential_increase", "oscillation", "throttling", "flatline", "erratic")
OCC_PATTERNS = ("vacant", "occupied", "arrival", "departure", "intermittent", "off_hours_presence")
HVAC_PATTERNS = ("stable", "normal_cycling", "pull_down", "setback_drift", "too_hot", "too_cold", "slow_recovery",
                 "no_cooling_effect", "short_cycling", "stuck_on", "stuck_off", "running_empty_room", "unit_alarm",
                 "flatline", "erratic", "bias_jump", "biased_reading", "calibration_drift", "dropout", "saturation",
                 "quantised")
FAULTS_ALL = ("stuck", "bias", "drift", "noise", "dropout", "saturation", "quantised")
DOMAIN_NAMES = {"air_quality": "Air Quality", "water": "Water", "power": "Power", "weather": "Weather",
                "occupancy": "Occupancy", "hvac": "HVAC", "environment": "Environment", "building": "Building",
                "safety": "Safety", "equipment": "Equipment"}
BASE_ACTIONS = ("none", "monitor", "inspect_ventilation", "inspect_hvac", "check_sensor", "inspect_water_system",
                "inspect_electrical", "review_schedule", "request_facility_review")


def patterns_for(card):
    return {"binary_state": OCC_PATTERNS, "hvac_unit": HVAC_PATTERNS}.get(card["kind"], CONT_PATTERNS)


def metric_key(card):
    """(role, metric) under which the E-line code finds dec/floor/unit: today's key for existing cards,
    ("card", card_id) for synthetic ones (registered by core.evidence.register)."""
    r = card.get("rules", {})
    if r.get("legacy_key"):
        return tuple(r["legacy_key"])
    return ("card", card["card_id"])


# --------------------------------------------------------------------------------------------- formatting
def num(v):
    """Card number: shortest exact text (1000, 0.85, 6.5, 1e-3 -> 0.001)."""
    if v is None:
        return ""
    if isinstance(v, int) or float(v).is_integer():
        return str(int(v))
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s


def _lim_text(card, which):
    lim = card[which]
    if not lim:
        return None
    if lim["dir"] == "both":
        return f"{which} below {num(lim['low'])} or above {num(lim['high'])}"
    return f"{which} {'above' if lim['dir'] == 'high' else 'below'} {num(lim['at'])}"


def _imp_text(card):
    imp = card.get("impossible") or {}
    a, b = imp.get("below"), imp.get("above")
    if a is not None and b is not None:
        return f"impossible below {num(a)} or above {num(b)}"
    if a is not None:
        return f"impossible below {num(a)}"
    if b is not None:
        return f"impossible above {num(b)}"
    return None


def rate_text(rr):
    """rate_rules -> one line. Semantics (teacher_v3.status_rate): change = window max - min, compared with
    the mean of the window's first hour."""
    if rr["abrupt_warn"] <= 0:
        a = f"step, spike, dip or fast rise = warning, critical above {num(round(rr['abrupt_crit'] * 100))}%"
    else:
        a = (f"step, spike, dip or fast rise warning above {num(round(rr['abrupt_warn'] * 100))}%, "
             f"critical above {num(round(rr['abrupt_crit'] * 100))}%")
    g = f"gradual change warning above {num(round(rr['gradual_warn'] * 100))}%"
    if rr.get("gradual_crit"):
        g += f", critical above {num(round(rr['gradual_crit'] * 100))}%"
    o = "cycling " + rr.get("osc", "normal")
    return f"rate rule (change = max - min vs first-hour mean): {a}; {g}; {o}"


def unit_shown(card):
    return card["unit"] or "ratio"


def render_full(card, place=None):
    """Agent CARD block. place = room text like "lecture hall, capacity 120" (or None)."""
    head = f"CARD: {card['quantity']} [{unit_shown(card)}], {card['kind']}, {card['context']}"
    if place:
        head += f" ({place})"
    parts = []
    if card.get("normal"):
        parts.append(f"normal {num(card['normal'][0])}-{num(card['normal'][1])}")
    w, c = _lim_text(card, "warning"), _lim_text(card, "critical")
    if w:
        parts.append(w)
    if c:
        parts.append(c)
    if not w and not c:
        parts.append("no fixed limits")
    it = _imp_text(card)
    if it:
        parts.append(it)
    if card.get("noise") is not None:
        parts.append(f"noise {num(card['noise'])}")
    if card.get("max_step"):
        parts.append(f"max 5-min change {num(card['max_step'])}")
    lines = [head, "  " + " | ".join(parts)]
    if card.get("rate_rules"):
        lines.append("  " + rate_text(card["rate_rules"]))
    if card.get("tank"):
        t = card["tank"]
        lines.append(f"  tank: high level above {num(t['high'])}, overflow risk above {num(t['overflow'])}; "
                     f"usual fill up to {num(t['fill_min'])} min")
    if card.get("dynamics"):
        lines.append("  dynamics: " + card["dynamics"])
    if card.get("cycle"):
        lines.append("  cycle: " + card["cycle"])
    return "\n".join(lines)


def render_line(card):
    """Reasoner one-line card (~25 tokens)."""
    u = card["unit"] or "ratio"
    parts = [f"card: {card.get('short', card['quantity'])} {u}"]
    if card["kind"] in ("binary_state", "hvac_unit"):
        parts.append(card["kind"])
    if card.get("normal"):
        parts.append(f"normal {num(card['normal'][0])}-{num(card['normal'][1])}")
    for which, tag in (("warning", "warn"), ("critical", "crit")):
        lim = card.get(which)
        if lim:
            if lim["dir"] == "both":
                parts.append(f"{tag} <{num(lim['low'])} or >{num(lim['high'])}")
            else:
                parts.append(f"{tag} {'>' if lim['dir'] == 'high' else '<'}{num(lim['at'])}")
    rr = card.get("rate_rules")
    if rr:
        parts.append(f"no fixed limit | warn: abrupt change | crit +{num(round(rr['abrupt_crit'] * 100))}% vs first hour")
    imp = card.get("impossible") or {}
    if imp.get("below") is not None:
        parts.append(f"impossible <{num(imp['below'])}")
    elif imp.get("above") is not None:
        parts.append(f"impossible >{num(imp['above'])}")
    if card.get("line_hint"):
        parts.append(card["line_hint"])
    return " | ".join(parts)


# --------------------------------------------------------------------------------------------- schema check
def validate_card(c):
    bad = []
    for k in CARD_KEYS:
        if k not in c:
            bad.append(f"missing {k}")
    if bad:
        return bad
    if c["kind"] not in KINDS:
        bad.append("kind")
    if c["domain"] not in DOMAIN_NAMES:
        bad.append("domain")
    for which in ("warning", "critical"):
        lim = c[which]
        if lim is None:
            continue
        if lim.get("dir") not in ("high", "low", "both"):
            bad.append(f"{which}.dir")
        if lim["dir"] == "both" and not ("low" in lim and "high" in lim):
            bad.append(f"{which} both needs low/high")
        if lim["dir"] != "both" and "at" not in lim:
            bad.append(f"{which}.at")
    w, cr = c["warning"], c["critical"]
    if w and cr and w["dir"] == cr["dir"]:
        if w["dir"] == "high" and not cr["at"] > w["at"]:
            bad.append("critical must be above warning")
        if w["dir"] == "low" and not cr["at"] < w["at"]:
            bad.append("critical must be below warning")
        if w["dir"] == "both" and not (cr["low"] < w["low"] and cr["high"] > w["high"]):
            bad.append("both: critical outside warning")
    if (w is None) != (cr is None):
        bad.append("warning/critical must both be set or both null")
    if c["kind"] == "continuous" and w is None and not c["rate_rules"] and not c["rules"].get("routines"):
        bad.append("no limits and no rate rule")
    imp = c["impossible"] or {}
    if c["normal"] and imp.get("below") is not None and imp["below"] > c["normal"][0]:
        bad.append("impossible.below above normal low")
    if c["normal"] and imp.get("above") is not None and imp["above"] < c["normal"][1]:
        bad.append("impossible.above below normal high")
    if not c["causes"] or "sensor_fault" not in c["causes"] and c["kind"] != "binary_state":
        bad.append("causes must include sensor_fault")
    for a in c["actions"]:
        if a not in BASE_ACTIONS + ("switch_off_ac",):
            bad.append(f"action {a}")
    for f in c["faults"]:
        if f not in FAULTS_ALL:
            bad.append(f"fault {f}")
    ca = c["rules"].get("cause_action", {})
    for cause in c["causes"]:
        if cause not in ca:
            bad.append(f"cause_action missing {cause}")
    return bad


# --------------------------------------------------------------------------------------------- existing cards
# Values restate today's backend exactly: features.go Metrics (limits, dir, decimals, floor, lo/hi), rules.go
# (indoor CO2 < 350 = sensor fault), teacher_v2.RATE (physical max 5-min change), postrules.go / rules.go relative
# branch (rate rule 0 / 150 % / 30 %), teacher_v2 routine rules (cycle text), node_limits_v2.json (tank lines).
G_ACTION = {"normal_conditions": "none", "occupancy_load": "inspect_ventilation", "ventilation_insufficient": "inspect_ventilation",
            "outdoor_pollution_ingress": "monitor", "indoor_emission_source": "inspect_ventilation",
            "hvac_cooling_issue": "inspect_hvac", "humidity_control_issue": "inspect_hvac", "sensor_fault": "check_sensor",
            "normal_usage": "none", "high_demand": "monitor", "possible_leak": "inspect_water_system",
            "tank_filling": "none", "tank_draining": "none", "supply_interruption": "inspect_water_system",
            "pump_cycling": "monitor", "water_quality_issue": "inspect_water_system", "normal_load": "none",
            "load_surge": "monitor", "equipment_startup": "monitor", "load_drop_or_outage": "inspect_electrical",
            "capacity_limit_throttling": "inspect_electrical", "gradual_load_growth": "monitor",
            "cyclic_equipment": "none", "power_quality_issue": "inspect_electrical", "normal_weather": "none",
            "heat_buildup": "monitor", "cooling_trend": "none", "weather_front": "monitor", "gusty_wind": "monitor",
            "diurnal_cycle": "none", "vacant": "none", "normal_occupancy": "none", "arrival": "none",
            "departure": "none", "intermittent_presence": "none", "off_hours_presence": "review_schedule",
            "tank_overflow_risk": "inspect_water_system", "fill_valve_stuck": "inspect_water_system"}

AQ_CAUSES = ["normal_conditions", "occupancy_load", "ventilation_insufficient", "outdoor_pollution_ingress",
             "indoor_emission_source", "hvac_cooling_issue", "humidity_control_issue", "sensor_fault"]
WATER_CAUSES = ["normal_usage", "high_demand", "possible_leak", "tank_filling", "tank_draining", "supply_interruption",
                "pump_cycling", "water_quality_issue", "sensor_fault", "tank_overflow_risk", "fill_valve_stuck"]
POWER_CAUSES = ["normal_load", "load_surge", "equipment_startup", "load_drop_or_outage", "capacity_limit_throttling",
                "gradual_load_growth", "cyclic_equipment", "power_quality_issue", "sensor_fault"]
WEATHER_CAUSES = ["normal_weather", "heat_buildup", "cooling_trend", "weather_front", "gusty_wind", "diurnal_cycle",
                  "sensor_fault"]
OCC_CAUSES = ["vacant", "normal_occupancy", "arrival", "departure", "intermittent_presence", "off_hours_presence",
              "sensor_fault"]
DEFAULT_RATE = {"abrupt_warn": 0.0, "abrupt_crit": 1.5, "gradual_warn": 0.3, "gradual_crit": None, "osc": "normal"}


def _card(cid, quantity, unit, kind, domain, dec, context, normal, warn, crit, imp, noise, floor, max_step, rate,
          dynamics, cycle, causes, faults, legacy, rules=None, short=None, line_hint=None, tank=None, actions=None):
    r = {"legacy_key": list(legacy) if legacy else None, "cause_action": {c: G_ACTION.get(c, "monitor") for c in causes},
         "erratic_fault": True, "zero_ok": False, "drift_fault": False, "routines": [], "recur_cause": None,
         "normal_cause": causes[0], "sensor_range": None}
    r.update(rules or {})
    # every action the escalation (teacher action_of) can produce stays in the list; continuous cards list every fault kind
    acts = list(actions or BASE_ACTIONS)
    if kind in ("continuous", "count"):
        faults = list(FAULTS_ALL)
    return {"card_id": cid, "quantity": quantity, "unit": unit, "kind": kind, "domain": domain, "decimals": dec,
            "context": context, "normal": normal, "warning": warn, "critical": crit, "impossible": imp, "noise": noise,
            "floor": floor, "max_step": max_step, "rate_rules": rate, "dynamics": dynamics, "cycle": cycle,
            "causes": list(causes), "actions": acts, "faults": list(faults), "tank": tank, "rules": r,
            "short": short or quantity, "line_hint": line_hint}


def H(at):
    return {"dir": "high", "at": at}


def L(at):
    return {"dir": "low", "at": at}


def existing_cards():
    C = {}
    allf = list(FAULTS_ALL)
    C["co2_indoor"] = _card(
        "co2_indoor", "CO2 concentration", "ppm", "continuous", "air_quality", 0, "indoor room", [400, 1000], H(1000), H(1500),
        {"below": 350, "above": 5000}, 6, 40, 150, None,
        "rises with people, +300-800 ppm/h when full; back near 450 within ~1 h of vacancy; outdoor ~420",
        "rise between 08:00 and 20:00 below the limits = normal occupancy; any fall below the limits = normal decay",
        AQ_CAUSES, allf, ("air_quality", "co2"), short="CO2", line_hint="follows occupancy, lag 10-30 min",
        rules={"drift_fault": True, "recur_cause": "occupancy_load", "normal_cause": "normal_conditions",
               "sensor_range": [250, 5000], "indoor": True,
               "routines": [{"type": "rise_in_hours", "patterns": ["gradual_increase", "step_increase"], "from": 8, "to": 20,
                             "cause": "occupancy_load", "below_only": True},
                            {"type": "pattern_normal", "patterns": ["gradual_decrease"], "cause": "normal_conditions",
                             "below_only": True}]})
    for ctx_, indoor in (("indoor", True), ("outdoor", False)):
        for met, q, dec, w, c, fl in (("pm25", "PM2.5", 1, 60, 120, 6), ("pm10", "PM10", 1, 100, 250, 10)):
            cid = f"{met}_{ctx_}"
            rt = [] if indoor else [{"type": "pattern_normal", "patterns": ["gradual_increase", "gradual_decrease",
                                                                            "step_increase", "oscillation"],
                                     "cause": "normal_conditions", "below_only": True}]
            C[cid] = _card(
                cid, f"{q} particulate matter", "ug/m3", "continuous", "air_quality", dec,
                "indoor room" if indoor else "outdoor air station", [0, w], H(w), H(c), {"below": 0, "above": 1000}, 1.0, fl,
                None, None,
                ("follows outdoor air with a 20-90 min lag; cooking, cleaning or dust inside give short spikes" if indoor else
                 "traffic peaks 08-10 and 19-22, higher on still winter nights, dust events with wind, rain washes it out"),
                ("no daily rule; spikes are events" if indoor else
                 "rises, falls, steps and cycles below the limits are normal outdoor variation"),
                AQ_CAUSES, ["stuck", "bias", "noise", "dropout", "saturation", "quantised"], ("air_quality", met), short=q,
                line_hint="follows outdoor air" if indoor else "outdoor driver",
                rules={"recur_cause": "indoor_emission_source", "normal_cause": "normal_conditions", "indoor": indoor,
                       "sensor_range": [0, 1000], "routines": rt})
    C["temp_indoor"] = _card(
        "temp_indoor", "room air temperature", "C", "continuous", "air_quality", 1, "indoor room", [20, 30], H(30), H(34),
        {"below": 5, "above": 55}, 0.15, 0.6, 1.0, None,
        "follows AC: falls 1-3 C/h when cooling starts, rises 0.3-1 C/h when AC is off; people and sun add heat",
        "AC cycling of up to 2 C range below the limits is normal",
        AQ_CAUSES, ["stuck", "bias", "drift", "noise", "dropout", "quantised"], ("air_quality", "temp"), short="room temp",
        line_hint="follows AC and outdoor heat",
        rules={"drift_fault": True, "recur_cause": "normal_conditions", "normal_cause": "normal_conditions", "indoor": True,
               "routines": [{"type": "osc_small", "max_range": 2.0, "cause": "normal_conditions"}]})
    C["rh_indoor"] = _card(
        "rh_indoor", "room relative humidity", "%", "continuous", "air_quality", 1, "indoor room", [30, 70], H(70), H(85),
        {"below": 1, "above": 100}, 0.6, 3, 5.0, None,
        "AC dries the air (-5 to -15 %); rises with outdoor humidity, rain and crowds",
        "no daily rule", AQ_CAUSES, allf, ("air_quality", "rh"), short="room RH",
        rules={"drift_fault": True, "recur_cause": "normal_conditions", "normal_cause": "normal_conditions", "indoor": True,
               "sensor_range": [1, 100]})
    C["tank_level"] = _card(
        "tank_level", "water tank level", "level", "continuous", "water", 1, "water tank", None, None, None,
        {"below": 0, "above": 500}, 0.5, 4, None, dict(DEFAULT_RATE, osc="warning"),
        "pump refills raise it in 30-120 min; use drains it slowly by day; a fall at night means water is lost",
        ("a rise is a refill (normal); a fall 06:00-22:00 is normal use unless it drains 3 h with no refill; "
         "a fall or repeated refills at night (22:00-06:00) = warning; pump cycling every 50 min or more is normal"),
        WATER_CAUSES, ["stuck", "bias", "noise", "dropout", "quantised"], ("water", "level"), short="tank level",
        line_hint="falls with use, rises on refills",
        rules={"recur_cause": "pump_cycling", "normal_cause": "normal_usage", "zero_ok": False,
               "routines": [{"type": "tank"}, {"type": "pump_cycle", "min_period": 50, "cause": "pump_cycling"}]})
    C["water_flow"] = _card(
        "water_flow", "water flow rate", "m3/h", "continuous", "water", 2, "pipe flow meter", None, None, None,
        {"below": 0, "above": 40}, 0.05, 0.4, None, dict(DEFAULT_RATE, osc="warning"),
        "follows demand and pump runs; near zero at night; steady flow at night means a leak",
        "pump cycling every 50 min or more is normal; shorter cycling = warning",
        WATER_CAUSES[:9], ["stuck", "bias", "noise", "quantised"], ("water", "flow"), short="flow",
        rules={"recur_cause": "normal_usage", "normal_cause": "normal_usage", "zero_ok": True,
               "routines": [{"type": "pump_cycle", "min_period": 50, "cause": "pump_cycling"}]})
    C["water_tds"] = _card(
        "water_tds", "total dissolved solids", "ppm", "continuous", "water", 0, "water supply", [0, 500], H(500), H(1000),
        {"below": 0, "above": 1000}, 5, 15, 50.0, None,
        "nearly flat; slow rise when water stagnates; jumps with a source change", "no daily rule",
        WATER_CAUSES[:9], ["stuck", "bias", "noise", "quantised", "saturation"], ("water", "tds"), short="TDS",
        rules={"recur_cause": "water_quality_issue", "normal_cause": "normal_usage", "zero_ok": True, "sensor_range": [0, 1000],
               "quality_cause": True})
    C["water_ph"] = _card(
        "water_ph", "water pH", "pH", "continuous", "water", 2, "water supply", [6.5, 8.5],
        {"dir": "both", "low": 6.5, "high": 8.5}, {"dir": "both", "low": 6.0, "high": 9.0},
        {"below": 0, "above": 14}, 0.05, 0.25, 0.3, None,
        "nearly flat; drifts slowly with stagnation or dosing", "no daily rule",
        WATER_CAUSES[:9], ["stuck", "bias", "noise", "quantised"], ("water", "ph"), short="pH",
        rules={"recur_cause": "water_quality_issue", "normal_cause": "normal_usage", "zero_ok": False, "quality_cause": True})
    C["power_load"] = _card(
        "power_load", "electrical load", "kW", "continuous", "power", 2, "energy meter", None, None, None,
        {"below": 0, "above": 2000}, 0.1, 0, None, dict(DEFAULT_RATE),
        "base load plus people, lights and AC compressors; steps when equipment switches",
        ("on workdays a start-up step 07:00-10:30 and a shut-down step 17:00-21:00 are normal; on/off cycling is normal; "
         "erratic load is a power-quality issue, not a sensor fault"),
        POWER_CAUSES, ["stuck", "bias", "dropout", "quantised"], ("power", "power_kw"), short="power",
        line_hint="follows occupancy and AC",
        rules={"recur_cause": "cyclic_equipment", "normal_cause": "normal_load", "erratic_fault": False, "zero_ok": True,
               "routines": [{"type": "osc_normal", "cause": "cyclic_equipment"},
                            {"type": "workday_steps", "up": [7.0, 10.5], "down": [17.0, 21.0],
                             "cause_up": "equipment_startup", "cause_down": "normal_load"}]})
    C["power_solar"] = _card(
        "power_solar", "solar PV output", "kW", "continuous", "power", 2, "rooftop solar inverter", None, None, None,
        {"below": 0, "above": 2000}, 0.05, 0, None, dict(DEFAULT_RATE),
        "zero at night, bell-shaped by day; clouds cut it in steps",
        "a rise ending 06:00-12:00 and a fall ending 12:00-19:00 are the normal solar day",
        POWER_CAUSES, ["stuck", "bias", "dropout", "quantised"], ("power", "power_kw"), short="solar",
        line_hint="daylight bell, zero at night",
        rules={"recur_cause": "cyclic_equipment", "normal_cause": "normal_load", "erratic_fault": False, "zero_ok": True,
               "routines": [{"type": "solar", "rise": [6, 12], "fall": [12, 19], "cause": "normal_load"}]})
    C["power_pf"] = _card(
        "power_pf", "power factor", "", "continuous", "power", 3, "feeder meter", [0.85, 1.0], L(0.85), L(0.7),
        {"below": 0, "above": 1}, 0.005, 0.03, 0.15, None,
        "near 0.95-1.0; dips when many AC compressors and motors run", "no daily rule",
        POWER_CAUSES, ["stuck", "bias", "noise", "dropout", "quantised"], ("power", "pf"), short="PF",
        line_hint="dips with inductive (AC) load",
        rules={"recur_cause": "normal_load", "normal_cause": "normal_load", "sensor_range": [0, 1]})
    C["weather_temp"] = _card(
        "weather_temp", "outdoor air temperature", "C", "continuous", "weather", 1, "rooftop weather station",
        [10, 38], H(38), H(42), {"below": 5, "above": 50}, 0.08, 0.8, 1.5, None,
        "daily cycle: lowest near 06:00, highest near 14:00-15:00; rain cools 2-5 C",
        "a rise ending 07:00-15:00 (up to +3 C/h) and a fall ending 15:00-07:00 (down to -3 C/h) below the limits = diurnal cycle",
        WEATHER_CAUSES, ["stuck", "bias", "noise", "dropout", "quantised"], ("weather", "temp"), short="outdoor temp",
        line_hint="outdoor driver",
        rules={"recur_cause": "normal_weather", "normal_cause": "normal_weather",
               "routines": [{"type": "diurnal", "rise": [7, 15], "max_slope": 3.0, "invert": False, "cause": "diurnal_cycle"}]})
    C["weather_rh"] = _card(
        "weather_rh", "outdoor relative humidity", "%", "continuous", "weather", 1, "rooftop weather station",
        [20, 90], H(90), H(97), {"below": 1, "above": 100}, 0.3, 4, 8.0, None,
        "daily cycle opposite to temperature: highest near dawn, lowest mid-afternoon; rain pushes it to 90-100",
        "a fall ending 07:00-15:00 and a rise ending 15:00-07:00 below the limits = diurnal cycle",
        WEATHER_CAUSES, ["stuck", "bias", "noise", "dropout", "quantised"], ("weather", "rh"), short="outdoor RH",
        rules={"recur_cause": "normal_weather", "normal_cause": "normal_weather",
               "routines": [{"type": "diurnal", "rise": [7, 15], "max_slope": None, "invert": True, "cause": "diurnal_cycle"}]})
    C["weather_wind"] = _card(
        "weather_wind", "wind speed", "m/s", "continuous", "weather", 2, "rooftop weather station", [0, 10], H(10), H(15),
        {"below": 0, "above": 44}, 0.4, 0.6, None, None,
        "calm at night, stronger and gusty in the afternoon; storms bring sudden gusts", "no daily rule",
        WEATHER_CAUSES, ["stuck", "noise", "quantised"], ("weather", "wind"), short="wind",
        rules={"recur_cause": "gusty_wind", "normal_cause": "normal_weather", "zero_ok": True})
    C["occupancy"] = _card(
        "occupancy", "room occupancy", "0/1", "binary_state", "occupancy", 0, "room presence sensor", None, None, None,
        None, None, None, None, None,
        "1 = people present; classes and office hours on workdays",
        "presence 22:00-06:00 = off-hours warning; more than 3 state changes per hour = flapping sensor",
        OCC_CAUSES, ["noise"], ("occupancy", "occ"), short="occupancy", line_hint="class hours on workdays",
        rules={"normal_cause": "normal_occupancy"})
    C["hvac_unit"] = _card(
        "hvac_unit", "AC unit room temperature with run state and setpoint", "C", "hvac_unit", "hvac", 1,
        "indoor AC unit", None, None, None, {"below": 10, "above": 45}, 0.1, 0.3, 2.0, None,
        ("comfort band setpoint -3/+2 C; warning above 30, critical above 34; pull-down 1-3 C/h after start; "
         "4+ starts per 4 h with runs of 15 min or less = short cycling"),
        "office units run on workdays 09:00-18:00; off at night and on Sundays",
        ["normal_operation", "scheduled_off", "high_heat_load", "ac_not_cooling", "overcooling", "ac_off_heat_gain",
         "short_cycling_control", "schedule_or_control_fault", "unit_not_starting", "unoccupied_running", "unit_alarm",
         "sensor_fault"], allf, ("hvac", "room_temp"), short="AC room temp", line_hint="follows its AC unit",
        rules={"cause_action": {"normal_operation": "none", "scheduled_off": "none", "high_heat_load": "monitor",
                                "ac_not_cooling": "inspect_hvac", "overcooling": "review_schedule",
                                "ac_off_heat_gain": "review_schedule", "short_cycling_control": "inspect_hvac",
                                "schedule_or_control_fault": "review_schedule", "unit_not_starting": "inspect_hvac",
                                "unoccupied_running": "switch_off_ac", "unit_alarm": "inspect_hvac",
                                "sensor_fault": "check_sensor"}, "normal_cause": "normal_operation"},
        actions=["none", "monitor", "inspect_hvac", "check_sensor", "review_schedule", "request_facility_review",
                 "switch_off_ac"])
    # hvac_unit limits for the policy/rate code (rendered through dynamics text; the HVAC teacher owns them)
    C["hvac_unit"]["warning"], C["hvac_unit"]["critical"] = H(30), H(34)
    for c in C.values():
        c["rules"]["synthetic"] = False
        c["rules"]["type"] = c["card_id"]
    return C


def metric_to_card(role, metric, node="", location=""):
    """today's (role, metric, node) -> card id (context variant from the node prefix / location)."""
    if role == "air_quality":
        if metric in ("pm25", "pm10"):
            out = node.startswith("AQ-") or "outdoor" in location
            return f"{metric}_{'outdoor' if out else 'indoor'}"
        return {"co2": "co2_indoor", "temp": "temp_indoor", "rh": "rh_indoor"}[metric]
    if role == "water":
        return {"level": "tank_level", "flow": "water_flow", "tds": "water_tds", "ph": "water_ph"}[metric]
    if role == "power":
        if metric == "pf":
            return "power_pf"
        return "power_solar" if node.startswith("SL-") else "power_load"
    if role == "weather":
        return f"weather_{metric}"
    if role == "occupancy":
        return "occupancy"
    if role == "hvac":
        return "hvac_unit"
    raise KeyError((role, metric))


# --------------------------------------------------------------------------------------------- synthetic cards
# Each prototype: quantity/unit/domain + value model for the simulator ("driver") + limit pattern. Values in
# lists are (lo, hi) ranges drawn per card. causes: generic names the cause rules map shapes to.
def P(**k):
    return k


TRAIN_TYPES = {
    "no2": P(q="nitrogen dioxide", short="NO2", unit="ppb", dom="air_quality", dec=0, ctx=["outdoor air station", "roadside station"],
             base=(15, 40), amp=(10, 30), noise=(1.5, 4), lim=("high", (80, 120), (160, 240)), imp=(0, 2000), step=(60, 120),
             driver="traffic", up="traffic_emission", down="normal_conditions", spike="traffic_emission", osc="normal_conditions",
             extra_causes=["ventilation_insufficient"], dyn="traffic peaks 08-10 and 18-21; low at night; wind disperses it",
             cyc="traffic peaks below the limits are normal"),
    "voc_index": P(q="VOC index", short="VOC", unit="index", dom="air_quality", dec=0, ctx=["indoor room", "lab room"],
                   base=(80, 120), amp=(20, 80), noise=(2, 5), lim=("high", (220, 280), (350, 420)), imp=(0, 500), step=(100, 150),
                   driver="occupancy_mass", up="occupancy_load", down="normal_conditions", spike="indoor_emission_source",
                   osc="normal_conditions", extra_causes=["ventilation_insufficient"],
                   dyn="100 = clean-air average; cleaning products, paint and crowds raise it; ventilation brings it back",
                   cyc="rises during occupied hours below the limits are normal"),
    "noise_db": P(q="sound level", short="noise", unit="dB", dom="environment", dec=1, ctx=["corridor", "lecture hall", "outdoor area"],
                  base=(38, 48), amp=(8, 18), noise=(0.8, 2.0), lim=("high", (68, 75), (82, 88)), imp=(20, 140), step=(25, 35),
                  driver="occupancy_linear", up="crowd_activity", down="normal_conditions", spike="loud_event",
                  osc="normal_conditions", extra_causes=["construction_work"],
                  dyn="quiet at night; rises with people and traffic; short bursts from doors and announcements",
                  cyc="busy-hour rises below the limits are normal"),
    "co": P(q="carbon monoxide", short="CO", unit="ppm", dom="air_quality", dec=1, ctx=["parking area", "kitchen", "generator room"],
            base=(0.5, 3), amp=(1, 4), noise=(0.2, 0.5), lim=("high", (9, 15), (30, 50)), imp=(0, 1000), step=(20, 40),
            driver="events_spiky", up="combustion_source", down="normal_conditions", spike="combustion_source",
            osc="normal_conditions", extra_causes=["ventilation_insufficient"],
            dyn="near zero in clean air; engines, burners and generators raise it; exhaust fans clear it in minutes",
            cyc="no daily rule"),
    "light_lux": P(q="illuminance", short="light", unit="lux", dom="environment", dec=0, ctx=["office", "lecture hall", "corridor"],
                   base=(250, 450), amp=(100, 300), noise=(5, 15), lim=None, rate=True, imp=(0, 100000), step=None,
                   driver="daylight", up="daylight_change", down="lights_switched_off", spike="daylight_change",
                   osc="normal_conditions", extra_causes=["lighting_fault"],
                   dyn="lights on in working hours; daylight adds a midday bulge; near zero at night",
                   cyc="a rise ending 06:00-12:00 and a fall ending 12:00-20:00 are the normal daylight day", solar=True),
    "chw_supply_temp": P(q="chilled-water supply temperature", short="CHW supply", unit="C", dom="hvac", dec=1,
                         ctx=["chiller plant", "plant room"], base=(6.5, 7.5), amp=(0.3, 1.0), noise=(0.05, 0.15),
                         lim=("high", (9, 10), (11.5, 13)), imp=(0, 30), step=(1.0, 2.0), driver="equipment_cycle",
                         up="chiller_capacity_shortfall", down="normal_operation", spike="chiller_capacity_shortfall",
                         osc="normal_operation", extra_causes=["chiller_trip"],
                         dyn="held near setpoint 7 C while the chiller runs; rises fast when the chiller trips",
                         cyc="small cycling around setpoint is normal"),
    "condenser_pressure": P(q="condenser refrigerant pressure", short="cond. pressure", unit="bar", dom="hvac", dec=2,
                            ctx=["chiller plant", "rooftop AC unit"], base=(12, 15), amp=(1, 3), noise=(0.05, 0.2),
                            lim=("high", (17, 19), (21, 23)), imp=(0, 40), step=(2, 4), driver="weather_follow",
                            up="high_ambient_load", down="normal_operation", spike="fan_or_coil_issue", osc="normal_operation",
                            extra_causes=["fan_or_coil_issue"],
                            dyn="follows outdoor temperature and load; dirty coils or a failed fan push it up",
                            cyc="rises with afternoon heat below the limits are normal"),
    "battery_soc": P(q="battery state of charge", short="SoC", unit="%", dom="power", dec=1, ctx=["UPS battery bank", "solar battery bank"],
                     base=(90, 100), amp=(5, 20), noise=(0.1, 0.3), lim=("low", (30, 40), (15, 20)), imp=(0, 100), step=(5, 10),
                     driver="consumption", up="charging", down="discharging_on_outage", spike="sensor_fault",
                     osc="normal_operation", extra_causes=["battery_degradation"],
                     dyn="stays near full on mains; falls while supplying an outage; recharges after",
                     cyc="charging back toward full is normal"),
    "ups_load": P(q="UPS load", short="UPS load", unit="%", dom="power", dec=1, ctx=["server room UPS", "lab UPS"],
                  base=(30, 50), amp=(5, 20), noise=(0.3, 1.0), lim=("high", (75, 85), (92, 98)), imp=(0, 150), step=(30, 50),
                  driver="occupancy_linear", up="load_growth", down="normal_operation", spike="load_surge", osc="normal_operation",
                  extra_causes=["load_surge"], dyn="follows connected equipment; rises in working hours",
                  cyc="working-hour rises below the limits are normal"),
    "generator_fuel": P(q="generator fuel level", short="fuel", unit="%", dom="power", dec=1, ctx=["diesel generator"],
                        base=(60, 95), amp=(2, 10), noise=(0.1, 0.4), lim=("low", (25, 35), (10, 15)), imp=(0, 100), step=(4, 8),
                        driver="consumption", up="refuelling", down="generator_running", spike="sensor_fault",
                        osc="normal_operation", extra_causes=["fuel_leak"],
                        dyn="flat while the generator is idle; falls 2-6 %/h while it runs; jumps up when refuelled",
                        cyc="no daily rule"),
    "borewell_depth": P(q="borewell water depth below ground", short="borewell depth", unit="m", dom="water", dec=1,
                        ctx=["borewell"], base=(25, 45), amp=(2, 8), noise=(0.05, 0.2), lim=("high", (55, 65), (70, 80)),
                        imp=(0, 300), step=(3, 6), driver="drawdown", up="pumping_drawdown", down="recovery",
                        spike="sensor_fault", osc="pump_cycling", extra_causes=["aquifer_depletion"],
                        dyn="deepens while the borewell pump runs, recovers when it stops; deeper in summer",
                        cyc="drawdown and recovery with pump runs are normal"),
    "turbidity": P(q="water turbidity", short="turbidity", unit="NTU", dom="water", dec=2, ctx=["water supply", "treatment outlet"],
                   base=(0.2, 0.6), amp=(0.1, 0.4), noise=(0.02, 0.06), lim=("high", (1, 1.5), (4, 6)), imp=(0, 4000),
                   step=(1.0, 2.0), driver="rain_events", up="source_contamination", down="normal_usage",
                   spike="pipe_disturbance", osc="normal_usage", extra_causes=["filter_breakthrough"],
                   dyn="low and flat; rises after heavy rain or pipe work", cyc="no daily rule"),
    "chlorine_residual": P(q="free chlorine residual", short="chlorine", unit="mg/L", dom="water", dec=2, ctx=["water supply"],
                           base=(0.4, 0.8), amp=(0.05, 0.2), noise=(0.01, 0.03), lim=("both", (0.2, 2.0), (0.1, 4.0)),
                           imp=(0, 20), step=(0.3, 0.6), driver="slow_walk", up="overdosing", down="dosing_failure",
                           spike="dosing_pulse", osc="normal_usage", extra_causes=["stagnation"],
                           dyn="decays slowly in storage; dosing pumps lift it in steps", cyc="no daily rule"),
    "soil_moisture": P(q="soil moisture", short="soil moisture", unit="%", dom="environment", dec=1, ctx=["lawn", "garden bed"],
                       base=(28, 40), amp=(3, 8), noise=(0.1, 0.4), lim=("low", (18, 22), (8, 12)), imp=(0, 100), step=(10, 20),
                       driver="irrigation", up="irrigation", down="drying", spike="sensor_fault", osc="normal_conditions",
                       extra_causes=["irrigation_failure"],
                       dyn="jumps up when irrigated or after rain, dries slowly, faster on hot afternoons",
                       cyc="irrigation rises are normal"),
    "door_open": P(q="door open state", short="door", unit="0/1", dom="building", dec=0, ctx=["lab door", "server room door"],
                   kind="binary_state", driver="binary",
                   dyn="1 = door open (evidence lines call state 1 'occupied'); opened briefly when people pass",
                   cyc="open 22:00-06:00 = off-hours warning; more than 3 changes per hour = flapping sensor"),
    "people_count": P(q="people count", short="people", unit="persons", dom="occupancy", dec=0, kind="count",
                      ctx=["lecture hall", "library hall", "canteen"], base=(0, 3), amp=(30, 120), noise=(0.5, 2),
                      lim="capacity", imp=(0, 2000), step=None, driver="occupancy_count", up="arrival", down="departure",
                      spike="crowd_event", osc="normal_occupancy", extra_causes=["overcrowding"],
                      dyn="follows the timetable: fills at class start, empties after", cyc="class hours on workdays"),
    "lift_trips": P(q="lift trips per 5 min", short="lift trips", unit="trips", dom="building", dec=0, kind="count",
                    ctx=["lift", "service lift"], base=(0, 1), amp=(4, 12), noise=(0.5, 1.5), lim=None, rate=True,
                    imp=(0, 100), step=None, driver="occupancy_count", up="peak_traffic", down="normal_operation",
                    spike="peak_traffic", osc="normal_operation", extra_causes=["lift_out_of_service"],
                    dyn="busy at class changes and lunch; near zero at night", cyc="class-change bursts are normal", zero_ok=True),
    "server_temp": P(q="server room temperature", short="server temp", unit="C", dom="hvac", dec=1, ctx=["server room", "network room"],
                     base=(20, 23), amp=(0.3, 1.0), noise=(0.05, 0.15), lim=("high", (26, 28), (31, 33)), imp=(0, 60),
                     step=(1.5, 3.0), driver="equipment_cycle", up="cooling_failure", down="normal_operation",
                     spike="cooling_failure", osc="normal_operation", extra_causes=["it_load_growth"],
                     dyn="held steady by precision AC; rises 2-6 C/h when cooling fails", cyc="small AC cycling is normal"),
    "kitchen_gas": P(q="kitchen gas concentration", short="gas", unit="ppm", dom="safety", dec=0, ctx=["canteen kitchen", "hostel kitchen"],
                     base=(0, 20), amp=(20, 80), noise=(2, 6), lim=("high", (300, 500), (800, 1200)), imp=(0, 10000),
                     step=(400, 800), driver="events_spiky", up="gas_leak", down="normal_conditions", spike="cooking_burst",
                     osc="normal_conditions", extra_causes=["ventilation_insufficient"],
                     dyn="near zero; short bursts while burners light; a sustained rise means a leak", cyc="cooking hours 06-10, 11-14, 18-21"),
    "fume_hood_velocity": P(q="fume-hood face velocity", short="face velocity", unit="m/s", dom="safety", dec=2,
                            ctx=["chemistry lab fume hood"], base=(0.45, 0.55), amp=(0.02, 0.06), noise=(0.005, 0.015),
                            lim=("low", (0.38, 0.42), (0.28, 0.32)), imp=(0, 5), step=(0.1, 0.2), driver="slow_walk",
                            up="sash_lowered", down="exhaust_fan_issue", spike="door_draught", osc="normal_conditions",
                            extra_causes=["sash_opened_too_wide"],
                            dyn="held near 0.5 m/s by the exhaust fan; drops when the fan weakens or the sash is opened wide",
                            cyc="no daily rule"),
    "solar_pv": P(q="solar PV output", short="PV", unit="kW", dom="power", dec=2, ctx=["rooftop solar array", "carport solar array"],
                  base=(0, 0), amp=(5, 80), noise=(0.05, 0.3), lim=None, rate=True, imp=(0, 5000), step=None, driver="solar",
                  up="normal_generation", down="cloud_cover", spike="normal_generation", osc="cloud_cover",
                  extra_causes=["inverter_trip"], dyn="zero at night, bell-shaped by day; clouds cut it in steps",
                  cyc="a rise ending 06:00-12:00 and a fall ending 12:00-19:00 are the normal solar day", solar=True, zero_ok=True),
    "ev_charger": P(q="EV charger power", short="EV charger", unit="kW", dom="power", dec=2, ctx=["EV charging bay"],
                    base=(0, 0.2), amp=(3, 22), noise=(0.02, 0.1), lim=None, rate=True, imp=(0, 500), step=None,
                    driver="sessions", up="charging_session", down="session_end", spike="charging_session",
                    osc="normal_operation", extra_causes=["charger_fault"],
                    dyn="0 when idle; a session is a step up held 1-4 h, then a step down", cyc="sessions any time are normal",
                    zero_ok=True),
    "water_meter": P(q="water use per 5 min", short="water use", unit="L", dom="water", dec=0, kind="count",
                     ctx=["building water meter", "hostel water meter"], base=(5, 30), amp=(80, 300), noise=(3, 10),
                     lim=None, rate=True, imp=(0, 100000), step=None, driver="occupancy_linear", up="high_demand",
                     down="normal_usage", spike="high_demand", osc="normal_usage", extra_causes=["possible_leak"],
                     dyn="follows people: morning and evening peaks in hostels, working hours in offices; low at night",
                     cyc="daily peaks are normal; steady use at night means a leak", zero_ok=True),
    "line_pressure": P(q="water line pressure", short="pressure", unit="bar", dom="water", dec=2, ctx=["supply main", "building riser"],
                       base=(2.5, 3.5), amp=(0.2, 0.6), noise=(0.02, 0.06), lim=("both", (1.5, 5.5), (1.0, 7.0)), imp=(0, 25),
                       step=(1.0, 2.0), driver="demand_inverse", up="pressure_surge", down="supply_interruption",
                       spike="water_hammer", osc="pump_cycling", extra_causes=["pipe_burst"],
                       dyn="dips at peak demand, recovers at night; a burst or pump trip drops it fast",
                       cyc="small demand dips below the limits are normal"),
}

TEST_TYPES = {
    "so2": P(q="sulphur dioxide", short="SO2", unit="ppb", dom="air_quality", dec=0, ctx=["outdoor air station"],
             base=(3, 12), amp=(3, 10), noise=(0.5, 1.5), lim=("high", (60, 80), (140, 180)), imp=(0, 2000), step=(40, 80),
             driver="traffic", up="combustion_emission", down="normal_conditions", spike="combustion_emission",
             osc="normal_conditions", extra_causes=["industrial_plume"],
             dyn="low background; diesel generators and plumes raise it", cyc="no daily rule"),
    "formaldehyde": P(q="formaldehyde", short="HCHO", unit="ppb", dom="air_quality", dec=0, ctx=["lab room", "new office"],
                      base=(10, 30), amp=(5, 20), noise=(1, 3), lim=("high", (80, 100), (150, 200)), imp=(0, 5000),
                      step=(40, 80), driver="occupancy_mass", up="material_offgassing", down="normal_conditions",
                      spike="indoor_emission_source", osc="normal_conditions", extra_causes=["ventilation_insufficient"],
                      dyn="off-gasses from furniture and chemicals; builds up when ventilation is off", cyc="no daily rule"),
    "vibration": P(q="vibration velocity", short="vibration", unit="mm/s", dom="equipment", dec=2, ctx=["pump motor", "AHU fan"],
                   base=(1.0, 2.0), amp=(0.2, 0.6), noise=(0.05, 0.15), lim=("high", (4.5, 5.0), (7.1, 8.0)), imp=(0, 100),
                   step=(2.0, 3.0), driver="equipment_cycle", up="bearing_wear", down="normal_operation",
                   spike="mechanical_impact", osc="normal_operation", extra_causes=["misalignment"],
                   dyn="steady while the machine runs, near zero when stopped; wear raises it slowly", cyc="no daily rule"),
    "transformer_oil_temp": P(q="transformer oil temperature", short="oil temp", unit="C", dom="power", dec=1,
                              ctx=["distribution transformer"], base=(45, 60), amp=(5, 12), noise=(0.1, 0.3),
                              lim=("high", (80, 85), (92, 98)), imp=(-10, 150), step=(2, 4), driver="weather_follow",
                              up="overload_heating", down="normal_operation", spike="sensor_fault", osc="normal_operation",
                              extra_causes=["cooling_fan_failure"],
                              dyn="follows load and outdoor heat with a 1-2 h lag", cyc="afternoon rises below the limits are normal"),
    "chiller_delta_t": P(q="chiller water temperature difference", short="chiller dT", unit="C", dom="hvac", dec=1,
                         ctx=["chiller plant"], base=(4.5, 5.5), amp=(0.3, 0.8), noise=(0.05, 0.15),
                         lim=("low", (3.0, 3.5), (1.5, 2.0)), imp=(-5, 20), step=(1.0, 2.0), driver="equipment_cycle",
                         up="normal_operation", down="low_delta_t_syndrome", spike="sensor_fault", osc="normal_operation",
                         extra_causes=["bypass_valve_open"],
                         dyn="near 5 C at design load; falls when water bypasses coils", cyc="no daily rule"),
    "cooling_tower_level": P(q="cooling-tower basin level", short="basin level", unit="%", dom="water", dec=1,
                             ctx=["cooling tower basin"], base=(60, 80), amp=(3, 10), noise=(0.2, 0.6),
                             lim=("low", (35, 40), (15, 20)), imp=(0, 100), step=(5, 10), driver="drawdown",
                             up="makeup_fill", down="evaporation_loss", spike="sensor_fault", osc="pump_cycling",
                             extra_causes=["makeup_valve_stuck"],
                             dyn="falls with evaporation, refilled by a float valve", cyc="refill cycles are normal"),
    "lpg_pressure": P(q="LPG manifold pressure", short="LPG pressure", unit="bar", dom="safety", dec=2, ctx=["canteen gas bank"],
                      base=(1.8, 2.4), amp=(0.1, 0.3), noise=(0.01, 0.04), lim=("both", (1.2, 3.0), (0.8, 3.6)),
                      imp=(0, 20), step=(0.5, 1.0), driver="demand_inverse", up="regulator_fault", down="cylinder_empty",
                      spike="regulator_fault", osc="normal_operation", extra_causes=["gas_leak"],
                      dyn="dips while burners draw gas; drops steadily as cylinders empty", cyc="cooking-hour dips are normal"),
    "cold_room_temp": P(q="cold-room temperature", short="cold room", unit="C", dom="environment", dec=1,
                        ctx=["canteen cold room", "lab cold room"], base=(2, 4), amp=(0.5, 1.5), noise=(0.05, 0.2),
                        lim=("both", (0.5, 6), (-1.5, 8)), imp=(-40, 60), step=(1.5, 3.0), driver="equipment_cycle",
                        up="door_left_open", down="thermostat_fault", spike="door_opening", osc="normal_operation",
                        extra_causes=["compressor_failure"],
                        dyn="compressor cycles keep it at 2-4 C; door openings give short bumps", cyc="defrost and door bumps are normal"),
}


def _r(rng, lohi, dec=None):
    v = rng.uniform(*lohi)
    return v


def _round_lim(v, dec):
    d = max(dec, 0)
    if abs(v) >= 100:
        return float(round(v / 5) * 5)
    if abs(v) >= 10:
        return float(round(v))
    return round(v, max(1, d))


def synthetic_card(type_name, rng, place_ctx=None, capacity=None, jitter=True):
    """One random card of a synthetic type. capacity: room capacity for 'capacity' limits (people_count)."""
    pr = TRAIN_TYPES.get(type_name) or TEST_TYPES[type_name]
    kind = pr.get("kind", "continuous")
    dec = pr.get("dec", 1)
    ctx = place_ctx or rng.choice(pr["ctx"])
    uid = f"{type_name}_{rng.randrange(16 ** 6):06x}"
    causes_base = [pr.get("normal_cause") or "normal_conditions"]
    if kind == "binary_state":
        c = _card(uid, pr["q"], pr["unit"], kind, pr["dom"], 0, ctx, None, None, None, None, None, None, None, None,
                  pr["dyn"], pr["cyc"], OCC_CAUSES, ["noise"], None, short=pr["short"],
                  rules={"normal_cause": "normal_occupancy", "driver": "binary"})
        c["rules"].update(synthetic=True, type=type_name, legacy_key=["occupancy", "occ"])
        return c
    causes = []
    for k in ("down", "up", "spike", "osc"):
        v = pr[k]
        if v not in causes and v != "sensor_fault":
            causes.append(v)
    for v in pr.get("extra_causes", []):
        if v not in causes:
            causes.append(v)
    normal = pr["down"] if pr["down"] in ("normal_conditions", "normal_operation", "normal_usage") else "normal_conditions"
    if normal not in causes:
        causes.insert(0, normal)
    else:
        causes.remove(normal)
        causes.insert(0, normal)
    causes.append("sensor_fault")
    base = rng.uniform(*pr["base"]) if pr["base"][1] > pr["base"][0] else pr["base"][0]
    noise = rng.uniform(*pr["noise"])
    noise_r = float(f"{noise:.2g}")
    warn = crit = None
    normal_rng = None
    rate = None
    lim = pr.get("lim")
    if lim == "capacity":
        cap = capacity or rng.choice((40, 60, 80, 120, 180, 240))
        w, cr = float(round(cap * rng.uniform(0.9, 1.0))), float(round(cap * rng.uniform(1.1, 1.25)))
        warn, crit = H(w), H(cr)
        normal_rng = [0, w]
    elif lim:
        d, wr, cr = lim
        if d == "both":
            lo_w, hi_w = wr
            lo_c, hi_c = cr
            f = (lambda v: v * rng.uniform(0.9, 1.1)) if jitter else (lambda v: v)
            lw, hw, lc, hc = (_round_lim(f(lo_w), dec), _round_lim(f(hi_w), dec), _round_lim(f(lo_c), dec), _round_lim(f(hi_c), dec))
            if not lc < lw < hw < hc:
                lw, hw, lc, hc = lo_w, hi_w, lo_c, hi_c
            warn = {"dir": "both", "low": lw, "high": hw}
            crit = {"dir": "both", "low": lc, "high": hc}
            normal_rng = [lw, hw]
        else:
            w = _round_lim(rng.uniform(*wr), dec)
            c_ = _round_lim(rng.uniform(*cr), dec)
            if (d == "high" and c_ <= w) or (d == "low" and c_ >= w):
                c_ = _round_lim(w * (1.5 if d == "high" else 0.5), dec)
            warn, crit = {"dir": d, "at": w}, {"dir": d, "at": c_}
            if d == "high":
                normal_rng = [_round_lim(max(pr["imp"][0], base - 4 * pr["amp"][1]), dec) if pr["imp"][0] < base else pr["imp"][0], w]
                normal_rng[0] = min(normal_rng[0], _round_lim(base * 0.5, dec))
                normal_rng[0] = max(normal_rng[0], pr["imp"][0])
            else:
                normal_rng = [w, _round_lim(max(base + 3 * pr["amp"][1], w * 1.5), dec)]
                normal_rng[1] = min(normal_rng[1], pr["imp"][1])
    if pr.get("rate") or lim is None:
        rate = dict(DEFAULT_RATE)
        if rng.random() < 0.5:
            rate["abrupt_crit"] = round(rng.choice((0.8, 1.0, 1.2, 1.5, 2.0, 2.5)), 2)
            rate["gradual_warn"] = rng.choice((0.2, 0.3, 0.4, 0.5))
            if rng.random() < 0.3:
                rate["abrupt_warn"] = rng.choice((0.25, 0.4, 0.5))
        rate["osc"] = "warning" if pr["dom"] == "water" and rng.random() < 0.5 else "normal"
    imp_lo, imp_hi = pr["imp"]
    step = None
    if pr.get("step"):
        step = float(f"{rng.uniform(*pr['step']):.2g}")
    floor = float(f"{max(noise * 3, 10 ** (-dec)):.2g}") if dec >= 0 else noise * 3
    routines = []
    if pr.get("solar"):
        routines.append({"type": "solar", "rise": [6, 12], "fall": [12, 19 if pr["driver"] == "solar" else 20],
                         "cause": pr["up"] if pr["driver"] == "solar" else "normal_conditions"})
    elif "below the limits are normal" in pr.get("cyc", "") or "are normal" in pr.get("cyc", ""):
        pats = {"traffic": ["gradual_increase", "gradual_decrease", "oscillation"],
                "occupancy_mass": ["gradual_increase", "step_increase", "gradual_decrease"],
                "occupancy_linear": ["gradual_increase", "step_increase", "step_decrease", "gradual_decrease"],
                "occupancy_count": ["step_increase", "step_decrease", "gradual_increase", "gradual_decrease"],
                "weather_follow": ["gradual_increase", "gradual_decrease"],
                "equipment_cycle": ["oscillation"], "drawdown": ["gradual_increase", "gradual_decrease", "oscillation"],
                "consumption": ["gradual_increase", "step_increase"], "irrigation": ["step_increase", "gradual_decrease"],
                "demand_inverse": ["gradual_decrease", "gradual_increase", "oscillation"],
                "sessions": ["step_increase", "step_decrease"]}.get(pr["driver"], [])
        if pats:
            routines.append({"type": "pattern_normal", "patterns": pats, "cause": normal, "below_only": True})
    cause_action = {}
    for cz in causes:
        if cz == "sensor_fault":
            cause_action[cz] = "check_sensor"
        elif cz == normal or cz.startswith("normal") or cz in ("recovery", "charging", "drying", "irrigation", "makeup_fill"):
            cause_action[cz] = "none"
        else:
            cause_action[cz] = {"air_quality": "inspect_ventilation", "water": "inspect_water_system", "power": "inspect_electrical",
                                "hvac": "inspect_hvac", "safety": "request_facility_review", "environment": "monitor",
                                "building": "request_facility_review", "equipment": "request_facility_review",
                                "occupancy": "review_schedule"}[pr["dom"]]
    for cz in (pr["up"], pr["spike"]):
        if cz in ("arrival", "peak_traffic", "normal_generation", "charging_session", "daylight_change", "crowd_activity"):
            cause_action[cz] = "none"
    acts = sorted(set(cause_action.values()) | {"none", "monitor", "check_sensor", "request_facility_review"}, key=lambda a: (BASE_ACTIONS + ("switch_off_ac",)).index(a))
    c = _card(uid, pr["q"], pr["unit"], kind, pr["dom"], dec, ctx, normal_rng, warn, crit,
              {"below": imp_lo, "above": imp_hi}, noise_r, floor, step, rate, pr["dyn"], pr["cyc"], causes,
              ["stuck", "bias", "noise", "dropout", "quantised"] + (["drift"] if pr["driver"] in ("slow_walk", "occupancy_mass") else []),
              None, short=pr["short"], actions=acts,
              rules={"cause_action": cause_action, "normal_cause": normal, "recur_cause": normal,
                     "erratic_fault": True, "zero_ok": bool(pr.get("zero_ok")) or imp_lo >= 0 and base < 1,
                     "drift_fault": pr["driver"] in ("slow_walk", "occupancy_mass"), "routines": routines,
                     "cause_map": {"up": pr["up"], "down": pr["down"], "spike": pr["spike"], "osc": pr["osc"]},
                     "driver": pr["driver"], "base": base, "amp": list(pr["amp"]), "sensor_range": [imp_lo, imp_hi]})
    c["rules"].update(synthetic=True, type=type_name, legacy_key=None)
    if c["impossible"]["below"] is not None and c["normal"] and c["impossible"]["below"] > c["normal"][0]:
        c["normal"][0] = c["impossible"]["below"]
    return c


def jitter_card(card, rng, frac=0.15):
    """Copy of an existing card with limits moved by up to +-frac (rate rules too). The E-line key stays."""
    c = copy.deepcopy(card)
    dec = c["decimals"]
    f = lambda v: _round_lim(v * (1 + rng.uniform(-frac, frac)), max(dec, 1))  # noqa: E731
    if c["warning"] and c["kind"] == "continuous":
        w, cr = c["warning"], c["critical"]
        for _ in range(10):
            if w["dir"] == "both":
                nw = {"dir": "both", "low": f(w["low"]), "high": f(w["high"])}
                nc = {"dir": "both", "low": f(cr["low"]), "high": f(cr["high"])}
                ok = nc["low"] < nw["low"] < nw["high"] < nc["high"]
            else:
                nw, nc = {"dir": w["dir"], "at": f(w["at"])}, {"dir": cr["dir"], "at": f(cr["at"])}
                ok = (nc["at"] > nw["at"]) if w["dir"] == "high" else (nc["at"] < nw["at"])
            if ok:
                c["warning"], c["critical"] = nw, nc
                break
        if c["normal"]:
            if c["warning"]["dir"] == "high":
                c["normal"] = [c["normal"][0], c["warning"]["at"]]
            elif c["warning"]["dir"] == "low":
                c["normal"] = [c["warning"]["at"], c["normal"][1]]
            else:
                c["normal"] = [c["warning"]["low"], c["warning"]["high"]]
    if c["rate_rules"]:
        rr = dict(c["rate_rules"])
        rr["abrupt_crit"] = round(rng.choice((0.8, 1.0, 1.2, 2.0, 2.5)), 2)
        rr["gradual_warn"] = rng.choice((0.2, 0.25, 0.4, 0.5))
        if rng.random() < 0.3:
            rr["abrupt_warn"] = rng.choice((0.25, 0.4, 0.5))
        c["rate_rules"] = rr
    c["rules"]["jittered"] = True
    return c


if __name__ == "__main__":
    rng = random.Random(1)
    EC = existing_cards()
    for k, c in EC.items():
        assert not validate_card(c), (k, validate_card(c))
    for t in list(TRAIN_TYPES) + list(TEST_TYPES):
        for _ in range(50):
            c = synthetic_card(t, rng)
            assert not validate_card(c), (t, validate_card(c), c)
    print(len(EC), "existing cards ok;", len(TRAIN_TYPES), "train types;", len(TEST_TYPES), "test types")
    print(render_full(EC["co2_indoor"], "lecture hall, capacity 120"))
    print(render_line(EC["co2_indoor"]))
    print(render_full(EC["power_load"]))
    print(render_full(synthetic_card("chlorine_residual", rng)))
    print(render_full(synthetic_card("ev_charger", rng)))
