"""agt_v3 dataset generator (V3_DESIGN §4.2). Synthetic windows only (simulator calibrated on aggregate stats).

  python3 gen_agt.py --out DIR [--scale 1.0] [--procs 6] [--only SPLIT]
Splits: train (6,000 train sites), dev (300 dev sites), test_unseen_layout (400 test sites, held-out motifs),
test_unseen_metric (8 reserved metric types on test sites), test_campus (provisional IIITH tree, real sensor names),
calm_fault (calm-looking faults on test sites). Every row: id, split, family, sub, role, stage, slices, card, site
fields, hist, n, end_epoch, prompt, completion, gold, meta, pair_id, synthetic, source.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import sys
import time
import traceback
from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "core"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(HERE))
import evidence as EV  # noqa: E402
import cards as CD  # noqa: E402
import sitegraph as ST  # noqa: E402
import sim as SM  # noqa: E402
import teacher_v3 as TV  # noqa: E402
import features as F  # noqa: E402
import features_v2 as V  # noqa: E402
import generate_dataset as G  # noqa: E402
import teacher_v2 as TE  # noqa: E402
import hvac as HV  # noqa: E402

IST = V.IST
EC = CD.existing_cards()
NODE_LIMITS = json.loads((ST.APPDATA / "node_limits_v2.json").read_text())
MONTHS = {"train": range(1, 9), "dev": (9, 10), "test": (11, 12)}
SITES = {"train": 6000, "dev": 300, "test": 400}
EX_W = {"co2_indoor": 12, "temp_indoor": 7, "rh_indoor": 6, "pm25_outdoor": 5, "pm10_outdoor": 4, "pm25_indoor": 3,
        "tank_level": 10, "water_flow": 6, "water_tds": 4, "water_ph": 5, "power_load": 12, "power_solar": 4, "power_pf": 5,
        "weather_temp": 6, "weather_rh": 4, "weather_wind": 4}
EVENT_PATTERNS = ("spike", "dip", "gradual_increase", "gradual_decrease", "step_increase", "step_decrease",
                  "exponential_increase", "oscillation", "throttling", "erratic")
DMIN = {"gradual_increase": 6, "gradual_decrease": 6, "exponential_increase": 6, "oscillation": 8, "throttling": 16, "erratic": 6}
STAGES = ("stage_40min", "stage_1.5h", "stage_3h")

# family plan (train rows); shares from V3_DESIGN §4.2
PLAN = OrderedDict([
    ("ex_stable", 3500), ("ex_event", 10400), ("ex_fault", 5200), ("ex_longrange", 1500), ("ex_occupancy", 1400), ("ex_hvac", 2000),
    ("hole_power", 2800), ("hole_water", 2400), ("hole_calm_fault", 2000), ("hole_recall", 1400),
    ("calm_routine", 6700), ("unseen_metric", 7200), ("dq_edge", 1500)])
SPLIT_N = {"dev": 600, "test_unseen_layout": 600, "test_campus": 600, "test_unseen_metric": 300, "calm_fault": 300}


# --------------------------------------------------------------------------------------------- helpers
JX = float(os.environ.get("AGT_JX", "0"))   # extra card-jitter probability for existing cards (train only)


def _jit(card, rng):
    """jitter once: a card already jittered by sensor_for (AGT_JX) is not moved again"""
    return card if card["rules"].get("jittered") else CD.jitter_card(card, rng)


def wchoice(rng, d):
    ks = list(d)
    return rng.choices(ks, weights=[d[k] for k in ks])[0]


def date_in(rng, split):
    m = rng.choice(list(MONTHS["train" if split == "train" else "dev" if split == "dev" else "test"]))
    d = rng.randint(1, 28)
    return datetime(2026, m, d, tzinfo=IST)


def end_at(rng, split, hours=None, workday=None, cal=None):
    for _ in range(40):
        day = date_in(rng, split)
        h = rng.uniform(*hours) if hours else rng.uniform(0, 24)
        h %= 24
        e = int((day + timedelta(hours=int(h), minutes=5 * int((h % 1) * 12))).timestamp())
        e -= e % 300
        if workday is None or cal is None or cal.is_workday(e) == workday:
            return e
    return e


def pick_n(rng, fam, p=None, stage=None):
    stage = stage or rng.choice(STAGES)
    if stage == "stage_40min":
        n = 48
    else:
        wf = "flat" if p in ("flatline",) or fam in ("fault",) else "spike" if p in ("spike", "dip") else "trend"
        n = {"flat": 144, "spike": 96, "trend": 48}[wf]
        if rng.random() < 0.35:
            n = rng.choice(V.LENGTHS)
    return n, stage


def s0_of(card, xs):
    key = CD.metric_key(card)
    sc, _ = G.scale_of(key[0], key[1], xs)
    return sc


def pcalm(card, xs):
    key = CD.metric_key(card)
    n = len(xs)
    ends = list(range(n, 47, -48)) if n > 48 else [n]
    if n > 48 and ends[-1] != 48:
        ends.append(48)
    return all(G.is_calm(key[0], key[1], xs[max(0, e - 48):e]) for e in ends)


def clamp(y, card, keep=()):
    lo, hi = sensor_range(card)
    return [v if i in keep else min(hi, max(lo, v)) for i, v in enumerate(y)]


def sensor_range(card):
    key = CD.metric_key(card)
    m = F.METRICS[key]
    imp = card.get("impossible") or {}
    lo = imp.get("below") if imp.get("below") is not None else m["lo"]
    hi = imp.get("above") if imp.get("above") is not None else m["hi"]
    return lo, hi


def place_of(ix, host):
    n = ix.nodes[host]
    if n["kind"] in ("room", "zone"):
        if n.get("capacity"):
            return f"{n['use'].replace('_', ' ')}, capacity {n['capacity']}"
        return n["use"].replace("_", " ")
    if n["kind"] == "equipment":
        return {"tank": f"{n.get('tank_kind', 'water')} tank", "ac_unit": "AC unit", "pump": "pump", "panel": "electrical panel",
                "feeder": "feeder", "weather_station": "weather station", "meter": "meter", "ahu": "AHU", "chiller": "chiller"}.get(n["etype"], n["etype"])
    return None


def location_of(ix, host):
    p = [ix.name(x) for x in ix.path(host)[1:]]
    return ", ".join(p) if p else ix.name(host)


def tank_for(node_id):
    r = random.Random("tank-" + node_id)
    high = float(round(r.uniform(60, 420) * 2) / 2)
    return {"high": high, "overflow": float(round(high * r.uniform(1.06, 1.25))), "fill_min": r.choice((30, 35, 45, 60, 80, 90, 120, 125))}


class Sensor:
    def __init__(self, site, ix, sid, card, device, host, location=None):
        self.site, self.ix, self.sid, self.card, self.device, self.host = site, ix, sid, card, device, host
        self.location = location or location_of(ix, host)
        self.place = place_of(ix, host)
        hn = ix.nodes[host]
        self.use = hn.get("use", "plant_room" if hn["kind"] == "equipment" else "office")
        self.cap = hn.get("capacity", 0) or 0


# --------------------------------------------------------------------------------------------- task context
class Task:
    def __init__(self, split, fam, k, count, seed):
        self.split, self.fam, self.k, self.count = split, fam, k, count
        self.rng = random.Random(f"{seed}-{split}-{fam}-{k}")
        self.site_split = {"train": "train", "dev": "dev"}.get(split, "test")
        self.cache = OrderedDict()
        npool = SITES[self.site_split]
        span = max(30, npool * count // max(1, sum(PLAN.values()) if split == "train" else count))
        self.pool = [self.rng.randrange(npool) for _ in range(min(npool, 60))]
        self.cal = SM.Calendar(f"{split}-{k}")
        self.used_sites = Counter()

    def site(self):
        if self.split == "test_campus":
            if "campus" not in self.cache:
                s = ST.campus_site()
                self.cache["campus"] = (s, ST.Index(s))
            return self.cache["campus"]
        seed = self.rng.choice(self.pool)
        if seed not in self.cache:
            s = ST.gen_site(seed, self.site_split)
            self.cache[seed] = (s, ST.Index(s))
            if len(self.cache) > 12:
                self.cache.popitem(last=False)
        self.used_sites[seed] += 1
        return self.cache[seed]

    def sensor_for(self, card_id, synthetic_type=None):
        """Sensor of the wanted card (existing) or a new synthetic-type sensor on a suitable host."""
        for _ in range(8):
            site, ix = self.site()
            if synthetic_type:
                hosts = [n["id"] for n in site["nodes"] if n["kind"] in ("room", "equipment") and n.get("etype") != "weather_station"]
                h = self.rng.choice(hosts)
                cap = ix.nodes[h].get("capacity") or None
                card = CD.synthetic_card(synthetic_type, self.rng, capacity=cap)
                EV.register(card)
                dev = f"{''.join(self.rng.choice('ABCDEFGHJKLMNPRSTUVWXYZ') for _ in range(2))}-{synthetic_type[:3].upper()}-{self.rng.randrange(10, 99)}"
                if site.get("naming") == "hindi":
                    dev = f"{dev.lower()}-yantra"
                return Sensor(site, ix, f"{dev}/{synthetic_type}", card, dev, h)
            cands = [n for n in site["nodes"] if n["kind"] == "sensor" and n["card"] == card_id]
            if not cands:
                continue
            nd = self.rng.choice(cands)
            card = copy.deepcopy(EC[card_id])
            if card_id == "tank_level":
                tl = NODE_LIMITS.get(nd["device"]) if self.split == "test_campus" else None
                card["tank"] = {k: tl[k] for k in ("high", "overflow", "fill_min")} if tl else tank_for(nd["id"])
            loc = nd.get("location") if self.split == "test_campus" else None
            if self.split == "train" and JX > 0 and self.rng.random() < JX:   # 2026-11-13 owner: card jitter 30 %
                card = CD.jitter_card(card, self.rng)
            return Sensor(site, ix, nd["id"], card, nd["device"], nd["parent"], loc)
        return None


# --------------------------------------------------------------------------------------------- one continuous row
def base_series(T, sn, n, H, end, events=(), params=None):
    warm = 24
    drv = SM.Drivers(f"{T.split}-{sn.sid}", end - (H + warm - 1) * 300, H + warm, sn.use, sn.cap, T.cal, events=events)
    y = SM.channel(sn.card, drv, T.rng, **(params or {}))[warm:]
    return [round(v, 4) for v in y], drv


def calm_base(T, sn, n, H, end):
    y, drv = base_series(T, sn, n, H, end)
    if not pcalm(sn.card, y[-n:]):
        y = SM.calm_ify(y)
        lo, hi = sensor_range(sn.card)
        y = [min(hi, max(lo, v)) for v in y]
        if not pcalm(sn.card, y[-n:]):
            return None
    return y


def inject_event(T, card, y, n, p, d, A, rng):
    """v2 injections (generate_v2 inj_*), hist coordinates. Returns (y, extra) or None."""
    H = len(y)
    o = H - d
    ow = n - d
    extra = {"d": d, "onset_idx": ow}
    if p in ("spike", "dip"):
        w = min(rng.randint(1, 3), d)
        for i in range(o, min(H, o + w)):
            y[i] += (1 if p == "spike" else -1) * A * (1.0 if i == o + w // 2 else 0.7)
        extra.update(active=o + w - 1 >= H - 1, w=w)
    elif p in ("step_increase", "step_decrease"):
        ms = card.get("max_step")
        r = 1 if not ms or A <= 0.8 * ms else int(math.ceil(A / (0.8 * ms)))
        if r > max(1, d - 2):
            return None
        for i in range(o, H):
            y[i] += (1 if p == "step_increase" else -1) * A * min(1.0, (i - o + 1) / r)
        extra["ramp"] = r
    elif p in ("gradual_increase", "gradual_decrease"):
        L = H - o
        for i in range(o, H):
            y[i] += (1 if p == "gradual_increase" else -1) * A * (i - o + 1) / L
    elif p == "exponential_increase":
        L = H - o
        r = rng.uniform(3.0, 5.0)
        for i in range(o, H):
            y[i] += A * 1.4 * (math.exp(r * (i - o + 1) / L) - 1) / (math.exp(r) - 1)
    elif p == "oscillation":
        P = rng.uniform(8, 16)
        if d < P:
            return None
        ph = rng.uniform(0, 2 * math.pi)
        for i in range(o, H):
            y[i] += A / 2 * math.sin(2 * math.pi * (i - o) / P + ph)
    elif p == "throttling":
        if d < 16:
            return None
        top = rng.randint(10, min(22, d - 4))
        rise = max(1, H - top - o)
        for i in range(o, H):
            y[i] += min(A * (i - o + 1) / rise, A)
        capv = max(y[H - top:])
        s0 = A / 6
        for i in range(H - top, H):
            y[i] = capv - abs(rng.gauss(0, 0.05 * s0))
    elif p == "erratic":
        s0 = A / 4
        for i in range(o, H):
            if rng.random() < 0.45:
                y[i] += rng.gauss(0, s0 * rng.uniform(3, 6))
    return y, extra


def quick_status(card, p, xs):
    st = F.compute_stats(xs, card["decimals"])
    if card["warning"] is not None:
        return TV.status_limits(card, p, st)[0]
    if card.get("rate_rules"):
        return TV.status_rate(card, p, st, xs)[0]
    return "normal"


def target_amp(card, y, n, p, d, s0, target, rng, T):
    """Amplitude (x s0) search so the shape lands on the target status. Returns (y2, extra, size) or None."""
    sizes = [TV.TE.BOUNDARY + 0.2 + rng.random() * 10]
    if target and card["warning"] is not None and card["warning"]["dir"] != "both" and p not in ("oscillation", "erratic"):
        w, c = card["warning"]["at"], card["critical"]["at"]
        hi = card["warning"]["dir"] == "high"
        ref = y[-1] if p not in ("spike", "dip", "throttling") else y[len(y) - d]
        lim_tgt = {"normal": (w - (w - ref) * rng.uniform(0.2, 0.9)) if (w - ref) * (1 if hi else -1) > 0 else None,
                   "warning": w + (c - w) * rng.uniform(0.05, 0.9), "critical": c + abs(c - w) * rng.uniform(0.05, 1.5)}.get(target)
        if lim_tgt is not None:
            A = (lim_tgt - ref) * (1 if (p in TV.UP or p == "spike") else -1)
            if p == "exponential_increase":
                A /= 1.4
            if A > 0:
                sizes = [A / s0] + sizes
    elif target and card.get("rate_rules") and p not in ("oscillation",):
        rr = card["rate_rules"]
        base = abs(sum(y[-n:][:12]) / 12) or 1.0
        rel = {"normal": rr["gradual_warn"] * rng.uniform(0.3, 0.9) if p in ("gradual_increase", "gradual_decrease") else None,
               "warning": (rr["gradual_warn"] * rng.uniform(1.1, 3.0) if p in ("gradual_increase", "gradual_decrease")
                           else rr["abrupt_crit"] * rng.uniform(0.3, 0.92) if rr["abrupt_warn"] <= 0
                           else rng.uniform(rr["abrupt_warn"] * 1.1, rr["abrupt_crit"] * 0.92)),
               "critical": (rr["abrupt_crit"] * rng.uniform(1.08, 2.5)) if p in TV.ABRUPT else None}.get(target)
        if rel is not None:
            sizes = [rel * base / s0] + sizes
    for sz in sizes:
        if sz <= 0 or sz > 400:
            continue
        y2 = list(y)
        r = inject_event(T, card, y2, n, p, d, sz * s0, rng)
        if r is None and p in ("step_increase", "step_decrease") and card.get("max_step"):
            d2 = min(n, int(math.ceil(sz * s0 / (0.8 * card["max_step"]))) + 3)
            y2 = list(y)
            r = inject_event(T, card, y2, n, p, d2, sz * s0, rng)
        if r is None:
            continue
        y2, extra = r
        y2 = clamp(y2, card)
        extra["size"] = sz if p not in ("erratic",) else None
        return y2, extra, sz
    return None


def finish_cont(T, sn, y, n, end, fam, sub, p, extra, stage, slices, missing=None):
    """Render prompt + gold; reject rows with unintended impossible values or failed shape checks."""
    card = sn.card
    y = [round(v, 4) for v in y]
    xs = y[-n:]
    win_missing = (missing or [False] * len(y))[-n:] if missing else None
    if win_missing and not any(win_missing):
        win_missing = None
    user, st, ev, info = EV.agent_user(card, sn.device, sn.location, y[-V.HIST:], n, end, place=sn.place, missing=win_missing)
    ow = extra.get("onset_idx")
    if p == "spike" and ow is not None and not (ow <= st["max_idx"] < ow + extra.get("w", 1)) and not extra.get("size_small"):
        return None
    if p == "dip" and ow is not None and not (ow <= st["min_idx"] < ow + extra.get("w", 1)):
        return None
    if p in ("step_increase", "step_decrease") and ow is not None and not (ow - 1 <= st["max_jump_idx"] <= ow + extra.get("ramp", 1)):
        return None
    if p == "throttling" and st["plateau_run"] < 6:
        return None
    if p == "oscillation" and st["zero_cross"] < 4 and (extra.get("size") or 9) >= 3:
        return None
    if extra.get("fault_hint") not in ("impossible", "impossible_glitch") and TV.impossible_idx(card, xs):
        return None
    ms = card.get("max_step")
    if ms and extra.get("fault_hint") is None and abs(st["max_jump_signed"]) > ms:
        return None  # card rule: a 5-min change above max_step is always a data fault; keep process rows below it
    ex = dict(extra, card=card, pattern=p, family=fam, xs=xs, hist=y, n=n, end=end, st=st, info=info, rng=T.rng,
              missing=win_missing, zero=extra.get("zero", False))
    tgt, meta = TV.label(ex)
    return make_row(T, sn, y, n, end, fam, sub, stage, slices, user, tgt, meta, extra)


def make_row(T, sn, y, n, end, fam, sub, stage, slices, user, tgt, meta, extra, hvac_ctx=None):
    card = sn.card
    prompt = F.llama3_prompt(EV.agent_system(card, n), user)
    comp = json.dumps(tgt, ensure_ascii=False) + "<|eot_id|>"
    rid = hashlib.sha1(prompt.encode()).hexdigest()[:12]
    sl = list(slices) + [stage, f"family_{fam}"]
    if extra.get("d") is not None and 3 <= extra["d"] <= 7:
        sl.append("young_k")
    row = {"id": f"{T.split}-{fam}-{rid}", "split": T.split, "family": fam, "sub": sub, "role": card["domain"],
           "stage": stage.replace("stage_", ""), "slices": sl, "card_id": card["card_id"], "card_type": card["rules"].get("type"),
           "card_synthetic": bool(card["rules"].get("synthetic")), "jittered": bool(card["rules"].get("jittered")),
           "card": card, "site_id": sn.site["site_id"], "naming": sn.site.get("naming"), "motifs": sn.site.get("motifs"),
           "sensor": sn.sid, "node": sn.device, "location": sn.location, "host": sn.host, "place": sn.place,
           "site_path": sn.ix.path_text(sn.host, include_self=True),
           "n": n, "hist_len": len(y[-V.HIST:]), "end_epoch": end, "hist": [round(v, 4) for v in y[-V.HIST:]],
           "d": extra.get("d"), "size": round(extra["size"], 2) if extra.get("size") else None,
           "prompt": prompt, "completion": comp, "gold": tgt, "meta": meta,
           "synthetic": True, "source": "synthetic_sim" if T.split != "test_campus" else "campus_tree_sim"}
    if hvac_ctx is not None:
        row["hvac_ctx"] = {k: hvac_ctx[k] for k in ("sp", "on", "thermo", "occ", "duty", "hour_on", "mode", "alarm", "malf", "missing")}
    if meta.get("missing_frac"):
        row["missing"] = extra.get("missing_mask")
    row["pair_id"] = row["id"]
    return row


# --------------------------------------------------------------------------------------------- families
def gen_event_row(T, sn, fam, sub=None, target=None, stage=None, slices=(), young=False):
    rng = T.rng
    p = sub or rng.choice(EVENT_PATTERNS)
    if p == "erratic" and sn.card["rules"].get("erratic_fault", True):
        p = rng.choice(EVENT_PATTERNS[:-1])
    n, stage = pick_n(rng, "event", p, stage)
    if n < DMIN.get(p, 3):
        n = 48
    H = 144 if rng.random() < 0.75 else rng.randint(n, 144)
    end = end_at(rng, T.split)
    y = calm_base(T, sn, n, H, end)
    if y is None:
        return None
    dmin = DMIN.get(p, 3)
    d = rng.randint(3, 7) if young else TE_sample_d(rng, n, dmin)
    d = max(d, dmin)
    s0 = s0_of(sn.card, y[-n:])
    r = target_amp(sn.card, y, n, p, d, s0, target, rng, T)
    if r is None:
        return None
    y2, extra, sz = r
    return finish_cont(T, sn, y2, n, end, fam, p, p, extra, stage, slices)


def TE_sample_d(rng, n, dmin=3):
    d = rng.randint(4, 12) if rng.random() < 0.35 else rng.randint(3, n)
    return max(dmin, min(n, d))


def gen_stable_row(T, sn, fam="ex_stable", slices=("calm_or_routine", "calm")):
    rng = T.rng
    n, stage = pick_n(rng, "stable")
    H = 144 if rng.random() < 0.75 else rng.randint(n, 144)
    end = end_at(rng, T.split)
    y = calm_base(T, sn, n, H, end)
    if y is None:
        return None
    return finish_cont(T, sn, y, n, end, fam, "stable", "stable", {"size": None, "d": None, "onset_idx": None}, stage, slices)


FAULTS = {"stuck": 3, "bias": 1.5, "drift": 1, "noise": 2, "dropout": 1.5, "saturation": 1, "quantised": 1.5, "impossible": 1.2}


def fault_ok(card, kind):
    imp = card.get("impossible") or {}
    if kind == "bias":
        return bool(card.get("max_step"))
    if kind == "drift":
        return bool(card["rules"].get("drift_fault"))
    if kind == "noise":
        return card["rules"].get("erratic_fault", True)
    if kind == "dropout":
        return imp.get("below") is not None and imp["below"] > 0 or not card["rules"].get("zero_ok", False) and imp.get("below") == 0 and False
    if kind == "saturation":
        return "saturation" in card["faults"] and imp.get("above") is not None and imp["above"] < 1e5
    if kind == "impossible":
        return imp.get("below") is not None or imp.get("above") is not None
    return kind in card["faults"] or kind in ("stuck",)


def gen_fault_row(T, sn, fam, kind=None, slices=("fault",), plausible=False):
    rng = T.rng
    kinds = {k: w for k, w in FAULTS.items() if fault_ok(sn.card, k)}
    kind = kind if kind and kind in kinds else wchoice(rng, kinds)
    n, stage = pick_n(rng, "fault", "flatline")
    H = 144
    if kind == "drift":
        end = end_at(rng, T.split, hours=(22, 29.9))
    else:
        end = end_at(rng, T.split)
    y = calm_base(T, sn, n, H, end)
    if y is None:
        return None
    card = sn.card
    s0 = s0_of(card, y[-n:])
    dmin = {"stuck": 12, "noise": 6, "saturation": 8, "quantised": 12, "dropout": 3, "bias": 3}.get(kind, 3)
    d = max(dmin, TE_sample_d(rng, n, dmin))
    o = len(y) - d
    keep = set()
    extra = {"size": None, "d": d, "onset_idx": n - d, "fault_hint": kind}
    base_flat = F.compute_stats(y[-n:], card["decimals"])["flat_run"]
    if kind == "stuck":
        p = "flatline"
        y = [y[i] if i < o else y[o] for i in range(len(y))]
        if abs(y[o]) < 1e-6:
            return None
    elif kind == "bias":
        ms = card["max_step"]
        A = max(1.6 * ms, rng.uniform(5, 12) * s0) * rng.choice((1, -1))
        if plausible:
            A = math.copysign(ms * rng.uniform(1.15, 1.8), A)
        p = "step_increase" if A > 0 else "step_decrease"
        y = [v + (A if i >= o else 0) for i, v in enumerate(y)]
        extra["ramp"] = 1
    elif kind == "drift":
        A = rng.uniform(12, 20) * s0 * rng.choice((1, -1))
        p = "gradual_increase" if A > 0 else "gradual_decrease"
        Hn = len(y)
        y = [v + A * i / (Hn - 1) for i, v in enumerate(y)]
        extra.update(d=Hn, onset_idx=n - Hn, onset_time=V.idx_time(end, Hn, 0))
    elif kind == "noise":
        p = "erratic"
        mult = rng.uniform(2.0, 4.0)
        y = [v + (rng.gauss(0, s0 * mult) if i >= o else 0) for i, v in enumerate(y)]
    elif kind == "dropout":
        k = rng.randint(1, 4)
        idx = sorted(rng.sample(range(o, len(y)), min(k, d)))
        if len(idx) >= 2 and max(idx) - min(idx) < 3:
            return None
        p = "dip" if len(idx) == 1 else "erratic"
        for i in idx:
            y[i] = 0.0
            keep.add(i)
        extra.update(active=idx[-1] == len(y) - 1, w=1, fault_hint="impossible")
    elif kind == "saturation":
        p = "throttling"
        rail = card["impossible"]["above"]
        r = rng.randint(3, max(3, min(12, d - 4)))
        start = y[o]
        for i in range(o, len(y)):
            f = min(1.0, (i - o + 1) / r)
            y[i] = rail if f >= 1 else start + (rail - start) * f
            if y[i] >= rail:
                keep.add(i)
    elif kind == "quantised":
        p = "flatline"
        q = rng.uniform(3, 6) * s0
        y = [round(v / q) * q if i >= o else v for i, v in enumerate(y)]
    elif kind == "impossible":
        imp = card["impossible"]
        lo = imp.get("below")
        if lo is not None and lo > 0 and (imp.get("above") is None or rng.random() < 0.7):
            v = lo * rng.uniform(0.3, 0.92)
            p = "step_decrease"
        elif imp.get("above") is not None and imp["above"] < 1e5:
            v = imp["above"] * rng.uniform(1.05, 1.4)
            p = "step_increase"
        else:
            return None
        for i in range(o, len(y)):
            y[i] = v + rng.gauss(0, (card.get("noise") or 0) * 0.3)
            keep.add(i)
        extra["ramp"] = 1
    y = clamp(y, card, keep)
    xs = y[-n:]
    st = F.compute_stats(xs, card["decimals"])
    if kind == "stuck" and st["flat_run"] < max(12, base_flat + 6):
        return None
    if kind == "quantised" and st["flat_run"] < 6:
        return None
    if kind == "saturation" and st["plateau_run"] < 3:
        return None
    if kind == "bias" and not (st["max_jump_idx"] == n - d and abs(st["max_jump_signed"]) > card["max_step"]):
        return None
    if kind == "drift" and "slow_drift" not in {f["kind"] for f in (V.long_view(*CD.metric_key(card), y[-144:]) or [])}:
        return None
    if kind == "drift":
        p_cls = p
    return finish_cont(T, sn, y, n, end, fam, kind, p, extra, stage, list(slices) + ["sensor_fault", f"fault_{kind}"])


def gen_longrange_row(T, sn, fam="ex_longrange"):
    rng = T.rng
    kind = rng.choice(("old_shift", "long_drift", "recurring"))
    n = rng.choice((24, 30, 36, 48, 60, 72))
    stage = rng.choice(STAGES)
    end = end_at(rng, T.split)
    y = calm_base(T, sn, n, 144, end)
    if y is None:
        return None
    card = sn.card
    s0 = s0_of(card, y[-n:])
    H = len(y)
    if kind == "old_shift":
        d = rng.randint(n + 6, H - 40)
        A = rng.uniform(6, 14) * s0
        sgn = rng.choice((1, -1))
        p = "step_increase" if sgn > 0 else "step_decrease"
        o = H - d
        y = [v + (sgn * A if i >= o else 0) for i, v in enumerate(y)]
        extra = {"size": A / s0, "d": d, "onset_idx": n - d, "ramp": 1}
        p_win = "stable"
    elif kind == "long_drift":
        A = rng.uniform(8, 14) * s0 * rng.choice((1, -1))
        y = [v + A * i / (H - 1) for i, v in enumerate(y)]
        p_win = "gradual_increase" if A > 0 else "gradual_decrease"
        extra = {"size": abs(A) / s0, "d": H, "onset_idx": n - H, "onset_time": V.idx_time(end, H, 0)}
    else:
        k = rng.randint(3, 6)
        idxs = sorted(rng.sample(range(10, H - 3), k))
        for i in idxs:
            y[i] += rng.uniform(4, 7) * s0
        last = idxs[-1]
        p_win = "spike" if last >= H - n else "stable"
        extra = {"size": None, "d": H - last, "onset_idx": n - (H - last), "active": last >= H - 2, "window_spike": last >= H - n}
        fam_l = "recurring"
    y = clamp(y, card)
    famx = {"old_shift": "old_shift", "long_drift": "long_drift", "recurring": "recurring"}[kind]
    row = finish_lr(T, sn, y, n, end, fam, famx, p_win, extra, stage)
    return row


def finish_lr(T, sn, y, n, end, fam, famx, p, extra, stage):
    card = sn.card
    y = [round(v, 4) for v in y]
    user, st, ev, info = EV.agent_user(card, sn.device, sn.location, y[-V.HIST:], n, end, place=sn.place)
    if TV.impossible_idx(card, y[-n:]):
        return None
    if card.get("max_step") and abs(st["max_jump_signed"]) > card["max_step"]:
        return None
    ex = dict(extra, card=card, pattern=p, family=famx, xs=y[-n:], hist=y, n=n, end=end, st=st, info=info, rng=T.rng)
    tgt, meta = TV.label(ex)
    return make_row(T, sn, y, n, end, fam, famx, stage, ["longrange", famx], user, tgt, meta, extra)


def gen_occ_row(T, sn, fam="ex_occupancy", want=None):
    rng = T.rng
    n, stage = pick_n(rng, "occ")
    hours = {"off_hours_presence": (22, 29.5), "vacant": (0, 24), "arrival": (8, 11), "departure": (16, 20)}.get(want, (0, 24))
    end = end_at(rng, T.split, hours=hours)
    events = ("night_presence",) if want == "off_hours_presence" else ()
    y, drv = base_series(T, sn, n, 144, end, events=events)
    y = [1.0 if v >= 0.5 else 0.0 for v in y]
    if want == "flapping" or (want is None and rng.random() < 0.08):
        o = len(y) - rng.randint(12, n)
        for i in range(o, len(y)):
            if rng.random() < 0.45:
                y[i] = 1.0 - y[i]
    xs = y[-n:]
    user, st, ev, info = EV.agent_user(sn.card, sn.device, sn.location, y, n, end, place=sn.place)
    ex = {"card": sn.card, "xs": xs, "end": end, "n": n, "info": info, "rng": rng, "family": fam}
    tgt, meta = TV.label(ex)
    if want and want != "flapping" and tgt["pattern"] != want:
        return None
    sl = ["occupancy"] + (["calm_or_routine", "routine"] if tgt["status"] == "normal" else [])
    return make_row(T, sn, y, n, end, fam, tgt["pattern"], stage, sl, user, tgt, meta, {"d": None})


HVAC_W = {p: 1.0 for p in HV.INJECTABLE}
for _p in ("stable", "normal_cycling", "pull_down", "setback_drift", "night_setback", "weekend_off", "continuous_duty",
           "fan_mode", "small_excursion", "setpoint_change_ok"):
    HVAC_W[_p] = 0.6


def hvac_base(T, sn, n, end, kind):
    rng = T.rng
    drv = SM.Drivers(f"{T.split}-{sn.sid}", end - (n - 1) * 300, n, "office", 10, T.cal)
    sp = rng.choice((22.0, 23.0, 24.0, 24.0, 25.0, 26.0))
    if kind == "on":
        xs = [round(sp + v, 2) for v in SM.ar_noise(n, 0.12, rng, 0.6)]
        on = [1] * n
    else:
        lvl = rng.uniform(25.5, 31.0)
        xs = [round(lvl + 0.4 * math.sin(i / 20) + v, 2) for i, v in enumerate(SM.ar_noise(n, 0.08, rng, 0.6))]
        on = [0] * n
    duty = rng.choice(("office", "office", "continuous", "idle")) if kind == "on" else rng.choice(("office", "office", "idle"))
    hon = [0.05] * 9 + [0.7] * 9 + [0.05] * 6 if duty == "office" else ([0.9] * 24 if duty == "continuous" else [0.02] * 24)
    ctx = {"sp": [sp] * n, "on": on, "thermo": None, "mode": 1, "alarm": [0] * n, "malf": 1, "missing": [False] * n,
           "occ": None if rng.random() < 0.5 else [1 if (v > 0.05) else 0 for v in drv.occ], "duty": duty, "hour_on": hon,
           "end": end, "node": sn.device}
    return xs, ctx


def gen_hvac_row(T, sn, fam="ex_hvac", want=None, slices=()):
    rng = T.rng
    p = want or wchoice(rng, HVAC_W)
    n = rng.choice((48, 48, 96, 144))
    n = max(n, HV.MIN_LEN.get(p, 0))
    n = min((L for L in (48, 96, 144) if L >= n), default=144)
    stage = {48: "stage_40min", 96: "stage_1.5h", 144: "stage_3h"}[n] if rng.random() < 0.7 else rng.choice(STAGES)
    end = end_at(rng, T.split)
    for kind in (rng.choice(("on", "off")), "on", "off"):
        xs, ctx = hvac_base(T, sn, n, end, kind)
        r = HV.make_case(p, xs, ctx, rng)
        if r:
            break
    else:
        return None
    ys, c2, lab = r
    lab.pop("_meta", None)
    lab.pop("_agrees", None)
    end2 = c2["end"]
    pre_n = rng.choice((0, 48, 96)) if rng.random() < 0.7 else 0
    pre = [round(ys[0] + v, 2) for v in SM.ar_noise(pre_n, 0.08, rng, 0.7)]
    hist = (pre + list(ys))[-144:]
    user, st, ev, info = EV.agent_user(sn.card, sn.device, sn.location, hist, n, end2, place=sn.place, hvac_ctx=c2)
    ex = {"card": sn.card, "xs": list(ys), "hvac_ctx": c2, "hvac_label": lab, "n": n, "rng": rng, "family": fam}
    tgt, meta = TV.label(ex)
    bad = HV_numbers_ok(tgt, user)
    if not bad:
        return None
    sl = ["hvac"] + list(slices) + (["calm_or_routine", "routine"] if tgt["status"] == "normal" else []) + \
        (["sensor_fault"] if tgt["status"] == "sensor_fault" else [])
    return make_row(T, sn, hist, n, end2, fam, p, stage, sl, user, tgt, meta, {"d": None}, hvac_ctx=c2)


def HV_numbers_ok(tgt, user):
    import re
    for o in tgt["observations"]:
        for num in re.findall(r"-?\d+(?:\.\d+)?", o.split("[")[0]):
            if num not in user:
                return False
    return True


# routines (calm negatives) for existing cards
def gen_routine_row(T, fam="calm_routine"):
    rng = T.rng
    kind = rng.choice(["co2_occ", "co2_decay", "tank_refill", "tank_day_drain", "pump_cycle", "power_startup", "power_shutdown",
                       "power_cycle", "power_holiday", "solar_day", "weather_diurnal_t", "weather_diurnal_rh", "ac_cycling",
                       "pm_outdoor", "occupancy", "hvac_normal", "flow_day"])
    slices = ["calm_or_routine", "routine", f"routine_{kind}"]
    if kind == "occupancy":
        sn = T.sensor_for("occupancy")
        return sn and gen_occ_row(T, sn, fam, want=rng.choice(("vacant", "arrival", "departure", "occupied", "intermittent")))
    if kind == "hvac_normal":
        sn = T.sensor_for("hvac_unit")
        return sn and gen_hvac_row(T, sn, fam, want=rng.choice(("normal_cycling", "pull_down", "setback_drift", "night_setback",
                                                                 "weekend_off", "continuous_duty", "fan_mode", "small_excursion",
                                                                 "setpoint_change_ok", "stable")), slices=slices[2:])
    spec = {"co2_occ": ("co2_indoor", ("gradual_increase", "step_increase"), (8.5, 19.5), True),
            "co2_decay": ("co2_indoor", ("gradual_decrease",), (0, 24), None),
            "tank_refill": ("tank_level", ("step_increase", "gradual_increase", "exponential_increase"), (0, 24), None),
            "tank_day_drain": ("tank_level", ("gradual_decrease",), (8, 19), None),
            "pump_cycle": ("tank_level", ("oscillation",), (7, 21), None),
            "flow_day": ("water_flow", ("oscillation",), (7, 21), None),
            "power_startup": ("power_load", ("step_increase",), (7.2, 10.4), True),
            "power_shutdown": ("power_load", ("step_decrease",), (17.2, 20.9), True),
            "power_cycle": ("power_load", ("oscillation",), (0, 24), None),
            "power_holiday": ("power_load", ("stable",), (9, 17), False),
            "solar_day": ("power_solar", ("gradual_increase", "gradual_decrease"), None, None),
            "weather_diurnal_t": ("weather_temp", ("gradual_increase", "gradual_decrease"), None, None),
            "weather_diurnal_rh": ("weather_rh", ("gradual_increase", "gradual_decrease"), None, None),
            "ac_cycling": ("temp_indoor", ("oscillation",), (9, 18), None),
            "pm_outdoor": ("pm25_outdoor", ("gradual_increase", "gradual_decrease", "step_increase", "oscillation"), (0, 24), None)}[kind]
    cid, pats, hours, workday = spec
    sn = T.sensor_for(cid)
    if sn is None:
        return None
    p = rng.choice(pats)
    if hours is None:  # diurnal / solar: rise in the morning, fall in the afternoon/evening
        inv = kind == "weather_diurnal_rh"
        rising = p == "gradual_increase"
        if kind == "solar_day":
            hours = (6.5, 11.9) if rising else (12.5, 18.9)
        else:
            hours = (7.5, 14.9) if rising != inv else (15.5, 30.5)
    n = rng.choice((24, 30, 36, 48)) if p != "oscillation" else rng.choice((48, 72, 96))
    stage = rng.choice(STAGES)
    for _ in range(4):
        end = end_at(rng, T.split, hours=hours, workday=workday, cal=T.cal)
        # the step must sit inside the routine window: put the onset so E5 time is in range
        y = calm_base(T, sn, n, 144, end)
        if y is None:
            continue
        s0 = s0_of(sn.card, y[-n:])
        if p == "stable":
            return finish_cont(T, sn, y, n, end, fam, kind, "stable", {"size": None}, stage, slices)
        if p in ("step_increase", "step_decrease") and kind.startswith("power"):
            d = rng.randint(3, min(n, 6))
        elif p == "oscillation":
            d = n
        else:
            d = rng.randint(max(DMIN.get(p, 3), n // 2), n)
        size = rng.uniform(4, 10)
        if kind == "pump_cycle" or kind == "flow_day":
            y2 = list(y)
            H = len(y2)
            P = rng.uniform(11, 20)
            for i in range(H - d, H):
                y2[i] += size * s0 / 2 * math.sin(2 * math.pi * (i - H + d) / P)
            extra = {"size": size, "d": d, "onset_idx": n - d}
        elif kind == "ac_cycling":
            y2 = list(y)
            H = len(y2)
            P = rng.uniform(8, 14)
            amp = min(0.9, size * s0 / 2)
            for i in range(H - d, H):
                y2[i] += amp * math.sin(2 * math.pi * (i - H + d) / P)
            extra = {"size": 2 * amp / s0, "d": d, "onset_idx": n - d}
        elif kind == "co2_occ":
            r = target_amp(sn.card, y, n, p, d, s0, "normal", rng, T)
            if r is None:
                continue
            y2, extra, _ = r
        else:
            r = inject_event(T, sn.card, list(y), n, p, d, size * s0, rng)
            if r is None:
                continue
            y2, extra = r
            extra["size"] = size
        y2 = clamp(y2, sn.card)
        row = finish_cont(T, sn, y2, n, end, fam, kind, p, extra, stage, slices)
        if row and row["meta"].get("routine"):
            return row
    return None


# --------------------------------------------------------------------------------------------- holes
def gen_hole_power(T):
    rng = T.rng
    cid = "power_load" if rng.random() < 0.85 else "power_solar"
    sn = T.sensor_for(cid)
    if sn is None:
        return None
    if rng.random() < 0.5:
        sn.card = _jit(sn.card, rng)
    tgt = rng.choice(("normal", "warning", "warning", "critical", "critical"))
    p = rng.choice(("spike", "dip", "step_increase", "step_decrease", "exponential_increase", "gradual_increase",
                    "gradual_decrease", "oscillation", "erratic", "throttling")) if tgt != "normal" else \
        rng.choice(("gradual_increase", "gradual_decrease", "oscillation", "stable"))
    if p == "stable":
        return gen_stable_row(T, sn, "hole_power", ("calm_or_routine", "calm", "power_boundary"))
    return gen_event_row(T, sn, "hole_power", p, tgt, slices=("power_boundary",))


def gen_hole_water(T):
    rng = T.rng
    k = rng.choice(("night_leak", "slow_day_leak", "overflow", "high", "valve", "supply_cut", "stuck_vs_drain", "flow_night_leak"))
    sl = ["water_hole", f"water_{k}"]
    if k == "flow_night_leak":
        sn = T.sensor_for("water_flow")
        if not sn:
            return None
        n = rng.choice((48, 96))
        end = end_at(rng, T.split, hours=(22.5, 29.5))
        y = calm_base(T, sn, n, 144, end)
        if y is None:
            return None
        s0 = s0_of(sn.card, y[-n:])
        return finish_cont(T, sn, y, n, end, "hole_water", k, "stable", {"size": None}, rng.choice(STAGES), sl)
    sn = T.sensor_for("tank_level")
    if not sn:
        return None
    card = sn.card
    if rng.random() < 0.25:
        card = sn.card = _jit(card, rng)
    tl = card["tank"]
    if k == "stuck_vs_drain":
        if rng.random() < 0.5:
            return gen_fault_row(T, sn, "hole_water", "stuck", slices=sl)
        k = "slow_day_leak" if rng.random() < 0.5 else "day_drain"
    hours = {"night_leak": (22.5, 29.5), "slow_day_leak": (9, 19), "day_drain": (9, 19)}.get(k, (0, 24))
    n = rng.choice((48, 96, 144)) if k in ("slow_day_leak", "day_drain") else rng.choice((24, 36, 48, 96))
    end = end_at(rng, T.split, hours=hours)
    y = calm_base(T, sn, n, 144, end)
    if y is None:
        return None
    H = len(y)
    s0 = s0_of(card, y[-n:])
    lvl = sum(y[-n:]) / n
    if k in ("night_leak", "slow_day_leak", "day_drain"):
        d = n if k != "night_leak" else rng.randint(max(12, n // 2), n)
        drop = rng.uniform(10, 25) * s0 if k != "day_drain" else rng.uniform(4, 9) * s0
        if k == "slow_day_leak":
            d = max(d, 40)
            drop = max(drop, 0.08 * lvl, 12 * s0)
        o = H - d
        y = [v - (drop * (i - o + 1) / d if i >= o else 0) for i, v in enumerate(y)]
        p, extra = "gradual_decrease", {"size": drop / s0, "d": d, "onset_idx": n - d}
    elif k in ("overflow", "high"):
        tgt_v = tl["overflow"] * rng.uniform(1.0, 1.04) if k == "overflow" else tl["high"] + (tl["overflow"] - tl["high"]) * rng.uniform(0.1, 0.8)
        base = y[-1]
        A = tgt_v - base
        if A < 3 * s0:
            y = [v - (A - 3 * s0) - 4 * s0 for v in y]
            A = tgt_v - y[-1]
        d = rng.randint(6, min(n, 30))
        p = rng.choice(("gradual_increase", "step_increase"))
        r = inject_event(T, card, y, n, p, d, A, rng)
        if r is None:
            return None
        y, extra = r
        extra["size"] = A / s0
    elif k == "valve":
        fm = tl["fill_min"]
        d = min(n - 2, int(2.3 * fm / 5) + rng.randint(1, 8))
        if d < 6 or d >= n:
            return None
        A = min(tl["high"] * 0.98 - y[-1], rng.uniform(8, 20) * s0)
        if A < 4 * s0:
            return None
        p = "gradual_increase"
        r = inject_event(T, card, y, n, p, d, A, rng)
        if r is None:
            return None
        y, extra = r
        extra["size"] = A / s0
    else:  # supply_cut: fast fall (step / exponential-like drop) -> abrupt rate rule
        p = "step_decrease"
        d = rng.randint(3, min(n, 24))
        A = min(y[-1] * rng.uniform(0.3, 0.8), y[-1] - 1)
        r = inject_event(T, card, y, n, p, d, A, rng)
        if r is None:
            return None
        y, extra = r
        extra["size"] = A / s0
    y = clamp(y, card)
    return finish_cont(T, sn, y, n, end, "hole_water", k, p, extra, rng.choice(STAGES), sl)


AQ_CARDS = ("co2_indoor", "temp_indoor", "rh_indoor", "pm25_indoor")


def gen_hole_calm_fault(T, fam="hole_calm_fault"):
    rng = T.rng
    cid = rng.choice(AQ_CARDS) if rng.random() < 0.7 else wchoice(rng, EX_W)
    sn = T.sensor_for(cid)
    if sn is None:
        return None
    kinds = [k for k in ("stuck", "bias", "drift", "quantised") if fault_ok(sn.card, k)]
    k = rng.choice(kinds)
    return gen_fault_row(T, sn, fam, k, slices=("calm_fault", "sensor_fault"), plausible=True)


def gen_hole_recall(T):
    rng = T.rng
    lim = [c for c in EX_W if EC[c]["warning"] is not None]
    sn = T.sensor_for(rng.choice(lim))
    if sn is None:
        return None
    if rng.random() < 0.3:
        sn.card = _jit(sn.card, rng)
    tgt = rng.choice(("warning", "warning", "critical", "critical", "normal"))
    d = sn.card["warning"]["dir"]
    up = ("spike", "step_increase", "gradual_increase", "exponential_increase", "throttling")
    dn = ("dip", "step_decrease", "gradual_decrease")
    p = rng.choice(up if d == "high" else dn if d == "low" else up + dn)
    return gen_event_row(T, sn, "hole_recall", p, tgt, slices=("recall", f"recall_{tgt}"))


# --------------------------------------------------------------------------------------------- unseen metrics + DQ
def gen_unseen_row(T, types, fam="unseen_metric"):
    rng = T.rng
    t = rng.choice(types)
    sn = T.sensor_for(None, synthetic_type=t)
    card = sn.card
    sl = ["unseen", f"type_{t}"]
    if card["kind"] == "binary_state":
        return gen_occ_row(T, sn, fam)
    r = rng.random()
    if r < 0.18:
        return gen_stable_row(T, sn, fam, tuple(sl) + ("calm_or_routine", "calm"))
    if r < 0.62:
        tg = rng.choice(("normal", "warning", "warning", "critical", "critical", "critical"))
        return gen_event_row(T, sn, fam, None, tg, slices=sl)
    if r < 0.86:
        return gen_fault_row(T, sn, fam, slices=tuple(sl) + ("sensor_fault",))
    if r < 0.94 and card["rules"].get("routines"):
        rt = card["rules"]["routines"][0]
        pats = rt.get("patterns") or ["gradual_increase", "gradual_decrease"]
        p = rng.choice(pats)
        if rt["type"] == "solar":
            hours = (6.5, 11.9) if p == "gradual_increase" else (12.5, 18.9)
        else:
            hours = (0, 24)
        n = rng.choice((24, 36, 48))
        end = end_at(rng, T.split, hours=hours)
        y = calm_base(T, sn, n, 144, end)
        if y is None:
            return None
        s0 = s0_of(card, y[-n:])
        tg = "normal" if card["warning"] is not None else None
        rr = target_amp(card, y, n, p, rng.randint(max(DMIN.get(p, 3), n // 2), n), s0, tg, rng, T)
        if rr is None:
            return None
        y2, extra, _ = rr
        return finish_cont(T, sn, y2, n, end, fam, "routine", p, extra, rng.choice(STAGES), sl + ["calm_or_routine", "routine"])
    return gen_dq_row(T, sn, fam)


def gen_dq_row(T, sn=None, fam="dq_edge"):
    rng = T.rng
    if sn is None:
        sn = T.sensor_for(wchoice(rng, EX_W))
        if sn is None:
            return None
    card = sn.card
    k = rng.choice(("glitch_in_event", "glitch_in_event", "insufficient", "insufficient", "recovery_gap", "replaced_bias", "small_gap"))
    if k == "replaced_bias" and not card.get("max_step"):
        k = "recovery_gap"
    if k == "glitch_in_event" and not TV.impossible_idx(card, [-1e17, 1e17]):
        k = "insufficient"
    n = rng.choice((48, 96, 144))
    end = end_at(rng, T.split)
    y = calm_base(T, sn, n, 144, end)
    if y is None:
        return None
    H = len(y)
    s0 = s0_of(card, y[-n:])
    sl = ["data_quality", f"dq_{k}"]
    missing = None
    extra = {"size": None, "d": None, "onset_idx": None}
    p = "stable"
    if k == "glitch_in_event":
        p = rng.choice(("gradual_increase", "step_increase", "gradual_decrease"))
        tg = rng.choice(("normal", "warning", "critical"))
        r = target_amp(card, y, n, p, rng.randint(12, n), s0, tg, rng, T)
        if r is None:
            return None
        y, extra, _ = r
        imp = card["impossible"]
        gi = H - rng.randint(3, n - 2)
        if imp.get("below") is not None and imp["below"] > -1e17 and (imp.get("above") is None or rng.random() < 0.5):
            y[gi] = imp["below"] - abs(imp["below"]) * rng.uniform(0.2, 0.8) - max(1.0, s0)
            if imp["below"] <= 0 and y[gi] > -1:
                y[gi] = -rng.uniform(1, 5) * max(s0, 0.5)
        else:
            y[gi] = imp["above"] * rng.uniform(1.1, 1.6) + 1
        extra["fault_hint"] = "impossible_glitch"
    elif k in ("insufficient", "small_gap", "recovery_gap", "replaced_bias"):
        frac = {"insufficient": rng.uniform(0.26, 0.6), "small_gap": rng.uniform(0.03, 0.2), "recovery_gap": rng.uniform(0.08, 0.3),
                "replaced_bias": rng.uniform(0.05, 0.2)}[k]
        kk = max(1, int(frac * n))
        if k == "insufficient" and rng.random() < 0.6:
            tg = rng.choice(("warning", "critical", "normal"))
            pp = rng.choice(("gradual_increase", "step_increase", "spike"))
            r = target_amp(card, y, n, pp, rng.randint(12, n), s0, tg, rng, T)
            if r:
                y, extra, _ = r
                p = pp
        if k in ("recovery_gap", "replaced_bias"):
            g0 = H - n + rng.randint(4, max(5, n // 2))
            mask = [False] * H
            for i in range(g0, min(H - 3, g0 + kk)):
                mask[i] = True
            if k == "replaced_bias":
                A = card["max_step"] * rng.uniform(1.6, 3.0) * rng.choice((1, -1))
                gend = max(i for i, m in enumerate(mask) if m) + 1
                y = [v + (A if i >= gend else 0) for i, v in enumerate(y)]
                p = "step_increase" if A > 0 else "step_decrease"
                extra = {"size": abs(A) / s0, "d": H - gend + 1, "onset_idx": n - (H - gend) - 1, "ramp": 1, "fault_hint": "bias"}
        else:
            wm = SM.scatter_missing(n, kk, rng)
            mask = [False] * (H - n) + wm
        y = SM.hold_missing(y, mask)
        missing = mask
        extra["missing_mask"] = mask[-n:]
    y = clamp(y, card, keep={i for i, v in enumerate(y) if TV.impossible_idx(card, [v])})
    st = F.compute_stats(y[-n:], card["decimals"])
    if p != "stable" and k != "glitch_in_event" and k != "replaced_bias":
        pass
    if missing and p == "stable" and st["flat_run"] >= 16:
        p = "stable"
    return finish_cont(T, sn, y, n, end, fam, k, p, extra, rng.choice(STAGES), sl, missing=missing)


# --------------------------------------------------------------------------------------------- dispatch
def one(T):
    rng = T.rng
    f = T.fam
    if f == "ex_stable":
        sn = T.sensor_for(wchoice(rng, EX_W))
        return sn and gen_stable_row(T, sn)
    if f == "ex_event":
        sn = T.sensor_for(wchoice(rng, EX_W))
        if sn and rng.random() < 0.3:
            sn.card = _jit(sn.card, rng)
        tg = rng.choices(("normal", "warning", "critical"), weights=(28, 34, 38))[0]
        return sn and gen_event_row(T, sn, f, None, tg, young=rng.random() < 0.12)
    if f == "ex_fault":
        sn = T.sensor_for(wchoice(rng, EX_W))
        return sn and gen_fault_row(T, sn, f)
    if f == "ex_longrange":
        sn = T.sensor_for(wchoice(rng, EX_W))
        return sn and gen_longrange_row(T, sn)
    if f == "ex_occupancy":
        sn = T.sensor_for("occupancy")
        return sn and gen_occ_row(T, sn, f, want=rng.choice((None, None, "off_hours_presence", "flapping")))
    if f == "ex_hvac":
        sn = T.sensor_for("hvac_unit")
        return sn and gen_hvac_row(T, sn)
    if f == "hole_power":
        return gen_hole_power(T)
    if f == "hole_water":
        return gen_hole_water(T)
    if f in ("hole_calm_fault", "calm_fault"):
        return gen_hole_calm_fault(T, "hole_calm_fault")
    if f == "hole_recall":
        return gen_hole_recall(T)
    if f == "calm_routine":
        return gen_routine_row(T)
    if f == "unseen_metric":
        types = list(CD.TEST_TYPES) if T.split == "test_unseen_metric" else list(CD.TRAIN_TYPES)
        return gen_unseen_row(T, types)
    if f == "dq_edge":
        return gen_dq_row(T)
    raise KeyError(f)


def run_task(args):
    split, fam, k, count, seed, out = args
    path = Path(out) / "shards" / f"{split}__{fam}__{k:03d}.jsonl"
    if path.exists() and path.with_suffix(".done").exists():
        return str(path), "cached", 0
    T = Task(split, fam, k, count, seed)
    rows, tries, errs = [], 0, Counter()
    t0 = time.time()
    with open(path, "w", encoding="utf-8") as f:
        made = 0
        while made < count and tries < count * 40:
            tries += 1
            try:
                r = one(T)
            except Exception as e:  # noqa: BLE001
                errs[repr(e)[:120]] += 1
                if sum(errs.values()) < 3:
                    traceback.print_exc()
                r = None
            if not r:
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            made += 1
    path.with_suffix(".done").write_text(json.dumps({"made": made, "tries": tries, "errors": dict(errs.most_common(5)),
                                                     "sec": round(time.time() - t0, 1), "sites": len(T.used_sites)}))
    return str(path), made, tries


def tasks_for(split, scale, seed, plan_override=None):
    out = []
    if split == "train" and plan_override:
        plan = dict(plan_override)   # 2026-11-13 fault rebalance: extra non-fault rows with a new seed
    elif split == "train":
        plan = {k: int(round(v * scale)) for k, v in PLAN.items()}
    else:
        n = int(round(SPLIT_N[split] * max(scale, 0.05)))
        if split == "test_unseen_metric":
            plan = {"unseen_metric": n}
        elif split == "calm_fault":
            plan = {"calm_fault": n}
        else:
            tot = sum(v for k, v in PLAN.items() if not (split != "dev" and k == "unseen_metric"))
            plan = {k: max(1, int(round(n * v / tot))) for k, v in PLAN.items() if not (split != "dev" and k == "unseen_metric")}
            if split == "test_campus":
                plan.pop("ex_hvac", None)
                plan = {k: v for k, v in plan.items()}
    for fam, cnt in plan.items():
        chunk = 300
        for k in range(math.ceil(cnt / chunk)):
            out.append((split, fam, k, min(chunk, cnt - k * chunk), seed))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--only", default="")
    ap.add_argument("--plan", default="", help='train plan override, JSON {"family": rows}')
    a = ap.parse_args()
    out = Path(a.out)
    (out / "shards").mkdir(parents=True, exist_ok=True)
    splits = a.only.split(",") if a.only else ["dev", "test_unseen_layout", "test_campus", "test_unseen_metric", "calm_fault", "train"]
    tasks = []
    for s in splits:
        tasks += [t + (str(out),) for t in tasks_for(s, a.scale, a.seed, json.loads(a.plan) if a.plan else None)]
    print(f"{len(tasks)} tasks", flush=True)
    t0 = time.time()
    with Pool(a.procs) as pool:
        for i, (p, made, tries) in enumerate(pool.imap_unordered(run_task, tasks)):
            print(f"[{i + 1}/{len(tasks)}] {Path(p).name} made={made} tries={tries} t={time.time() - t0:.0f}s", flush=True)
    print("done", round(time.time() - t0), "s", flush=True)


if __name__ == "__main__":
    main()
