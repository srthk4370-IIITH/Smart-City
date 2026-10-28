"""Paraphrase banks and fact helpers. Every number written comes from an evidence line string (parsed back out of it),
so the verifier can trace it. Several wording families per slot; the generator picks one at random per example."""
import re

from lib import METRICS, word

NUM = r"[-+]?\d+(?:\.\d+)?"


def unit_of(s):
    u = s.get("unit_shown") or METRICS.get((s["role"], s["metric"]), ("",))[0]
    return "" if u in ("level", "0/1", "ratio") else u


def uu(s):
    u = unit_of(s)
    return (" " + u) if u else ""


def ev(s, eid):
    for e, t in s.get("ev", []):
        if e == eid:
            return t
    return None


def parse(s):
    """numbers from the generic E-lines (backend wording); missing keys when the format differs (HVAC/occupancy)."""
    p = {}
    t = ev(s, "E1") or ""
    m = re.match(r"last = (%s)" % NUM, t)
    if m:
        p["last"] = m.group(1)
    m = re.match(r"current state = (\d)", t)
    if m:
        p["state"] = m.group(1)
    m = re.match(r"room now (%s) C, setpoint (%s) C" % (NUM, NUM), t)
    if m:
        p["last"], p["setp"] = m.group(1), m.group(2)
    t = ev(s, "E2") or ""
    m = re.match(r"max = (%s).* at (\d\d:\d\d)" % NUM, t)
    if m:
        p["max"], p["max_t"] = m.group(1), m.group(2)
    m = re.match(r"max (%s) C at (\d\d:\d\d), min (%s) C at (\d\d:\d\d)" % (NUM, NUM), t)
    if m:
        p["max"], p["max_t"], p["min"], p["min_t"] = m.groups()
    m = re.match(r"occupied fraction = (%s)" % NUM, t)
    if m:
        p["frac"] = m.group(1)
    t = ev(s, "E3") or ""
    m = re.match(r"min = (%s).* at (\d\d:\d\d)" % NUM, t)
    if m:
        p["min"], p["min_t"] = m.group(1), m.group(2)
    t = ev(s, "E4") or ""
    m = re.match(r"trend = (%s)(?: \S+)?/h \(r2 (%s)\)" % (NUM, NUM), t) or re.match(r"trend (%s) C/h \(r2 (%s)\)" % (NUM, NUM), t)
    if m:
        p["slope"], p["r2"] = m.group(1), m.group(2)
    m = re.match(r"first occupied at (\S+)", t)
    if m:
        p["first_on"] = m.group(1)
    t = ev(s, "E5") or ""
    m = re.match(r"largest 5-min change = (%s)(?: \S+)? at (\d\d:\d\d)" % NUM, t)
    if m:
        p["jump"], p["jump_t"] = m.group(1), m.group(2)
    m = re.match(r"AC on (\d+)/(\d+) samples", t)
    if m:
        p["ac_on"], p["ac_n"] = m.group(1), m.group(2)
    m = re.match(r"last occupied at (\S+)", t)
    if m:
        p["last_on"] = m.group(1)
    t = ev(s, "E8") or ""
    m = re.match(r"noise (%s), longest flat run (\d+) pts" % NUM, t)
    if m:
        p["noise"], p["flat"] = m.group(1), m.group(2)
    return p


def absn(x):
    return x.lstrip("+-")


def W(s, cap=True):
    w = word(s["role"], s["metric"])
    return (w[0].upper() + w[1:]) if cap and not w[:3].isupper() and not w.startswith("pH") else w


# ---------------------------------------------------------------- observation phrases (text, src ids)
def o_now(R, s):
    p = parse(s)
    if "last" not in p:
        return None
    v, u, w = p["last"], uu(s), W(s)
    return (R.choice(["%s is %s%s now" % (w, v, u), "%s now reads %s%s" % (w, v, u), "Latest %s reading: %s%s" % (W(s, False), v, u),
                      "%s stands at %s%s" % (w, v, u), "%s at %s%s at the end of the window" % (w, v, u)]), [s["ref"] + ".E1"])


def o_trend(R, s):
    p = parse(s)
    if "slope" not in p:
        return None
    sl = p["slope"]
    up = not sl.startswith("-")
    u = uu(s)
    w = W(s)
    a = absn(sl)
    if float(a) == 0:
        return (R.choice(["%s is flat (trend %s%s per hour)" % (w, sl, u), "No trend in %s (%s%s per hour)" % (W(s, False), sl, u)]),
                [s["ref"] + ".E4"])
    vb = R.choice(["rising", "climbing", "increasing"]) if up else R.choice(["falling", "dropping", "decreasing"])
    return (R.choice(["%s %s %s%s per hour (r2 %s)" % (w, vb, a, u, p["r2"]),
                      "%s has been %s at %s%s per hour, r2 %s" % (w, vb, a, u, p["r2"]),
                      "Steady %s of %s%s per hour in %s (r2 %s)" % ("rise" if up else "fall", a, u, W(s, False), p["r2"]),
                      "%s trend: %s%s per hour (r2 %s)" % (w, sl, u, p["r2"])]), [s["ref"] + ".E4"])


def o_path(R, s):
    """from the earlier extreme to the later one, in time order (never 'down from low to high')"""
    p = parse(s)
    if not all(k in p for k in ("max", "min", "max_t", "min_t")):
        return None
    u, w = uu(s), W(s)
    if p["min_t"] <= p["max_t"]:
        a, at, b, bt, vb = p["min"], p["min_t"], p["max"], p["max_t"], R.choice(["rose", "went up", "climbed"])
    else:
        a, at, b, bt, vb = p["max"], p["max_t"], p["min"], p["min_t"], R.choice(["fell", "went down", "dropped"])
    return (R.choice(["%s %s from %s%s at %s to %s%s at %s" % (w, vb, a, u, at, b, u, bt),
                      "%s %s from %s at %s to %s%s by %s" % (w, vb, a, at, b, u, bt),
                      "Between %s and %s %s %s from %s to %s%s" % (at, bt, W(s, False), vb, a, b, u)]),
            [s["ref"] + ".E2", s["ref"] + ".E3"])


def o_jump(R, s):
    p = parse(s)
    if "jump" not in p:
        return None
    u, w = uu(s), W(s)
    return (R.choice(["Largest 5-min change %s%s at %s" % (p["jump"], u, p["jump_t"]),
                      "%s jumped %s%s within 5 minutes at %s" % (w, p["jump"], u, p["jump_t"]),
                      "A single %s%s step in %s at %s" % (p["jump"], u, W(s, False), p["jump_t"])]), [s["ref"] + ".E5"])


def o_flat(R, s):
    p = parse(s)
    if "flat" not in p:
        return None
    return (R.choice(["%s shows no variation: noise %s, flat for %s readings" % (W(s), p["noise"], p["flat"]),
                      "Identical %s values for %s readings (noise %s)" % (W(s, False), p["flat"], p["noise"]),
                      "%s frozen: longest flat run %s points, noise %s" % (W(s), p["flat"], p["noise"])]), [s["ref"] + ".E8"])


def o_noise(R, s):
    p = parse(s)
    if "noise" not in p:
        return None
    return (R.choice(["%s still varies normally (noise %s)" % (W(s), p["noise"]), "%s noise %s, so the sensor is alive" % (W(s), p["noise"])]),
            [s["ref"] + ".E8"])


def o_e9(R, s):
    t = ev(s, "E9")
    if not t or "under 8 h" in t:
        return None
    body = t.split(": ", 1)[1] if ": " in t else t
    return (R.choice(["12 h view of %s: %s" % (W(s, False), body), "Over 12 h, %s shows %s" % (W(s, False), body),
                      "%s over the last 12 h: %s" % (W(s), body)]), [s["ref"] + ".E9"])


def o_occ(R, s):
    p = parse(s)
    if "state" not in p:
        return None
    if p.get("first_on", "never") == "never":
        return (R.choice(["No presence detected all window", "Room empty the whole window", "Occupancy sensor saw nobody in the window"]),
                [s["ref"] + ".E2", s["ref"] + ".E4"])
    if p["state"] == "1":
        return (R.choice(["Room occupied since %s" % p["first_on"], "People present from %s, still present" % p["first_on"],
                          "Occupancy began at %s and continues" % p["first_on"]]), [s["ref"] + ".E4", s["ref"] + ".E1"])
    return (R.choice(["Room was occupied %s-%s, now empty" % (p["first_on"], p["last_on"]),
                      "People left at %s; room now empty" % p["last_on"]]), [s["ref"] + ".E5", s["ref"] + ".E1"])


def o_ac(R, s):
    p = parse(s)
    if "ac_on" not in p:
        return None
    if p["ac_on"] == "0":
        return (R.choice(["AC off the whole window", "AC unit did not run in the window"]), [s["ref"] + ".E5"])
    return (R.choice(["AC ran %s of %s samples" % (p["ac_on"], p["ac_n"]), "AC on for %s of %s samples" % (p["ac_on"], p["ac_n"]),
                      "The unit was running %s of %s samples" % (p["ac_on"], p["ac_n"])]), [s["ref"] + ".E5"])


def o_quote(R, s, eid):
    t = ev(s, eid)
    if not t:
        return None
    return (R.choice(["%s: %s" % (W(s), t), "%s %s" % (W(s), t)]), [s["ref"] + "." + eid])


def o_steady(R, s):
    """related sensor steady (context); falls back to a quoted line"""
    r = o_now(R, s)
    if r is None:
        return o_quote(R, s, "E1")
    low = r[0] if r[0][1:2].isupper() else r[0][0].lower() + r[0][1:]
    return (R.choice(["%s steady; %s" % (W(s), low), r[0] + ", no unusual change"]), r[1])


def o_limit(R, s, lim, which):
    p = parse(s)
    if "last" not in p:
        return None
    u, w = uu(s), W(s)
    low = which.startswith("low")
    which = which.replace("low_", "")
    if low:
        return (R.choice(["%s %s%s is below the %s limit of %s%s" % (w, p["last"], u, which, lim, u),
                          "%s at %s%s, under the %s limit (%s%s)" % (w, p["last"], u, which, lim, u)]), [s["ref"] + ".E1"])
    return (R.choice(["%s %s%s is over the %s limit of %s%s" % (w, p["last"], u, which, lim, u),
                      "%s at %s%s, past the %s limit (%s%s)" % (w, p["last"], u, which, lim, u),
                      "%s %s%s exceeds the %s limit of %s%s" % (w, p["last"], u, which, lim, u)]), [s["ref"] + ".E1"])


def lim_s(v):
    return ("%g" % v)


# ---------------------------------------------------------------- checklist "why" banks
WHY = {
    "inspect_ventilation": ["Fresh-air supply looks insufficient for the load", "Check dampers and fresh-air intake",
                            "Ventilation is not keeping up", "Air exchange too low for current use"],
    "inspect_hvac": ["Cooling is not holding the room temperature", "AC running but the room keeps warming",
                     "Check compressor, filters and refrigerant", "Unit behaviour does not match demand"],
    "check_sensor": ["Readings are physically implausible", "Sensor data does not match related sensors",
                     "Verify the sensor before trusting it", "Check wiring, power and placement"],
    "recalibrate_sensor": ["Offset or drift suggests calibration loss", "Readings drifted away from neighbours",
                           "Calibrate against a reference meter"],
    "replace_sensor": ["Fault returned soon after the last repair", "Earlier repair did not hold",
                       "Repeated failure on the same sensor"],
    "restart_or_reconnect_sensor": ["No current data from this feed", "Feed is stale; reconnect gateway or sensor",
                                    "Too many readings missing to judge"],
    "inspect_water_system": ["Tank level falling without matching demand", "Look for leaks, valves and overflow",
                             "Check pump, inlet valve and pipework", "Water balance does not add up"],
    "inspect_electrical": ["Load or power factor outside normal pattern", "Check panels, capacitor bank and big loads",
                           "Electrical behaviour needs a site check"],
    "review_schedule": ["Equipment running outside the expected schedule", "Schedule does not match occupancy",
                        "Align operating hours with actual use"],
    "request_facility_review": ["Needs the facilities team today", "Escalate to facility management",
                                "Beyond a routine check; get the team involved", "Expert check needed"],
    "monitor": ["Watch the next re-check", "Confirm the trend at the next window", "Keep an eye on it; no fault yet",
                "Check again after the next readings"],
    "none": ["Expected behaviour; nothing to do", "No action needed"],
}


def why(R, a):
    return R.choice(WHY[a])


MONITOR = ["Next re-check: watch {w} and {w2}", "Watch whether {w} keeps moving at the next window",
           "Track {w} at the next re-check", "Confirm at the next refinement that {w} has settled",
           "Watch {w} and the related {w2} readings"]
