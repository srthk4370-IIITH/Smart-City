"""Track B: deterministic post-checks on stored v2 agent outputs (no model calls).

Loads (eval row, stored v2 sample) pairs, applies post-rules that use only what the backend has at
checkAgent time (the prompt text and the raw window s.Xs), and rescores with the official scorer
(training/v2/post/common_v2.score_one), so before/after numbers are exactly comparable with host_eval3e.
Run with ~/venvs/train/bin/python in WSL.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path("/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent")
for p in (REPO / "training", REPO / "training/v2", REPO / "training/v2/post"):
    sys.path.insert(0, str(p))
import common_v2 as C  # noqa: E402
import features as F  # noqa: E402
import generate_dataset as G  # noqa: E402
import teacher_v2 as TE  # noqa: E402

RUNS = Path.home() / "smartcity_runs"
SETS = {
    "dev": RUNS / "agents_v2_topup3f/eval_dev",
    "rw5dev": RUNS / "agents_v2_topup3f/eval_rw5dev",
    "test": RUNS / "agents_v2_topup3f/eval_test",
    "rw5test": RUNS / "agents_v2_topup3f/eval_rw5test",
}
NORMAL_CAUSE = dict(TE.NORMAL_CAUSE)


def load(name, tag="v2cuda"):
    d = SETS[name]
    rows = {r["id"]: r for r in C.read_jsonl(d / "eval3e.jsonl")}
    out, seen = [], set()
    for s in C.read_jsonl(d / "eval" / tag / "samples.jsonl"):
        if s["id"] in seen or s["id"] not in rows:
            continue
        seen.add(s["id"])
        out.append((rows[s["id"]], s))
    return out


# ------------------------------------------------------------------ prompt context
RX_LIM = re.compile(r"^LIMITS: .*?warning (above|below) ([-\d.]+), critical (above|below) ([-\d.]+)", re.M)
RX_TANK = re.compile(r"^TANK: high level above ([-\d.]+), overflow risk above ([-\d.]+); usual fill up to (\d+) min", re.M)


class Ctx:
    def __init__(self, row):
        self.row = row
        self.role = row["role"]
        self.metric = row.get("metric")
        self.node = row.get("node", "")
        self.n = row.get("n") or 48
        self.end = row["end_epoch"]
        self.prompt = row["prompt"]
        h = row.get("hist") or []
        self.xs = [float(v) for v in h[-self.n:]] if len(h) >= self.n else None
        self.m = F.METRICS.get((self.role, self.metric)) if self.metric else None
        self.st = F.compute_stats(self.xs, self.m["dec"]) if (self.xs and self.m) else None
        lm = RX_LIM.search(self.prompt)
        self.lim = (lm.group(1), float(lm.group(2)), float(lm.group(4))) if lm else None
        tk = RX_TANK.search(self.prompt)
        self.tank = {"high": float(tk.group(1)), "overflow": float(tk.group(2)), "fill_min": int(tk.group(3))} if tk else None

    @property
    def base(self):
        return sum(self.xs[:12]) / 12 if self.xs else None   # = rules.go RuleFinding baseMean: mean(xs[:12])


# ------------------------------------------------------------------ the post-rules
# each: rule(ctx, p) -> list of (field, new value) or [] ; p = the parsed answer dict (normalised enums)
LIMIT_ROLES = ("air_quality", "weather", "power", "water")   # metrics with a LIMITS line; hvac/occupancy excluded


def status_go(role, metric, pattern, st, base):
    """= app/backend/rules.go StatusOf (the teacher's status_of plus its CO2 < 350 ppm sensor_fault line)."""
    if pattern != "flatline" and role == "air_quality" and metric == "co2" and st["last"] < 350:
        return "sensor_fault"
    return G.status_of(role, metric, pattern, st, base)


def r_limit(c, p):
    """status from the value vs the warning/critical limits, for limit-defined metrics (rules.go StatusOf, limit branch),
    with the MODEL's pattern; never overrides sensor_fault, flatline or erratic."""
    if c.role not in LIMIT_ROLES or not c.lim or c.st is None or c.m is None or c.m.get("warn") is None:
        return []
    if p["status"] not in ("normal", "warning", "critical") or p["pattern"] in ("flatline", "erratic"):
        return []
    s = status_go(c.role, c.metric, p["pattern"], c.st, c.base)
    return [("status", s)] if s != p["status"] and s in ("normal", "warning", "critical") else []


def r_quality_cause(c, p):
    """water pH / TDS beyond a limit (status warning/critical, pattern not stable) -> water_quality_issue (the teacher's
    cause_of for these metrics; the board's off-label 'acidic_condition' meant the same)."""
    if c.role != "water" or c.metric not in ("ph", "tds") or p["status"] not in ("warning", "critical"):
        return []
    if p["pattern"] == "stable" or p["likely_cause"] == "water_quality_issue":
        return []
    return [("likely_cause", "water_quality_issue")]


def _rel_status(c, p):
    s = status_go(c.role, c.metric, p["pattern"], c.st, c.base)
    r = TE.routine_rule(c.role, c.metric, c.node, p["pattern"], s, c.st, c.end, c.n)
    return (r[0], r[1]) if r else (s, None)


def _tank_patch(c):
    if c.tank and c.node and c.node not in TE.V.NODE_LIMITS:
        TE.V.NODE_LIMITS[c.node] = c.tank


def r_rel_power(c, p):
    """power_kw (no fixed limits): rules.go StatusOf relative branch (range / first-hour mean) + the v2 power routines."""
    if c.role != "power" or c.metric != "power_kw" or c.st is None:
        return []
    if p["status"] not in ("normal", "warning", "critical") or p["pattern"] == "flatline":
        return []
    s, _ = _rel_status(c, p)
    return [("status", s)] if s != p["status"] and s in ("normal", "warning", "critical") else []


def r_rel_water(c, p):
    """water flow/level (no fixed limits): relative branch + TANK routines (overflow, filling, leak, pump cycling)."""
    if c.role != "water" or c.metric not in ("flow", "level") or c.st is None:
        return []
    if p["status"] not in ("normal", "warning", "critical") or p["pattern"] == "flatline":
        return []
    _tank_patch(c)
    s, _ = _rel_status(c, p)
    return [("status", s)] if s != p["status"] and s in ("normal", "warning", "critical") else []


def r_water_cause(c, p):
    """water level/flow: cause from the TANK routine for the model's pattern (filling / draining / leak / overflow /
    pump cycling); only when the routine applies, else unchanged."""
    if c.role != "water" or c.metric not in ("flow", "level") or c.st is None or p["status"] == "sensor_fault":
        return []
    _tank_patch(c)
    s = status_go(c.role, c.metric, p["pattern"], c.st, c.base)
    r = TE.routine_rule(c.role, c.metric, c.node, p["pattern"], s, c.st, c.end, c.n)
    if not r:
        return []
    out = []
    if r[1] != p["likely_cause"]:
        out.append(("likely_cause", r[1]))
    return out


CO2_FLOOR = 300.0


def r_floor(c, p, floor=CO2_FLOOR):
    """indoor CO2 whose latest reading is below the physical floor -> sensor_fault (REALWORLD 5.6)."""
    if c.role != "air_quality" or c.metric != "co2" or c.st is None or c.st["last"] >= floor:
        return []
    fk = "stuck" if p["pattern"] == "flatline" else "bias"
    out = [] if p["status"] == "sensor_fault" else [("status", "sensor_fault")]
    if p["likely_cause"] != "sensor_fault":
        out.append(("likely_cause", "sensor_fault"))
    if p["status"] != "sensor_fault" or (p.get("fault_kind") or "") not in C.enums()["fault_kinds"]:
        out.append(("fault_kind", fk))   # a valid kind the model already gave with sensor_fault is kept
    return out


def r_erratic(c, p):
    """the model's own pattern implies a fault (v1 teacher rule): erratic outside power -> sensor_fault/noise;
    non-zero flatline -> sensor_fault/stuck."""
    if c.st is None:
        return []
    if p["pattern"] == "erratic" and c.role not in ("power", "occupancy", "hvac"):
        fk = "noise"
    elif p["pattern"] == "flatline" and abs(c.st["last"]) > 1e-6 and c.role not in ("occupancy", "hvac"):
        fk = "stuck"
    else:
        return []
    out = [] if p["status"] == "sensor_fault" else [("status", "sensor_fault")]
    if p["likely_cause"] != "sensor_fault":
        out.append(("likely_cause", "sensor_fault"))
    if not p.get("fault_kind"):
        out.append(("fault_kind", fk))
    return out


# ---- glitch (port of dataquality.go glitchFree + Metrics floor)
GLITCH_SIGMA = 8.0
GLITCH_METRICS = {("air_quality", "co2"), ("air_quality", "temp"), ("air_quality", "rh"), ("water", "tds"),
                  ("water", "ph"), ("water", "level"), ("weather", "temp"), ("weather", "rh"), ("hvac", "room_temp")}


# where each glitch kind is non-physical (REALWORLD 5.2 / gen_rw5 ZERO_OK, RAIL_OK): a 0 reading, a reading at the
# range rail, or a one-reading excursion that returns. RH 100 % (fog/rain) is physical, so RH has no rail entry; tank
# level single-reading jumps are v2 events (relative status), so level is rail-only.
GLITCH_ZERO = {("air_quality", "co2"), ("air_quality", "temp"), ("air_quality", "rh"), ("water", "ph"), ("water", "tds")}
GLITCH_RAIL = {("air_quality", "co2"), ("air_quality", "temp"), ("water", "tds"), ("water", "ph"), ("water", "level")}
GLITCH_VALUE = {("air_quality", "co2"), ("air_quality", "temp"), ("air_quality", "rh"), ("water", "tds"), ("water", "ph")}


def glitch_at(c, sigma=GLITCH_SIGMA):
    xs = c.xs
    if (c.role, c.metric) not in GLITCH_METRICS or not xs or len(xs) < 5:
        return -1
    d = sorted(abs(xs[i + 1] - xs[i]) for i in range(len(xs) - 1))
    sig = 1.4826 * d[len(d) // 2]
    fl = (c.m or {}).get("floor")
    if fl and sig < fl / 10:
        sig = fl / 10
    if sig <= 0:
        return -1
    at = -1
    for i in range(1, len(xs) - 1):
        a, b, e = xs[i - 1], xs[i], xs[i + 1]
        if abs(b - a) > sigma * sig and abs(b - e) > sigma * sig and abs(e - a) < 2 * sig:
            if at >= 0:
                return -1
            at = i
    return at


def r_glitch(c, p, sigma=GLITCH_SIGMA, touch_cause="changed", drop_ea=False):
    """one isolated single-reading glitch (dataquality.go glitchFree) that IS the window's spike/dip, and the model
    reads spike/dip: a 0 / range-rail value -> sensor_fault dropout; any other value -> normal, no active event."""
    if p["pattern"] not in ("spike", "dip"):
        return []
    i = glitch_at(c, sigma)
    if i < 0:
        return []
    st, xs = c.st, c.xs
    if (p["pattern"] == "spike" and st["max_idx"] != i) or (p["pattern"] == "dip" and st["min_idx"] != i):
        return []
    # the rest of the window must be calm (glitch removed: the relative / limit status of a stable window)
    ys = xs[:i] + [(xs[i - 1] + xs[i + 1]) / 2] + xs[i + 1:]
    st2 = F.compute_stats(ys, c.m["dec"])
    if status_go(c.role, c.metric, "stable", st2, sum(ys[:12]) / 12) != "normal":
        return []
    key = (c.role, c.metric)
    rail = c.m.get("hi")
    if (abs(xs[i]) < 1e-9 and key in GLITCH_ZERO) or (key in GLITCH_RAIL and rail is not None and xs[i] >= rail):
        pass  # sentinel -> dropout below
    elif key not in GLITCH_VALUE:
        return []
    if (abs(xs[i]) < 1e-9 and key in GLITCH_ZERO) or (key in GLITCH_RAIL and rail is not None and xs[i] >= rail):
        tgt = {"status": "sensor_fault", "likely_cause": "sensor_fault", "fault_kind": "dropout"}
        if drop_ea:
            tgt["event_active"] = False
    else:
        tgt = {"status": "normal", "event_active": False}
        if touch_cause == "always" or (touch_cause == "changed" and p["status"] != "normal"):
            tgt["likely_cause"] = NORMAL_CAUSE.get(c.role, p["likely_cause"])
    return [(k, v) for k, v in tgt.items() if p.get(k) != v]


def r_chatter(c, p):
    """the value hovers at the warning limit (>= 3 crossings, every reading within 5% of the limit; dataquality.go
    deadband is 5%) -> warning, event active (REALWORLD 5.11); pattern left to the model."""
    if not c.lim or c.xs is None or c.role not in LIMIT_ROLES:
        return []
    d, warn = c.lim[0], c.lim[1]
    band = 0.05 * abs(warn)
    if any(abs(v - warn) > band for v in c.xs):
        return []
    up = (lambda v: v >= warn) if d == "above" else (lambda v: v <= warn)
    cross = sum(1 for i in range(1, len(c.xs)) if up(c.xs[i]) != up(c.xs[i - 1]))
    if cross < 3:
        return []
    out = []
    if p["status"] == "sensor_fault":
        # only a "flatline" the data contradicts (it crosses the limit >= 3 times, no long flat run) is overridden;
        # a stuck sensor at the limit never crosses it. Other fault reads are left to the model.
        if p["pattern"] != "flatline" or c.st["flat_run"] >= len(c.xs) // 2:
            return []
        cause = G.cause_of(c.role, c.metric, "stable", "warning", F.is_off_hours(c.end), c.node.startswith("SR-"), False)
        out += [("pattern", "stable"), ("likely_cause", cause), ("fault_kind", None)]
    if p["status"] != "warning":
        out.append(("status", "warning"))
    if p.get("event_active") is not True:
        out.append(("event_active", True))
    return out


# ---- off-label cause
CAUSE_MAP = {  # observed / plausible off-label values -> the role's allowed cause
    "acidic_condition": "water_quality_issue", "alkaline_condition": "water_quality_issue",
    "contamination": "water_quality_issue", "water_contamination": "water_quality_issue",
    "high_tds": "water_quality_issue", "low_ph": "water_quality_issue", "high_ph": "water_quality_issue",
    "leak": "possible_leak", "pump_short_cycling": "pump_cycling", "overflow": "tank_overflow_risk",
    "power_outage": "load_drop_or_outage", "outage": "load_drop_or_outage", "overload": "capacity_limit_throttling",
    "poor_ventilation": "ventilation_insufficient", "occupancy": "occupancy_load",
}


# keyword -> cause, per role, first match wins (substring of the off-label value); same table in postrules.go
CAUSE_KEYS = {
    "water": [("acid", "water_quality_issue"), ("alkal", "water_quality_issue"), ("ph", "water_quality_issue"),
              ("tds", "water_quality_issue"), ("contamin", "water_quality_issue"), ("quality", "water_quality_issue"),
              ("turbid", "water_quality_issue"), ("leak", "possible_leak"), ("overflow", "tank_overflow_risk"),
              ("valve", "fill_valve_stuck"), ("cycl", "pump_cycling"), ("fill", "tank_filling"), ("drain", "tank_draining"),
              ("supply", "supply_interruption"), ("demand", "high_demand")],
    "power": [("outage", "load_drop_or_outage"), ("drop", "load_drop_or_outage"), ("surge", "load_surge"),
              ("overload", "capacity_limit_throttling"), ("throttl", "capacity_limit_throttling"),
              ("startup", "equipment_startup"), ("quality", "power_quality_issue"), ("harmonic", "power_quality_issue"),
              ("cycl", "cyclic_equipment"), ("growth", "gradual_load_growth")],
    "air_quality": [("ventilat", "ventilation_insufficient"), ("occupan", "occupancy_load"), ("outdoor", "outdoor_pollution_ingress"),
                    ("emission", "indoor_emission_source"), ("humid", "humidity_control_issue"), ("cooling", "hvac_cooling_issue")],
    "weather": [("diurnal", "diurnal_cycle"), ("front", "weather_front"), ("gust", "gusty_wind"), ("heat", "heat_buildup"),
                ("cool", "cooling_trend")],
}


def r_cause(c, p):
    """a cause outside the role's set: a known synonym (CAUSE_MAP), else the first keyword match (CAUSE_KEYS),
    else abstain to the status-consistent default (sensor_fault / the role's normal cause), else unchanged."""
    allowed = C.enums()["causes"].get(c.role, set())
    cz = p["likely_cause"]
    if not allowed or cz in allowed:
        return []
    if CAUSE_MAP.get(cz) in allowed:
        return [("likely_cause", CAUSE_MAP[cz])]
    for k, v in CAUSE_KEYS.get(c.role, []):
        if k in cz and v in allowed:
            return [("likely_cause", v)]
    if p["status"] == "sensor_fault":
        return [("likely_cause", "sensor_fault")]
    if p["status"] == "normal" and c.role in NORMAL_CAUSE:
        return [("likely_cause", NORMAL_CAUSE[c.role])]
    return []


def r_fkind(c, p):
    """status sensor_fault with a missing / unknown fault_kind -> derive from the pattern."""
    if p["status"] != "sensor_fault" or (p.get("fault_kind") or "") in C.enums()["fault_kinds"] or c.st is None:
        return []
    pt = p["pattern"]
    fk = ("stuck" if pt == "flatline" else "noise" if pt == "erratic" else "dropout" if c.st["min"] == 0.0
          else "bias" if pt.startswith("step") else "saturation" if pt == "throttling" else "drift")
    return [("fault_kind", fk)]


def r_rel_level(c, p):
    return r_rel_water(c, p) if c.metric == "level" else []


RULES = {"rel_level": r_rel_level,
         "floor250": lambda c, p: r_floor(c, p, 250.0), "floor280": lambda c, p: r_floor(c, p, 280.0),
         "glitch12": lambda c, p: r_glitch(c, p, 12.0), "glitch15": lambda c, p: r_glitch(c, p, 15.0),
         "glitch_v1": lambda c, p: r_glitch(c, p, 8.0, "always", True),
         "limit": r_limit, "quality_cause": r_quality_cause, "rel_power": r_rel_power, "rel_water": r_rel_water, "water_cause": r_water_cause,
         "floor": r_floor, "erratic": r_erratic, "glitch": r_glitch, "chatter": r_chatter, "cause": r_cause,
         "fkind": r_fkind}


# ------------------------------------------------------------------ apply + rescore
def parse_full(text):
    s = text.find("{")
    if s < 0:
        return None
    cut, _ = C.cut_at_action(text[s:])
    try:
        d = json.loads(cut)
        return d if isinstance(d, dict) else None
    except json.JSONDecodeError:
        return None


def apply(row, sample, rules, log=None):
    """returns (new scored dict, changes list)."""
    d = parse_full(sample["text"])
    if d is None:
        return sample, []
    p = {k: C._norm(d.get(k, "")) for k in ("pattern", "status", "likely_cause")}
    p["fault_kind"] = C._norm(d["fault_kind"]) if d.get("fault_kind") else None
    p["event_active"] = d.get("event_active")
    c = Ctx(row)
    ch = []
    for name in rules:
        for k, v in RULES[name](c, p):
            ch.append((name, k, p.get(k), v))
            p[k] = v
            if k == "status" and v == "sensor_fault" and p["likely_cause"] != "sensor_fault":
                ch.append((name, "likely_cause", p["likely_cause"], "sensor_fault"))
                p["likely_cause"] = "sensor_fault"
    if not ch:
        return sample, []
    nd = dict(d)
    nd.update(pattern=p["pattern"], status=p["status"], likely_cause=p["likely_cause"])
    if p.get("event_active") is not None:
        nd["event_active"] = p["event_active"]
    if p["status"] == "sensor_fault" and p.get("fault_kind"):
        nd["fault_kind"] = p["fault_kind"]
    elif p["status"] != "sensor_fault":
        nd.pop("fault_kind", None)   # = policy.go: fault_kind only with sensor_fault
    s2 = C.score_one(row, json.dumps(nd))
    s2["slices"] = sample["slices"]
    return s2, ch


KEYS = ("pattern", "status", "cause", "fault_kind", "action", "event_active", "policy", "json")


def slice_table(pairs, keys=KEYS):
    """pairs: list of (before, after) scored dicts -> {slice: {key: (n, before, after, wins, losses)}}"""
    sl = defaultdict(list)
    for b, a in pairs:
        for s in b["slices"]:
            sl[s].append((b, a))
    out = {}
    for s, pp in sl.items():
        row = {"n": len(pp)}
        for k in keys:
            v = [(bool(b[k]), bool(a[k])) for b, a in pp if b.get(k) is not None and a.get(k) is not None]
            if v:
                row[k] = (len(v), sum(x for x, _ in v), sum(y for _, y in v),
                          sum(1 for x, y in v if y and not x), sum(1 for x, y in v if x and not y))
        out[s] = row
    return out


def run_rules(name, rules, tag="v2cuda"):
    data = load(name, tag)
    pairs, changes = [], []
    for row, s in data:
        a, ch = apply(row, s, rules)
        pairs.append((s, a))
        if ch:
            changes.append({"id": row["id"], "slices": s["slices"], "changes": ch,
                            "gold": {"pattern": s["gold_pattern"], "status": s["gold_status"]}})
    return pairs, changes
