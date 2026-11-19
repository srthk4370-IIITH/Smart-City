"""agt_v3 deterministic gold: teacher_v2 label functions + postrules + hvac rules + card severity rules, ported to
card parameters (V3_DESIGN §2.2, §4.1). Every label is a function of what the prompt shows (card + evidence) plus the
simulator's shape hint for the pattern name (as in v2: the generator chooses shapes, the rules label them).

Output key order (frozen): pattern, status, data_quality{verdict, why, src}, severity_reason, evidence, observations,
likely_cause, confidence, event_active, onset, [fault_kind], action.

Consistency rules (enforced here, checked again in verify_agt.py):
  status == sensor_fault  <=> data_quality.verdict == fault (and fault_kind set)
  verdict suspect allows a process status; verdict insufficient -> status normal or warning (critical capped)
  severity_reason names the card limit / rate rule / cycle / tank / fault rule that sets the status (<= 20 words)
"""
from __future__ import annotations

import math
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "core"
sys.path.insert(0, str(CORE))
import evidence as EV  # noqa: E402  (sets up training/ import paths)
import cards as CD  # noqa: E402
import features as F  # noqa: E402
import features_v2 as V  # noqa: E402
import generate_dataset as G  # noqa: E402
import teacher_v2 as TE  # noqa: E402
import templates_v2 as TP  # noqa: E402
import hvac as HV  # noqa: E402

KEY_ORDER = ("pattern", "status", "data_quality", "severity_reason", "evidence", "observations", "likely_cause",
             "confidence", "event_active", "onset", "fault_kind", "action")
UP = {"gradual_increase", "step_increase", "exponential_increase", "throttling"}
DOWN = {"gradual_decrease", "step_decrease"}
ABRUPT = {"spike", "step_increase", "step_decrease", "dip", "exponential_increase", "throttling", "erratic"}
INSUFF_FRAC, SUSPECT_FRAC = 0.25, 0.10
FAULT_WORD = {"stuck": "stuck reading", "bias": "bias step", "drift": "calibration drift", "noise": "noisy sensor",
              "dropout": "dropout to 0", "saturation": "saturated at the sensor limit", "quantised": "coarse quantised readings"}
PAT_WORD = {"gradual_increase": "gradual rise", "gradual_decrease": "gradual fall", "step_increase": "step up",
            "step_decrease": "step down", "spike": "spike", "dip": "dip", "exponential_increase": "accelerating rise",
            "oscillation": "cycling", "throttling": "rise to a plateau", "stable": "steady level", "erratic": "erratic swings",
            "flatline": "flat line"}

# generic templates for synthetic-card routines and data-quality notes ({...} = exact evidence strings)
EXTRA_T = {
    "why_card_cycle": ["{W} matches the card's normal cycle [E4]", "Routine {W} per the card cycle, below limits [E4,E1]",
                       "{M} {W} is the usual daily behaviour [E4]", "Expected {W} for this time of day [E4,E7]"],
    "dq_glitch_hi": ["One impossible reading of {max}{u} at {tmax} ignored [E2]",
                     "Single reading {max}{u} at {tmax} is impossible; treated as a glitch [E2]"],
    "dq_glitch_lo": ["One impossible reading of {min}{u} at {tmin} ignored [E3]",
                     "Single reading {min}{u} at {tmin} is impossible; treated as a glitch [E3]"],
    "dq_impossible_lo": ["{M} at {last}{u} is physically impossible for this sensor [E1,E3]",
                         "Readings down to {min}{u} cannot be real; sensor fault [E3,E1]"],
    "dq_impossible_hi": ["{M} at {last}{u} is physically impossible for this sensor [E1,E2]",
                         "Readings up to {max}{u} cannot be real; sensor fault [E2,E1]"],
    "dq_gaps": ["Many readings missing; the shape is uncertain [E8]", "Gaps in the data; trend {slope} is unreliable [E4]"],
    "rate_above": ["{M} moved from {min} to {max}{u}, beyond the card rate rule [E3,E2]",
                   "Change {min} -> {max}{u} is large against the start level [E3,E2]"],
}


def fill(key, vals, rng, avoid=()):
    if key in EXTRA_T:
        opts = [t for t in EXTRA_T[key] if not any(a in t for a in avoid)] or EXTRA_T[key]
        return rng.choice(opts).format(**vals)
    return TP.fill(key, vals, rng, avoid)


def off_hours(end):
    return F.is_off_hours(end)


def hour_wd(end):
    d = datetime.fromtimestamp(end, V.IST)
    return d.hour + d.minute / 60, d.weekday()


# --------------------------------------------------------------------------------------------- evidence values
def evidence_vals(card, st, info, end, n):
    dec = card["decimals"]
    unit = card["unit"]
    sd = max(dec, 1)
    u = f" {unit}" if unit else ""
    T = lambda i: V.idx_time(end, n, i)  # noqa: E731
    fm = lambda x: F.fmt(x, dec)  # noqa: E731
    v = {"M": card.get("short") or card["quantity"], "u": u, "last": fm(st["last"]), "max": fm(st["max"]), "tmax": T(st["max_idx"]),
         "min": fm(st["min"]), "tmin": T(st["min_idx"]), "slope": f"{st['slope_per_h']:+.{sd}f}{u}/h", "r2": f"{st['r2']:.2f}",
         "jump": f"{st['max_jump_signed']:+.{sd}f}", "tjump": T(st["max_jump_idx"]), "sma": fm(st["sma_1h"]),
         "ema": fm(st["ema_1h"]), "mean": fm(st["mean"]), "h1": fm(st["first_half"]), "h2": fm(st["second_half"]),
         "curv": f"{st['curvature']:+.{sd}f}", "zc": str(st["zero_cross"]), "noise": f"{st['noise']:.{sd + 1}f}",
         "flat": str(st["flat_run"]), "plateau": str(st["plateau_run"]), "hh": f"{info['hist_len'] * 5 / 60:.0f}",
         "k": str(info.get("exc_count", 0)), "peak": f"{info.get('exc_peak', 0.0):.1f}"}
    if card.get("tank"):
        t = card["tank"]
        v.update(high=fm(t["high"]), overflow=fm(t["overflow"]), fill=CD.num(t["fill_min"]))
    for f in info.get("long_view") or []:
        if f["kind"] == "level_shift":
            v.update(shift=f"{f['delta']:+.{sd}f}", tshift=f["time"], sig=f"{f['sigma']:.1f}")
        else:
            v.update(drift=f"{f['delta']:+.{sd}f}", tdrift=f["time"], dr2=f"{f['r2']:.2f}", dsig=f"{f['sigma']:.1f}")
    return v


# --------------------------------------------------------------------------------------------- status rules
def decisive(card, p, st):
    """(value_high, id_high, value_low, id_low) the limit rule reads (today's StatusOf)."""
    hv, hid = (st["max"], "E2") if p in ("spike", "throttling") else (st["last"], "E1")
    lv, lid = (st["min"], "E3") if p in ("spike", "dip") else (st["last"], "E1")
    return hv, hid, lv, lid


def status_limits(card, p, st):
    """-> (status, side, value, eid, limit) ; side high|low|inside."""
    w, c = card["warning"], card["critical"]
    hv, hid, lv, lid = decisive(card, p, st)
    if w["dir"] == "high":
        if hv >= c["at"]:
            return "critical", "high", hv, hid, c["at"]
        if hv >= w["at"]:
            return "warning", "high", hv, hid, w["at"]
        return "normal", "high", hv, hid, w["at"]
    if w["dir"] == "low":
        if lv < c["at"]:
            return "critical", "low", lv, lid, c["at"]
        if lv < w["at"]:
            return "warning", "low", lv, lid, w["at"]
        return "normal", "low", lv, lid, w["at"]
    # both: low side first (as today's pH branch), worst wins
    if lv < c["low"]:
        return "critical", "low", lv, lid, c["low"]
    if hv >= c["high"]:
        return "critical", "high", hv, hid, c["high"]
    if lv < w["low"]:
        return "warning", "low", lv, lid, w["low"]
    if hv >= w["high"]:
        return "warning", "high", hv, hid, w["high"]
    return "normal", "inside", st["last"], "E1", None


def rel_change(st, xs):
    base = sum(xs[:12]) / min(12, len(xs))
    return st["range"] / max(abs(base), 1e-6), base


def status_rate(card, p, st, xs):
    rr = card["rate_rules"]
    rel, base = rel_change(st, xs)
    if p == "stable":
        return "normal", "stable", rel
    if p in ABRUPT:
        if rel > rr["abrupt_crit"]:
            return "critical", "abrupt_crit", rel
        if rel > rr["abrupt_warn"]:
            return "warning", "abrupt_warn", rel
        return "normal", "abrupt_small", rel
    if p in ("gradual_increase", "gradual_decrease"):
        if rr.get("gradual_crit") and rel > rr["gradual_crit"]:
            return "critical", "gradual_crit", rel
        if rel > rr["gradual_warn"]:
            return "warning", "gradual_warn", rel
        return "normal", "gradual_small", rel
    if p == "oscillation":
        return rr.get("osc", "normal"), "osc", rel
    return "normal", "other", rel


def routine(card, p, status, st, end, n, xs, has_limits):
    """card routines -> (status, cause, why_key, routine_name) or None (teacher_v2.routine_rule, card form)."""
    hr, wd = hour_wd(end)
    below = status == "normal"
    for r in card["rules"].get("routines", []):
        t = r["type"]
        if t == "tank":
            tl = card.get("tank")
            if tl and st["last"] >= tl["overflow"]:
                return "critical", "tank_overflow_risk", "why_overflow", "tank_overflow"
            if p in UP:
                if tl and st["max"] >= tl["high"]:
                    return "warning", "tank_overflow_risk", "why_overflow", "tank_high"
                if tl and TE.fill_minutes(st, end, n) >= 2 * tl["fill_min"]:
                    return "warning", "fill_valve_stuck", "why_valve", "tank_valve"
                return "normal", "tank_filling", "why_refill", "tank_refill"
            if p == "oscillation" and off_hours(end):
                return "warning", "possible_leak", "why_night_refills", "tank_night_refills"
            if p == "gradual_decrease":
                if off_hours(end):
                    return "warning", "possible_leak", "offhours_water", "tank_night_drain"
                if TE.long_drain(xs, st["noise"]):
                    return "warning", "possible_leak", "why_day_leak", "tank_long_drain"
                return "normal", "tank_draining", "why_drain", "tank_day_drain"
        elif t == "pump_cycle" and p == "oscillation":
            if TE.osc_period_min(st, n) >= r["min_period"]:
                return "normal", r["cause"], "why_pump", "pump_cycle"
            return "warning", r["cause"], "why_shortcycle", "pump_short_cycle"
        elif t == "osc_normal" and p == "oscillation":
            return "normal", r["cause"], "why_loadcycle", "load_cycle"
        elif t == "workday_steps":
            tj = TE._hm(V.idx_time(end, n, st["max_jump_idx"]))
            if wd < 5 and TE.step_in_window(st):
                if p == "step_increase" and r["up"][0] <= tj <= r["up"][1]:
                    return "normal", r["cause_up"], "why_startup", "workday_startup"
                if p == "step_decrease" and r["down"][0] <= tj <= r["down"][1] and st["last"] >= 0.1 * max(st["first_half"], 1e-9):
                    return "normal", r["cause_down"], "why_shutdown", "workday_shutdown"
        elif t == "solar":
            if (p == "gradual_increase" and r["rise"][0] <= hr < r["rise"][1]) or (p == "gradual_decrease" and r["fall"][0] <= hr < r["fall"][1]):
                return "normal", r["cause"], "why_solar" if card["rules"].get("legacy_key") else "why_card_cycle", "solar_day"
        elif t == "diurnal" and below:
            a, b = r["rise"]
            rise_p, fall_p = ("gradual_decrease", "gradual_increase") if r["invert"] else ("gradual_increase", "gradual_decrease")
            if p == rise_p and a <= hr < b and (r["max_slope"] is None or (st["slope_per_h"] <= r["max_slope"] if not r["invert"] else True)):
                return "normal", r["cause"], "why_diurnal", "diurnal"
            if p == fall_p and (hr >= b or hr < a) and (r["max_slope"] is None or st["slope_per_h"] >= -r["max_slope"]):
                return "normal", r["cause"], "why_diurnal", "diurnal"
        elif t == "rise_in_hours" and below and p in r["patterns"] and r["from"] <= hr < r["to"]:
            return "normal", r["cause"], "why_occ_co2", "occupied_rise"
        elif t == "pattern_normal" and p in r["patterns"] and (below or not has_limits):
            key = {"co2_indoor": "why_co2_decay"}.get(card["rules"].get("type"), None)
            if card["rules"].get("type", "").endswith("_outdoor"):
                key = "why_outdoor_pm"
            return "normal", r["cause"], key or "why_card_cycle", "card_cycle"
        elif t == "osc_small" and below and p == "oscillation" and st["range"] <= r["max_range"]:
            return "normal", r["cause"], "why_hvac_cycle", "ac_cycling"
    return None


def fault_rule(card, p, st, info, end, zero, hint):
    r = card["rules"]
    if p == "flatline" and not zero:
        return "quantised" if hint == "quantised" else "stuck"
    if p == "erratic" and r.get("erratic_fault", True):
        return "dropout" if hint == "dropout" else "noise"
    if p in ("dip", "erratic") and st["min"] == 0.0 and hint == "dropout":
        return "dropout"
    ms = card.get("max_step")
    if p in ("step_increase", "step_decrease") and ms and abs(st["max_jump_signed"]) > ms:
        return "bias"
    rail = (card.get("impossible") or {}).get("above")
    if p == "throttling" and rail is not None and st["max"] >= rail:
        return "saturation"
    lv = TE.lv_kinds(info)
    if (r.get("drift_fault") and "slow_drift" in lv and lv["slow_drift"]["r2"] >= TE.DRIFT_R2
            and info.get("hist_len", 0) >= TE.DRIFT_MIN_PTS and lv["slow_drift"]["sigma"] >= TE.DRIFT_SIGMA
            and off_hours(end) and p in ("gradual_increase", "gradual_decrease", "stable")):
        return "drift"
    return None


def impossible_idx(card, xs):
    imp = card.get("impossible") or {}
    lo, hi = imp.get("below"), imp.get("above")
    out = []
    for i, v in enumerate(xs):
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            out.append(i)
    return out


def cause_of(card, p, status, end, zero):
    lk = card["rules"].get("legacy_key")
    if lk and lk[0] in ("air_quality", "water", "power", "weather"):
        role, metric = lk
        c = G.cause_of(role, metric, p, status, off_hours(end), bool(card["rules"].get("indoor", True)), zero)
        if card["rules"].get("quality_cause") and status in ("warning", "critical") and p != "stable":
            c = "water_quality_issue"
        return c if c in card["causes"] else card["rules"]["normal_cause"]
    cm = card["rules"].get("cause_map", {})
    if p == "stable" or (p == "flatline" and zero):
        return card["rules"]["normal_cause"]
    if p in UP:
        return cm.get("up", card["rules"]["normal_cause"])
    if p in DOWN or p == "dip":
        return cm.get("down", card["rules"]["normal_cause"])
    if p == "spike":
        return cm.get("spike", card["rules"]["normal_cause"])
    if p == "oscillation":
        return cm.get("osc", card["rules"]["normal_cause"])
    return card["rules"]["normal_cause"]


def action_of(card, cause, status):
    lk = card["rules"].get("legacy_key")
    if lk and lk[0] in ("air_quality", "water", "power", "weather", "occupancy"):
        return TE.action_of(cause, status)
    a = card["rules"]["cause_action"].get(cause, "monitor")
    if a == "none" and status in ("warning", "critical"):
        return "monitor"
    if a == "monitor" and status == "critical":
        return "request_facility_review"
    return a


# --------------------------------------------------------------------------------------------- severity reason
def _fmtv(card, v):
    return F.fmt(v, card["decimals"])


def limit_reason(card, status, side, val, eid, lim):
    u = (" " + card["unit"]) if card["unit"] else ""
    s = f"{eid} {_fmtv(card, val)}{u}"
    w = card["warning"]
    if status == "normal":
        if w["dir"] == "high":
            return f"{s} below warning {CD.num(w['at'])} (card)"
        if w["dir"] == "low":
            return f"{s} above warning {CD.num(w['at'])} (card)"
        return f"{s} inside {CD.num(w['low'])}-{CD.num(w['high'])} (card)"
    which = "critical" if status == "critical" else "warning"
    rel = "above" if side == "high" else "below"
    return f"{s} {rel} {which} {CD.num(lim)} (card)"


def rate_reason(card, status, why, p, rel):
    rr = card["rate_rules"]
    ac = CD.num(round(rr["abrupt_crit"] * 100))
    gw = CD.num(round(rr["gradual_warn"] * 100))
    if why == "abrupt_crit":
        return f"{PAT_WORD[p]} from E3 to E2 is over {ac}% of the first-hour level (card rate rule)"
    if why == "abrupt_warn":
        if rr["abrupt_warn"] <= 0:
            return f"{PAT_WORD[p]} under {ac}% change: warning (card rate rule)"
        return f"{PAT_WORD[p]} over {CD.num(round(rr['abrupt_warn'] * 100))}%, under {ac}%: warning (card rate rule)"
    if why == "abrupt_small":
        return f"{PAT_WORD[p]} under {CD.num(round(rr['abrupt_warn'] * 100))}% of the first-hour level: normal (card rate rule)"
    if why == "gradual_warn":
        return f"{PAT_WORD[p]} over {gw}% of the first-hour level: warning (card rate rule)"
    if why == "gradual_crit":
        return f"{PAT_WORD[p]} over {CD.num(round(rr['gradual_crit'] * 100))}% of the first-hour level: critical (card rate rule)"
    if why == "gradual_small":
        return f"{PAT_WORD[p]} under {gw}% of the first-hour level: normal (card rate rule)"
    if why == "osc":
        return f"cycling is {rr.get('osc', 'normal')} (card rate rule)"
    return "no change beyond noise (card rate rule)"


ROUTINE_REASON = {
    "tank_overflow": "E1 {last} above overflow {overflow} (card tank)",
    "tank_high": "E2 {max} above high level {high} (card tank)",
    "tank_valve": "filling since E3 {tmin}, over 2x the usual {fill} min (card tank)",
    "tank_refill": "tank refill is normal (card cycle)",
    "tank_night_refills": "repeated refills at night = warning (card cycle)",
    "tank_night_drain": "fall at night 22:00-06:00 = warning (card cycle)",
    "tank_long_drain": "3 h steady drain with no refill = warning (card cycle)",
    "tank_day_drain": "daytime fall is normal use (card cycle)",
    "pump_cycle": "pump cycling every 50 min or more is normal (card cycle)",
    "pump_short_cycle": "cycling faster than every 50 min = warning (card cycle)",
    "load_cycle": "on/off cycling is normal (card cycle)",
    "workday_startup": "workday start-up step at E5 {tjump} is normal (card cycle)",
    "workday_shutdown": "workday shut-down step at E5 {tjump} is normal (card cycle)",
    "solar_day": "normal daylight shape for this hour (card cycle)",
    "diurnal": "diurnal change below the limits (card cycle)",
    "occupied_rise": "rise in occupied hours below warning {warn} (card cycle)",
    "card_cycle": "{W} below the limits is normal (card cycle)",
    "ac_cycling": "AC cycling within 2 C below warning {warn} (card cycle)",
}


def fault_reason(card, fk, vals, imp_side=None):
    if fk == "stuck":
        return f"E8 flat run {vals['flat']} pts: stuck reading, a data fault (card faults)"
    if fk == "bias":
        if imp_side:
            return f"E1 {vals['last']} is impossible ({imp_side}): sensor fault (card)"
        return f"E5 {vals['jump']} exceeds max 5-min change {CD.num(card['max_step'])}: bias (card)"
    if fk == "drift":
        return f"E9 slow drift {vals.get('drift', '')} off-hours: calibration drift (card faults)"
    if fk == "noise":
        return f"E8 noise {vals['noise']} far above card noise {CD.num(card['noise'])}: noisy sensor (card faults)"
    if fk == "dropout":
        return "readings of 0 are impossible here: dropout, a data fault (card)"
    if fk == "saturation":
        return f"E2 {vals['max']} pinned at the sensor limit: saturation (card faults)"
    if fk == "quantised":
        return f"E8 flat run {vals['flat']} pts in coarse steps: quantised readings (card faults)"
    return "data fault (card faults)"


# --------------------------------------------------------------------------------------------- main label
def order(t):
    return {k: t[k] for k in KEY_ORDER if k in t}


def ids_in(*texts):
    s = set()
    for t in texts:
        for m in re.findall(r"\bE(\d+)\b", t or ""):
            s.add(int(m))
    return [f"E{i}" for i in sorted(s)]


def label(ex):
    """ex: card, pattern (shape hint), family, size, d, onset_idx, active, fault_hint, ramp, xs (window, gaps held),
    hist, missing (window mask or None), n, end, st, info, rng, zero, glitch (bool). -> (target, meta)"""
    card, rng = ex["card"], ex["rng"]
    if card["kind"] == "binary_state":
        return occ_label(ex)
    if card["kind"] == "hvac_unit":
        return hvac_label(ex)
    n, end, st, info, xs = ex["n"], ex["end"], ex["st"], ex["info"], ex["xs"]
    p = ex["pattern"]
    fam = ex["family"]
    hint = ex.get("fault_hint")
    zero = ex.get("zero", False)
    vals = evidence_vals(card, st, info, end, n)
    T = lambda i: V.idx_time(end, n, i)  # noqa: E731
    lv = TE.lv_kinds(info)
    has_limits = card["warning"] is not None
    missing = ex.get("missing") or []
    mfrac = (sum(1 for m in missing if m) / n) if missing else 0.0
    small = ex.get("size") is not None and ex["size"] < TE.BOUNDARY and fam in TE.AMPLITUDE_FAMILIES
    shape = p
    if small:
        p = "stable"
    imp = impossible_idx(card, xs)
    dq = {"verdict": "ok", "why": "", "src": []}
    fault, imp_side, why_r, rname = None, None, None, None
    glitch = False
    if imp:
        lo = (card["impossible"] or {}).get("below")
        lowside = lo is not None and xs[imp[0]] < lo
        if len(imp) == 1 and imp[0] != n - 1 and hint == "impossible_glitch":
            glitch = True
        else:
            fault = "dropout" if all(xs[i] == 0.0 for i in imp) and lowside else "bias"
            imp_side = f"below {CD.num(lo)}" if lowside else f"above {CD.num(card['impossible']['above'])}"
    st_eff = st
    if glitch:
        # status from the process with the glitch removed (neighbour value), as dataquality.go would reject it
        y2 = list(xs)
        i = imp[0]
        y2[i] = y2[i - 1] if i > 0 else y2[i + 1]
        st_eff = F.compute_stats(y2, card["decimals"])
    if fault is None and not glitch and not small:
        fault = fault_rule(card, p, st, info, end, zero, hint)
    # ---- status
    if fault:
        status, cause = "sensor_fault", "sensor_fault"
        sev = fault_reason(card, fault, vals, imp_side)
    else:
        if p == "flatline" and zero:
            status, sev = "normal", "idle at 0, allowed for this sensor (card)"
        elif has_limits:
            status, side, val, eid, lim = status_limits(card, p, st_eff)
            sev = limit_reason(card, status, side, val, eid, lim)
        elif card.get("rate_rules"):
            status, why, rel = status_rate(card, p, st_eff, xs)
            sev = rate_reason(card, status, why, p, rel)
        else:
            status, sev = "normal", "no limit applies (card)"
        if fam == "recurring":
            if not has_limits or status == "normal":
                status = "normal"
                cause = card["rules"].get("recur_cause") or card["rules"]["normal_cause"]
                if not has_limits:
                    sev = "small recurring excursions only (card rate rule)"
            else:
                cause = cause_of(card, "spike", status, end, zero)
        else:
            cause = cause_of(card, p, status, end, zero)
        r = None if fam == "recurring" else routine(card, p, status, st_eff, end, n, xs, has_limits)
        if r:
            status, cause, why_r, rname = r
            w = card["warning"]
            sev = ROUTINE_REASON[rname].format(W=PAT_WORD.get(p, p), warn=CD.num(w["at"]) if w and "at" in w else "", **vals)
    # ---- data quality
    if fault:
        dq = {"verdict": "fault", "why": {"stuck": f"flat for {vals['flat']} pts at {vals['last']}",
                                         "bias": (f"value {vals['last']} impossible ({imp_side})" if imp_side else f"jump {vals['jump']} too fast to be physical"),
                                         "drift": "slow one-way drift over 12 h while the room is empty",
                                         "noise": f"noise {vals['noise']} far above normal",
                                         "dropout": "readings of 0 the sensor cannot report",
                                         "saturation": f"pinned at {vals['max']}, the sensor limit",
                                         "quantised": "coarse steps instead of a smooth signal"}[fault],
              "src": {"stuck": ["E8", "E1"], "bias": ["E1"] if imp_side else ["E5"], "drift": ["E9"], "noise": ["E8"],
                      "dropout": ["E3"], "saturation": ["E2", "E8"], "quantised": ["E8"]}[fault]}
    elif glitch:
        hi_side = xs[imp[0]] >= st["max"]
        dq = {"verdict": "suspect", "why": f"one impossible reading at {T(imp[0])} ignored",
              "src": ["E2"] if hi_side else ["E3"]}
    elif mfrac >= INSUFF_FRAC:
        k = sum(1 for m in missing if m)
        dq = {"verdict": "insufficient", "why": f"{k} of {n} readings missing", "src": ["GAPS"]}
        if status == "critical":
            status = "warning"
            sev = f"{k} of {n} readings missing: insufficient data, critical not allowed (card)"
    elif mfrac >= SUSPECT_FRAC:
        k = sum(1 for m in missing if m)
        dq = {"verdict": "suspect", "why": f"{k} of {n} readings missing; read on the rest", "src": ["GAPS", "E8"]}
    else:
        dq = {"verdict": "ok", "why": rng.choice(("noise normal, inside physical range", "plausible values, normal noise",
                                                  "smooth signal inside the physical range")),
              "src": ["E8", "E2"] if rng.random() < 0.5 else ["E8", "E3"]}
        if missing:
            dq["why"] = "short gap only; " + dq["why"]
            dq["src"] = ["GAPS", "E8"]
    # ---- event_active / onset (teacher_v2)
    wstart = T(0)
    if p == "stable" or (p == "flatline" and zero):
        active, onset = False, wstart
    elif p == "spike" and fam != "recurring":
        active, onset = bool(ex.get("active")), vals["tmax"]
    elif p == "dip" and fault != "dropout":
        active, onset = bool(ex.get("active")), vals["tmin"]
    elif fam == "old_shift" and "level_shift" in lv:
        active, onset = True, lv["level_shift"]["time"]
    elif p in ("step_increase", "step_decrease") and (ex.get("onset_idx") is None or
                                                     abs(st["max_jump_idx"] - ex["onset_idx"]) <= ex.get("ramp", 1) + 1):
        active, onset = True, vals["tjump"]
    elif fam == "recurring":
        active = bool(ex.get("active"))
        onset = T(ex["onset_idx"]) if ex.get("onset_idx") is not None and ex["onset_idx"] >= 0 else ex.get("onset_time", wstart)
    else:
        active = True
        oi = ex.get("onset_idx")
        onset = ex.get("onset_time") or (T(oi) if oi is not None and oi >= 0 else wstart)
    # ---- observations
    vals_w = dict(vals, W=PAT_WORD.get(p, p))
    if small:
        k = {"spike": "small_blip", "dip": "small_dip", "step_increase": "small_shift", "step_decrease": "small_shift"}.get(shape, "small_trend")
        if shape == "oscillation" or fam in ("old_shift", "long_drift"):
            k = "stable"
        obs1 = fill(k, vals_w, rng)
    else:
        obs1 = fill(TE.obs1_key(p, fam, ex, lv, card["rules"].get("legacy_key", ["x"])[0] if card["rules"].get("legacy_key") else
                                ("power" if not card["rules"].get("erratic_fault", True) else "x"), zero, status),
                    vals_w, rng, TE.contradicting(p, st))
    obs2 = None
    if fault and imp_side:
        obs2 = fill("dq_impossible_lo" if imp_side.startswith("below") else "dq_impossible_hi", vals_w, rng)
    elif fault and fault != "stuck":
        obs2 = fill({"bias": "why_bias", "drift": "why_drift", "noise": "why_noise", "quantised": "why_quantised",
                     "dropout": "why_dropout", "saturation": "why_saturation"}[fault], vals_w, rng)
    elif fault == "stuck":
        obs2 = fill("why_stuck", vals_w, rng) if rng.random() < 0.5 else None
    elif glitch:
        obs2 = fill("dq_glitch_hi" if dq["src"] == ["E2"] else "dq_glitch_lo", vals_w, rng)
    elif status in ("warning", "critical") and has_limits and not why_r:
        _, side, val, eid, lim = status_limits(card, p, st_eff)
        key = "limit_below" if side == "low" else "limit_above"
        obs2 = fill(key, dict(vals_w, val=_fmtv(card, val), eid=eid, lim=CD.num(lim), status=status), rng)
    elif status in ("warning", "critical") and card.get("rate_rules") and not why_r:
        obs2 = fill("rate_above", vals_w, rng)
    elif why_r:
        obs2 = fill(why_r, vals_w, rng) if why_r != "offhours_water" or rng.random() < 0.8 else None
    elif fam == "compound" and ex.get("secondary") in ("spike", "dip"):
        obs2 = fill("compound_" + ex["secondary"], vals_w, rng)
    elif dq["verdict"] in ("insufficient", "suspect") and missing:
        obs2 = fill("dq_gaps", vals_w, rng)
    elif fam == "recurring" and ex.get("window_spike"):
        obs2 = fill("recurring_recent", vals_w, rng) if rng.random() < 0.7 else None
    elif p != "stable" and "level_shift" in lv and fam != "old_shift" and rng.random() < 0.5:
        obs2 = fill("context_shift", vals_w, rng)
    elif p != "stable" and "slow_drift" in lv and fam != "long_drift" and rng.random() < 0.5:
        obs2 = fill("context_drift", vals_w, rng)
    elif p in ("spike", "dip") and info.get("exc_count", 0) >= 2 and fam != "recurring" and rng.random() < 0.5:
        obs2 = fill("context_episodes", vals_w, rng)
    obs = [obs1] + ([obs2] if obs2 else [])
    # ---- confidence (teacher_v2 calibration)
    d = ex.get("d")
    if small:
        conf = TE.calibrated("boundary")
    elif why_r:
        conf = TE.calibrated("routine")
    elif p == "stable":
        conf = TE.calibrated("stable")
    elif p == "flatline" and zero:
        conf = TE.calibrated("zero_idle")
    elif fam in ("old_shift", "long_drift", "recurring"):
        conf = TE.calibrated(fam)
    elif fault in ("drift", "saturation", "dropout"):
        conf = TE.calibrated({"drift": "calib_drift"}.get(fault, fault))
    elif fault:
        conf = TE.calibrated(hint if hint in TE.PROXY or hint in TE.PRIORS else fault, d, None) if hint not in ("impossible",) else 0.85
    else:
        conf = TE.calibrated(p, d, ex.get("size"))
    if dq["verdict"] == "insufficient":
        conf = round(max(0.3, conf - 0.2), 2)
    elif dq["verdict"] == "suspect":
        conf = round(max(0.3, conf - 0.1), 2)
    if len(sev.split()) > 20:
        sev = " ".join(sev.split()[:20])
    t = {"pattern": p, "status": status, "data_quality": dq, "severity_reason": sev}
    t["evidence"] = ids_in(sev, *obs, " ".join(x for x in dq["src"] if x.startswith("E")))
    t.update({"observations": obs, "likely_cause": cause, "confidence": conf, "event_active": active, "onset": onset})
    if status == "sensor_fault":
        t["fault_kind"] = fault
    t["action"] = action_of(card, cause, status)
    meta = {"small": small, "fault_kind": fault, "routine": rname, "glitch": glitch, "missing_frac": round(mfrac, 3),
            "shape": shape}
    return order(t), meta


# --------------------------------------------------------------------------------------------- occupancy / binary
def occ_label(ex):
    xs, end, n, info, rng, card = ex["xs"], ex["end"], ex["n"], ex["info"], ex["rng"], ex["card"]
    pattern, st = TE.occ_label(xs, end, n)
    tgt = TE.occ_target(pattern, st, {"occ_frac_12h": info.get("occ_frac_12h", 0.0)}, end, n, rng)
    T = lambda i: V.idx_time(end, n, i)  # noqa: E731
    status = tgt["status"]
    if status == "sensor_fault":
        sev = f"E3 {st['toggles']} state changes: more than 3 per hour is a flapping sensor (card cycle)"
        dq = {"verdict": "fault", "why": f"{st['toggles']} state changes, flapping", "src": ["E3"]}
    elif pattern == "off_hours_presence":
        sev = f"presence with window end {T(n - 1)} off-hours 22:00-06:00 = warning (card cycle)"
        dq = {"verdict": "ok", "why": "clean 0/1 states", "src": ["E3"]}
    else:
        sev = {"vacant": "no presence: normal (card cycle)", "occupied": "presence in normal hours (card cycle)",
               "arrival": f"arrival at E4 {T(st['first_on']) if st['first_on'] >= 0 else T(0)} in normal hours (card cycle)",
               "departure": f"departure after E5 {T(st['last_on']) if st['last_on'] >= 0 else T(0)} is normal (card cycle)",
               "intermittent": "intermittent presence in normal hours (card cycle)"}[pattern]
        dq = {"verdict": "ok", "why": "clean 0/1 states", "src": ["E3"]}
    t = {"pattern": pattern, "status": status, "data_quality": dq, "severity_reason": sev}
    t["evidence"] = ids_in(sev, *tgt["observations"], "E3")
    for k in ("observations", "likely_cause", "confidence", "event_active", "onset"):
        t[k] = tgt[k]
    if status == "sensor_fault":
        t["fault_kind"] = tgt.get("fault_kind", "noise")
    t["action"] = tgt["action"]
    return order(t), {"fault_kind": t.get("fault_kind"), "routine": None, "glitch": False, "missing_frac": 0.0, "shape": pattern}


# --------------------------------------------------------------------------------------------- HVAC unit
def hvac_label(ex):
    lab = ex["hvac_label"]
    xs, ctx, n = ex["xs"], ex["hvac_ctx"], ex["n"]
    st = HV.hvac_stats(xs, ctx)
    p, status = lab["pattern"], lab["status"]
    sp = st["sp_last"]
    band = f"{HV.fmt1(sp - HV.BAND_LO)}-{HV.fmt1(sp + HV.BAND_HI)}"
    fk = HV.FAULT_KIND.get(p) if status == "sensor_fault" else None
    if fk:
        sev = {"stuck": "temperature flat while the unit runs: stuck sensor (card faults)",
               "noise": "erratic room temperature: noisy sensor (card faults)",
               "bias": "temperature jump or reading impossible for a running AC: bias (card faults)",
               "drift": "steady fall with the AC off by day: calibration drift (card faults)",
               "dropout": f"E8 missing {st['missing']}/{n} readings: dropout (card faults)",
               "saturation": "pinned at the 10 / 45 C sensor limit: saturation (card faults)",
               "quantised": "whole-degree readings only: quantised (card faults)"}[fk]
        dq = {"verdict": "fault", "why": sev.split(":")[0], "src": {"dropout": ["E8"], "quantised": ["E7"], "bias": ["E7", "E1"]}.get(fk, ["E7"])}
    else:
        if p in ("too_hot", "no_cooling_effect", "slow_recovery"):
            sev = f"E1 room {HV.fmt1(st['last'])} C vs band {band} C: {status} (card)"
        elif p == "too_cold":
            sev = f"E1 room {HV.fmt1(st['last'])} C below band {band} C: {status} (card)"
        elif p == "short_cycling":
            sev = f"E5 {len(st['starts'])} starts with short runs: short cycling, {status} (card)"
        elif p == "stuck_off":
            sev = f"unit off when usually on, room above band: {status} (card)"
        elif p == "stuck_on":
            sev = "running all night below setpoint need: warning (card cycle)"
        elif p == "running_empty_room":
            sev = "AC running in a vacant room for over 1 h: warning (card)"
        elif p == "unit_alarm":
            sev = "unit reports an alarm: warning (card)"
        else:
            sev = f"room {HV.fmt1(st['last'])} C inside band {band} C: normal (card)" if p in ("stable", "normal_cycling") else \
                  {"pull_down": "normal pull-down after start (card)", "setback_drift": "setback drift with AC off is normal (card cycle)"}[p]
        dq = {"verdict": "ok", "why": "plausible room temperature, readings complete", "src": ["E8"]}
    t = {"pattern": p, "status": status, "data_quality": dq, "severity_reason": sev}
    t["evidence"] = ids_in(sev, *lab["observations"], " ".join(dq["src"]))
    for k in ("observations", "likely_cause", "confidence", "event_active", "onset"):
        t[k] = lab[k]
    if fk:
        t["fault_kind"] = fk
    t["action"] = lab["action"]
    return order(t), {"fault_kind": fk, "routine": None, "glitch": False, "missing_frac": 0.0, "shape": p}
