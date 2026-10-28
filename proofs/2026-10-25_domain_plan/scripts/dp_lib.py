"""Domain-plan scoring library (WSL python): live post-rules (Go post_rules=all order), extra P1 rules,
E2 paired gates vs mixA50 + rules, flatline drift, claim checks (E1)."""
from __future__ import annotations

import json, re, sys
from collections import defaultdict

sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-24_trackB/scripts")
import trackb_lib as L  # noqa: E402
C = L.C

ALL = ["erratic", "limit", "quality_cause", "rel_power", "rel_level", "water_cause", "glitch", "floor250", "chatter", "cause", "fkind"]
HV_NORMAL = ("stable", "normal_cycling", "pull_down", "setback_drift")


def expand(spec):
    """'ALL' / 'ALL_P1' / comma list -> rule names"""
    import p1_rules as P
    out = []
    for x in spec.split(","):
        out += D_NAMES(P).get(x, [x] if x else [])
    return out


def D_NAMES(P):
    return {"ALL": ALL, "ALL_P1": P.ALL_P1}


def load_rows(path):
    return {r["id"]: r for r in map(json.loads, open(path, encoding="utf-8"))}


def load_samples(path):
    out = {}
    for s in map(json.loads, open(path, encoding="utf-8")):
        out.setdefault(s["id"], s)
    return out


def ruled(rows, samples, rules):
    """id -> (scored-after-rules, changes)"""
    out = {}
    for i, s in samples.items():
        if i in rows:
            a, ch = L.apply(rows[i], s, rules)
            if not ch and rows[i].get("regold"):
                a = dict(C.score_one(rows[i], s["text"]), slices=s.get("slices"), text=s["text"])
            if "pred" not in a:
                a = dict(a, pred=s.get("pred"))
            out[i] = (a, ch)
    return out


def pred(s):
    return s.get("pred") or {}


def flat_flag(s):
    p = pred(s)
    return p.get("pattern") == "flatline" or p.get("status") == "sensor_fault"


def gold_event(s):
    return s["gold_status"] != "sensor_fault" and s["gold_pattern"] not in ("flatline", "erratic") + HV_NORMAL


def slices_of(row, s):
    sl = ["ALL"]
    fam = row.get("family") or ""
    if fam == "compound" or "compound" in (s.get("slices") or []):
        sl.append("compound")
    if row["role"] == "water" and str(row.get("seen", "")).startswith("unseen"):
        sl.append("water_unseen")
    if s["gold_pattern"] == "gradual_decrease":
        sl.append("gold_gradual_decrease")
    if row["role"] == "hvac":
        sl.append("hvac")
    if fam in ("real_routine", "water_fill", "routine"):
        sl.append("fam_" + fam)
    for x in s.get("slices") or []:
        if x.startswith("rw5_") or x in ("calm_or_routine", "stage_early", "stage_1.5h", "stage_3h", "realworld"):
            sl.append(x)
    return sl


def paired(rows, ref, cand, keys=("pattern", "status", "cause")):
    """ref/cand: id -> scored. Returns ({slice: {key: [n, ref_ok, cand_ok, wins, losses]}}, flat_drift dict)."""
    t = defaultdict(lambda: {k: [0, 0, 0, 0, 0] for k in keys})
    fd = {"to_flat": 0, "from_flat": 0, "n_event": 0}
    for i in ref:
        if i not in cand:
            continue
        r, c = ref[i], cand[i]
        for sl in slices_of(rows[i], r):
            for k in keys:
                a, b = bool(r.get(k)), bool(c.get(k))
                v = t[sl][k]
                v[0] += 1; v[1] += a; v[2] += b; v[3] += (b and not a); v[4] += (a and not b)
        if gold_event(r):
            fd["n_event"] += 1
            fd["to_flat"] += flat_flag(c) and not flat_flag(r)
            fd["from_flat"] += flat_flag(r) and not flat_flag(c)
    fd["net"] = fd["to_flat"] - fd["from_flat"]
    return dict(t), fd


def gate_line(name, t, fd, fixed=("compound", "water_unseen", "gold_gradual_decrease", "hvac", "fam_real_routine", "fam_water_fill", "fam_routine")):
    """E2 gates: net flat drift <= 0 and no fixed slice loses > 1 row net (pattern/status/cause)."""
    bad = [f"{s}.{k}{t[s][k][3] - t[s][k][4]:+d}" for s in fixed if s in t for k in t[s] if t[s][k][3] - t[s][k][4] < -1]
    a = t["ALL"]
    f = lambda k: f"{100 * a[k][1] / a[k][0]:.1f}>{100 * a[k][2] / a[k][0]:.1f}({a[k][3]}/{a[k][4]})"
    ok = fd["net"] <= 0 and not bad
    return ok, f"[{name}] n{a['pattern'][0]} p{f('pattern')} s{f('status')} c{f('cause')} flat{fd['net']:+d} {'PASS' if ok else 'FAIL'} {bad}"


# ------------------------------------------------------------------ claim checks (E1; mirrored by Go claimcheck)
RX_NIGHT = re.compile(r"\b(night|overnight|night-time|nighttime|off-hours|off hours|after hours|after-hours|weekend|midnight)\b", re.I)
RX_DAY = re.compile(r"\b(daytime|day-time|working hours|work hours|office hours|business hours)\b", re.I)
RX_NUM = r"(-?\d+(?:\.\d+)?)"
RX_FROMTO = re.compile(r"from\s+" + RX_NUM + r"[^\d\-]{0,12}?\s*(?:to|->|→)\s*" + RX_NUM, re.I)
RX_UP = re.compile(r"\b(up|rose|rise|rising|risen|increas\w*|climb\w*|grew|grow\w*|jump\w*|higher)\b", re.I)
RX_DOWN = re.compile(r"\b(down|fell|fall\w*|drop\w*|decreas\w*|declin\w*|lower\w*|sank|dipp?\w*)\b", re.I)
RX_INBAND = re.compile(r"\b(inside|within|in)\s+(the\s+)?(comfort\s+)?band\b", re.I)
RX_HV_E1 = re.compile(r"^E1 room now ([-\d.]+) C, setpoint [-\d.]+ C \(band ([-\d.]+)-([-\d.]+)\)", re.M)
RX_EIDS = re.compile(r"\[([E\d,\s]+)\]\s*$")


def claim_flags(row, obs, off_hours):
    """-> list of {kind, obs_index, evidence}. Flags only; never edits text."""
    out = []
    for k, o in enumerate(obs or []):
        o = str(o)
        ev = [e.strip() for e in (RX_EIDS.search(o).group(1).split(",") if RX_EIDS.search(o) else [])]
        if RX_NIGHT.search(o) and not off_hours:
            out.append({"kind": "time_of_day", "obs": k, "claim": RX_NIGHT.search(o).group(1).lower(), "fact": "window end is not off-hours", "evidence": ev})
        if RX_DAY.search(o) and off_hours:
            out.append({"kind": "time_of_day", "obs": k, "claim": RX_DAY.search(o).group(1).lower(), "fact": "window end is off-hours", "evidence": ev})
        m = RX_FROMTO.search(o)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            up, dn = bool(RX_UP.search(o)), bool(RX_DOWN.search(o))
            if up != dn and a != b and (up and b < a or dn and b > a):
                out.append({"kind": "direction", "obs": k, "claim": "up" if up else "down", "fact": f"from {a:g} to {b:g}", "evidence": ev})
        if row["role"] == "hvac" and RX_INBAND.search(o):
            e1 = RX_HV_E1.search(row["prompt"])
            if e1:
                now, lo, hi = map(float, e1.groups())
                if now < lo or now > hi:
                    out.append({"kind": "inside_band", "obs": k, "claim": "inside band", "fact": f"room {now:g} C, band {lo:g}-{hi:g}", "evidence": ev + ["E1"]})
    return out


def obs_of(text):
    d = L.parse_full(text) or {}
    o = d.get("observations") or []
    return o if isinstance(o, list) else [o]
