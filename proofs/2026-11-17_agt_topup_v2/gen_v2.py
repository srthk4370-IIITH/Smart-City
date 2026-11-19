"""gen_v2.py: agt_v3 top-up v2 NEW rows (synthetic only; CPU). Reuses proofs/2026-11-13_v3_data/agt_v3/gen_agt.py (simulator, teacher,
prompt builder) by import; nothing of it is rewritten. Families (all prompts are byte-identical to what agt_v3 sees, except the tool rows
which only add assistant / ipython turns, see PROTOCOL.md and gen_tools.py):
  dyn_*          dynamic windows: event / stable / fault / occupancy / routine rows with a forced window 1.5 h (18 pts) / 3 h (36) / 4 h (48) / 12 h (144)
  hard_standby   sub-resolution standby on a kW card (rendered with the app's effDec): stable / normal, not flatline / stuck
  hard_leak      early part of a slow leak ramp (tank): gradual_decrease warning, not stable
  hard_night     presence at night = off_hours_presence (warning), not sensor_fault; flapping stays the fault contrast
  hard_plateau   lone plateau (throttling) or lone step inside the card limits = real event, not sensor_fault
  hard_limits    card-edited limits (wide jitter), status follows the CARD limits in the prompt
  hard_ph        rare-cadence sensor (water pH, one fresh reading every 30-120 min, held between), GAPS line and matching data_quality
  weak_*         roles the v1 selection showed weak: power / water events and faults, calm rows that are stable (not oscillation)
  tool_*         see gen_tools.py
usage (module): imported by gen_run.py"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import os
import sys
from pathlib import Path

QIDK = Path(os.environ.get("QIDK", "/mnt/c/Users/hp/Desktop/qidk"))
sys.path.insert(0, str(QIDK / "proofs/2026-11-13_v3_data/agt_v3"))
import gen_agt as GA  # noqa: E402  (also puts core/ and training/ on sys.path)

EV, CD, TV, F, V, SM = GA.EV, GA.CD, GA.TV, GA.F, GA.V, GA.SM
EOT = "<|eot_id|>"
WIN_N = {"1.5h": 18, "3h": 36, "4h": 48, "12h": 144}
WIN_W = {"1.5h": 0.25, "3h": 0.25, "4h": 0.30, "12h": 0.20}
NF = {"n": None}


def _pick_forced(rng, fam, p=None, stage=None):
    stage = stage or rng.choice(GA.STAGES)
    return (NF["n"] or 48), stage


GA.pick_n = _pick_forced


def wname(n):
    return {18: "1.5h", 36: "3h", 48: "4h", 144: "12h"}.get(n, "%gh" % (n / 12))


def pick_win(rng):
    ks = list(WIN_W)
    return WIN_N[rng.choices(ks, weights=[WIN_W[k] for k in ks])[0]]


def rid(prefix, text):
    return "%s-%s" % (prefix, hashlib.sha1(text.encode()).hexdigest()[:12])


@contextlib.contextmanager
def with_dec(card, dec):
    """render with another number of decimals (the app's effDec for sub-resolution values)"""
    key = EV.register(card)
    olds = []
    for M in (F.METRICS, V.METRICS):
        if key in M:
            olds.append((M[key], dict(M[key])))
            M[key]["dec"] = dec
    try:
        yield
    finally:
        for d, o in olds:
            d.update(o)


def eff_dec(xs, dec):
    """features.go effDec"""
    if dec < 2:
        return dec
    mx = max([abs(v) for v in xs] or [0.0])
    while dec < 4 and mx > 0 and mx < 10 ** (1 - dec):
        dec += 1
    return dec


def tag(row, fam, prefix, extra_slices=()):
    row["family"] = fam
    row["stage"] = wname(row["n"])
    row["slices"] = list(row["slices"]) + list(extra_slices)
    row["id"] = rid(prefix, row["prompt"])
    row["synthetic"], row["source"] = True, "synthetic_sim_v2"
    return row


def finish(T, sn, y, n, end, fam, sub, p, extra, stage, slices, missing=None, dec=None):
    """GA.finish_cont with the number of decimals the app would print (effDec); same prompt / teacher path"""
    card = sn.card
    y = [round(v, 6 if dec else 4) for v in y]
    xs = y[-n:]
    wm = (missing or [False] * len(y))[-n:] if missing else None
    if wm and not any(wm):
        wm = None
    ctx = with_dec(card, dec) if dec else contextlib.nullcontext()
    with ctx:
        user, st, ev, info = EV.agent_user(card, sn.device, sn.location, y[-V.HIST:], n, end, place=sn.place, missing=wm)
        e = dict(extra, card=card, pattern=p, family=fam, xs=xs, hist=y, n=n, end=end, st=st, info=info, rng=T.rng, missing=wm,
                 zero=extra.get("zero", False))
        tgt, meta = TV.label(e)
    row = GA.make_row(T, sn, y, n, end, fam, sub, stage, slices, user, tgt, meta, extra)
    return tag(row, fam, "v2-" + fam)


# ---------------------------------------------------------------------------------------------------- dynamic windows
DYN_FAM = [("ex_event", 0.50), ("ex_stable", 0.12), ("ex_fault", 0.20), ("ex_occupancy", 0.10), ("calm_routine", 0.08)]


def gen_dyn(T):
    rng = T.rng
    NF["n"] = pick_win(rng)
    T.fam = rng.choices([a for a, _ in DYN_FAM], weights=[b for _, b in DYN_FAM])[0]
    r = GA.one(T)
    if not r or r["n"] != NF["n"]:
        return None
    return tag(r, "dyn_" + T.fam, "v2-dyn", ["v2_dyn", "win_" + wname(r["n"])])


# ---------------------------------------------------------------------------------------------------- hard cases
def gen_standby(T):
    rng = T.rng
    sn = T.sensor_for("power_load")
    if sn is None:
        return None
    if rng.random() < 0.3:
        sn.card = GA._jit(sn.card, rng)
    card = sn.card
    n = pick_win(rng)
    end = GA.end_at(rng, T.split)
    base = rng.choice((0.0015, 0.0022, 0.0026, 0.003, 0.003, 0.0035, 0.0045, 0.006, 0.0085))
    rel = rng.uniform(0.02, 0.1)
    y = [base * (1 + rng.gauss(0, rel)) for _ in range(144)]
    for i in range(1, 144):                       # sticky texture of a W-resolution meter: values repeat sometimes
        if rng.random() < 0.25:
            y[i] = y[i - 1]
    kind = rng.choice(("pure", "pure", "bump", "late_low"))
    if kind == "bump":                            # a short 20-90 W draw: tiny on the kW card, no limit
        o = rng.randint(144 - n + 4, 140)
        for i in range(o, min(144, o + rng.randint(1, 3))):
            y[i] = rng.uniform(0.02, 0.09)
    elif kind == "late_low":                      # earlier running load (kW) that stopped long before the window
        k = rng.randint(4, max(5, 144 - n - 12))
        lv = rng.uniform(0.4, 3.0)
        for i in range(k):
            y[i] = lv * (1 + rng.gauss(0, 0.04))
    xs = y[-n:]
    dec = eff_dec(xs, card["decimals"])
    sn.card = copy.deepcopy(card)
    sn.card["decimals"] = dec                     # teacher text prints with the same decimals as the prompt
    p = "stable" if kind != "bump" else rng.choice(("stable", "spike"))
    row = finish(T, sn, y, n, end, "hard_standby", "standby_" + kind, p, {"size": None, "d": None, "onset_idx": None}, "stage_3h",
                 ["hard", "standby", "calm_or_routine"], dec=dec)
    g = row["gold"]
    if g["status"] != "normal" or g["pattern"] in ("flatline", "erratic") or g["data_quality"]["verdict"] != "ok":
        return None
    return row


def gen_leak(T):
    rng = T.rng
    sn = T.sensor_for("tank_level")
    if sn is None:
        return None
    if rng.random() < 0.35:
        sn.card = GA._jit(sn.card, rng)
    n = rng.choice((36, 48, 48, 144))
    NF["n"] = n
    tgt = rng.choice(("warning", "warning", "warning", "normal"))
    d = rng.randint(6, 22)                        # the early part of the ramp
    end = GA.end_at(rng, T.split, hours=(9, 19) if rng.random() < 0.6 else (22.5, 29.5))
    y = GA.calm_base(T, sn, n, 144, end)
    if y is None:
        return None
    s0 = GA.s0_of(sn.card, y[-n:])
    r = GA.target_amp(sn.card, y, n, "gradual_decrease", d, s0, tgt, rng, T)
    if r is None:
        return None
    y2, extra, sz = r
    row = finish(T, sn, y2, n, end, "hard_leak", "early_leak_" + tgt, "gradual_decrease", extra, "stage_40min",
                 ["hard", "leak_early", "water_hole"])
    g = row["gold"]
    if g["pattern"] != "gradual_decrease" or (tgt == "warning" and g["status"] != "warning"):
        return None
    return row


def gen_night(T):
    rng = T.rng
    sn = T.sensor_for("occupancy")
    if sn is None:
        return None
    NF["n"] = pick_win(rng)
    want = rng.choice(("off_hours_presence", "off_hours_presence", "off_hours_presence", "flapping", None))
    r = GA.gen_occ_row(T, sn, "hard_night", want=want)
    if not r or r["n"] != NF["n"]:
        return None
    g = r["gold"]
    if want == "off_hours_presence" and (g["pattern"] != "off_hours_presence" or g["status"] == "sensor_fault"):
        return None
    return tag(r, "hard_night", "v2-night", ["hard", "night_presence"])


LONE = ("throttling", "step_increase", "step_decrease", "throttling", "gradual_increase", "oscillation")


def gen_plateau(T):
    """lone plateau / lone step inside the card limits and max_step: a real event, never sensor_fault (second evidence kind missing)"""
    rng = T.rng
    sn = T.sensor_for(GA.wchoice(rng, GA.EX_W))
    if sn is None:
        return None
    if rng.random() < 0.4:
        sn.card = GA._jit(sn.card, rng)
    NF["n"] = pick_win(rng)
    p = rng.choice(LONE)
    tg = rng.choices(("normal", "warning", "critical"), weights=(30, 35, 35))[0]
    r = GA.gen_event_row(T, sn, "hard_plateau", p, tg, young=rng.random() < 0.3)
    if not r or r["n"] != NF["n"] or r["gold"]["status"] == "sensor_fault":
        return None
    return tag(r, "hard_plateau", "v2-plat", ["hard", "lone_" + p])


def wide_jit(card, rng):
    c = copy.deepcopy(card)
    c["rules"].pop("jittered", None)
    return CD.jitter_card(c, rng, frac=rng.choice((0.25, 0.35, 0.45)))


def gen_limits(T):
    rng = T.rng
    lim = [c for c in GA.EX_W if GA.EC[c]["warning"] is not None]
    sn = T.sensor_for(rng.choice(lim))
    if sn is None:
        return None
    sn.card = wide_jit(sn.card, rng)
    NF["n"] = pick_win(rng)
    d = sn.card["warning"]["dir"]
    up = ("spike", "step_increase", "gradual_increase", "exponential_increase", "throttling")
    dn = ("dip", "step_decrease", "gradual_decrease")
    p = rng.choice(up if d == "high" else dn if d == "low" else up + dn)
    tg = rng.choice(("normal", "warning", "warning", "critical"))
    r = GA.gen_event_row(T, sn, "hard_limits", p, tg, young=rng.random() < 0.2)
    if not r or r["n"] != NF["n"]:
        return None
    return tag(r, "hard_limits", "v2-lim", ["hard", "card_edited"])


def gen_ph(T):
    """rare cadence: one fresh reading every k samples (30-120 min), values held between (GAPS line, like dq_edge rows)"""
    rng = T.rng
    sn = T.sensor_for("water_ph")
    if sn is None:
        return None
    n = rng.choice((36, 48, 48, 96, 144))
    end = GA.end_at(rng, T.split)
    y = GA.calm_base(T, sn, n, 144, end)
    if y is None:
        return None
    card = sn.card
    s0 = GA.s0_of(card, y[-n:])
    k = rng.choice((6, 12, 12, 18, 24))
    ph = rng.randrange(k)
    mask = [(i % k) != ph for i in range(144)]
    p, extra = "stable", {"size": None, "d": None, "onset_idx": None}
    if rng.random() < 0.4:
        pp = rng.choice(("gradual_increase", "gradual_decrease", "step_increase", "step_decrease"))
        r = GA.target_amp(card, y, n, pp, rng.randint(max(6, k), n), s0, rng.choice(("normal", "warning", "critical")), rng, T)
        if r:
            y, extra, _ = r
            p = pp
    y = SM.hold_missing(y, mask)
    y = GA.clamp(y, card)
    extra["missing_mask"] = mask[-n:]
    return finish(T, sn, y, n, end, "hard_ph", "rare_cadence_%dmin" % (k * 5), p, extra, "stage_3h",
                  ["hard", "rare_cadence", "data_quality"], missing=mask)


def gen_weak(T):
    """roles weak in the v1 selection: power / water events + faults, and calm rows that are stable (not oscillation)"""
    rng = T.rng
    NF["n"] = pick_win(rng)
    k = rng.choices(("power_event", "water_event", "power_fault", "water_fault", "calm_texture"), weights=(30, 25, 12, 12, 21))[0]
    if k.endswith("event"):
        cid = rng.choice(("power_load", "power_load", "power_solar", "power_pf")) if k == "power_event" else \
            rng.choice(("tank_level", "tank_level", "water_flow", "water_tds", "water_ph"))
        sn = T.sensor_for(cid)
        if sn is None:
            return None
        if rng.random() < 0.4:
            sn.card = GA._jit(sn.card, rng)
        tg = rng.choices(("normal", "warning", "critical"), weights=(25, 40, 35))[0]
        r = GA.gen_event_row(T, sn, "weak_" + k, None, tg, young=rng.random() < 0.15)
    elif k.endswith("fault"):
        cid = rng.choice(("power_load", "power_solar", "power_pf")) if k == "power_fault" else \
            rng.choice(("tank_level", "water_flow", "water_tds", "water_ph"))
        sn = T.sensor_for(cid)
        if sn is None:
            return None
        r = GA.gen_fault_row(T, sn, "weak_" + k)
    else:
        sn = T.sensor_for(GA.wchoice(rng, GA.EX_W))
        if sn is None:
            return None
        r = GA.gen_stable_row(T, sn, "weak_calm_texture", ("calm_or_routine", "calm", "texture"))
    if not r or r["n"] != NF["n"]:
        return None
    return tag(r, "weak_" + k, "v2-weak", ["weak_role"])


FAMS = {"dyn": gen_dyn, "hard_standby": gen_standby, "hard_leak": gen_leak, "hard_night": gen_night, "hard_plateau": gen_plateau,
        "hard_limits": gen_limits, "hard_ph": gen_ph, "weak": gen_weak}
