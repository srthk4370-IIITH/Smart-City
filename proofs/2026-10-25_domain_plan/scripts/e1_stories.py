"""E1 story suite (PLAN.md section 4): realistic sensor stories as agent windows, teacher-labelled (story gold).

Each story is a generator over REAL test-month windows (training/v2 generators + teacher_v2 / hvac.classify_hvac),
run per time-of-day ("when"), seen vs unseen node, 3 seeds. The prompt is the exact v2 prompt (features_v2 =
Go features_v2.go by the parity tests). `intended` = the label a human operator expects; a row whose teacher gold
differs from `intended` is a LABEL-DEFINITION GAP (rules backlog, not training).

  python e1_stories.py --out DIR [--seeds 3]   -> DIR/eval3e.jsonl, DIR/manifest.json
"""
from __future__ import annotations

import argparse, hashlib, json, math, random, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

V2 = Path("/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2")
for p in (V2 / "topup3f", V2 / "topup3e", V2 / "topup", V2, V2.parent):
    sys.path.insert(0, str(p))
import gen_rw5 as RW  # noqa: E402  (sets up the 3e/3f import paths)
from gen_topup import GV, V, TE, HA, SRC  # noqa: E402
import gen_topup as T  # noqa: E402

F, G, H = V.F, GV.G, HA.H
IST = V.IST


def wdh(e):
    d = datetime.fromtimestamp(e, IST)
    return d.weekday(), d.hour + d.minute / 60


WHEN = {"day": lambda e: wdh(e)[0] < 5 and 11 <= wdh(e)[1] < 16,
        "night": lambda e: wdh(e)[1] < 5 or wdh(e)[1] >= 23,
        "eve": lambda e: wdh(e)[0] < 5 and 18.5 <= wdh(e)[1] < 21,
        "late_morning": lambda e: wdh(e)[0] < 5 and 11 <= wdh(e)[1] < 13,
        "sunday": lambda e: wdh(e)[0] == 6 and 10 <= wdh(e)[1] < 17,
        "any": lambda e: True}


class SCtx(GV.Ctx):
    def __init__(self, S, ends, roles, heldout, split, role, kthr, rng):
        super().__init__(S, ends, roles, heldout, split, role, kthr, rng)
        self.roles_, self.heldout_ = roles, heldout

    """GV.Ctx with the node pool forced to seen / unseen, a key filter and window ends restricted to `when`."""
    def setup(self, tag, when, keyok):
        self.tag, self.when, self.keyok, self._ec = tag, WHEN[when], keyok, {}
        held = set(self.heldout_.get(self.role, []))
        self.seen = [k for nd, ks in self.roles_[self.role].items() if nd not in held for k in ks]
        return self

    def pick_key(self, ok):
        """seen: seen nodes, test + Sep-Oct (dev) months (neither is trained on); unseen: held-out nodes."""
        if self.tag == "unseen" and (self.unseen or self.sepoct):
            pool, tag = sorted(set(self.unseen) | set(self.sepoct)), "unseen"
        else:
            pool, tag = self.seen, "seen"
        pool = [k for k in pool if ok(k) and self.keyok(k) and self._ends(k)]
        if not pool:
            return None, tag
        k = self.rng.choices(pool, weights=[math.sqrt(len(self._ends(k))) for k in pool])[0]
        return k, (tag if tag == "seen" or k in self.unseen else "unseen_sepoct")

    def _ends(self, key):
        if key not in self._ec:
            ok = [(e, c) for c in ("test", "dev") for e in self.ends[key].get(c, []) if self.when(e)]
            if len(ok) < 300:   # thin test/dev data (water level by day, pH): train-month base windows too
                ok += [(e, "train") for e in self.ends[key].get("train", []) if self.when(e)]
            self._ec[key] = ok
        return self._ec[key]

    def base(self, key, n, need_hist=0):
        ends = self._ends(key)
        if not ends:
            return None, None
        end, self.cur = self.rng.choice(ends)
        h = GV.hist_at(self.S[key], end, max_miss=GV.MAX_MISS.get(key[0], 6))
        if len(h) < max(n, need_hist) or GV.split_of(end - (len(h) - 1) * GV.STEP) != self.cur:
            return None, None
        return end, h


# ------------------------------------------------------------------ custom continuous-role stories
def leak(min_d, max_d):
    """Tank level drains steadily from the node's OWN current level for d readings with no refill (real window,
    any shape before onset; the last d readings replaced by a straight drain of 25-50% of the level + noise)."""
    def fn(ctx, n):
        rng = ctx.rng
        key, tag = ctx.pick_key(lambda k: k[2] == "level" and k[1] in V.NODE_LIMITS)
        if key is None:
            return None
        end, y = ctx.base(key, n)
        if y is None:
            return None
        y = list(y)
        m = V.METRICS[key[0], key[2]]
        tl = V.NODE_LIMITS[key[1]]
        Hh, d = len(y), rng.randint(min_d, max_d)
        o = Hh - d
        if max(y[-n:]) >= tl["high"] or y[o - 1] - m["lo"] <= 0:
            return None
        s0, bst = G.scale_of(key[0], key[2], y[max(0, o - 48):o])
        A = rng.uniform(0.25, 0.5) * (y[o - 1] - m["lo"])
        sd = min(s0, 0.01 * A) if s0 else 0.0
        for i in range(o, Hh):
            y[i] = y[o - 1] - A * (i - o + 1) / d + rng.gauss(0, sd)
        y = GV.clamp(y, m)
        return GV.finish(ctx, key, tag, end, y, n, "e1", "leak", "gradual_decrease",
                         {"d": d, "onset_idx": n - d, "size": None, "base_mean": bst["mean"]})
    return fn


def ph_drift(ctx, n):
    """pH falls slowly (0.6-1.2 over 2-4 h) on a real pH window: acid dosing fault / contamination."""
    rng = ctx.rng
    key, tag = ctx.pick_key(lambda k: k[2] == "ph")
    if key is None:
        return None
    end, y = ctx.base(key, n)
    if y is None:
        return None
    y = list(y)
    m = V.METRICS[key[0], key[2]]
    Hh, d = len(y), rng.randint(24, 46)
    o = Hh - d
    A = rng.uniform(0.6, 1.2)
    for i in range(o, Hh):
        y[i] -= A * (i - o + 1) / d
    y = GV.clamp(y, m)
    return GV.finish(ctx, key, tag, end, y, n, "e1", "ph_drift", "gradual_decrease", {"d": d, "onset_idx": n - d, "size": None})


def flat_at(value_fn, d_lo, d_hi):
    """Sensor frozen (exactly constant) for the last d readings, e.g. CO2 stuck at 400 ppm."""
    def fn(ctx, n):
        rng = ctx.rng
        b = GV.calm_base(ctx, n)
        if b is None:
            return None
        key, tag, end, y, s0, bst = b
        d = rng.randint(d_lo, d_hi)
        v = value_fn(y, rng)
        for i in range(len(y) - d, len(y)):
            y[i] = v
        return GV.finish(ctx, key, tag, end, y, n, "fault", "stuck", "flatline",
                         {"d": d, "onset_idx": n - d, "size": None, "base_mean": bst["mean"], "fault_hint": "stuck"})
    return fn


def scaled_event(pattern):
    """Unseen-sensor look: the node's history rescaled by a in {0.6, 1.7} (+-10% offset), then a v2 event."""
    def fn(ctx, n):
        rng = ctx.rng
        orig_hist = GV.hist_at
        a = rng.choice((0.6, 1.7))

        def hist_scaled(s, end, maxlen=V.HIST, max_miss=6):
            h = orig_hist(s, end, maxlen, max_miss)
            if not h:
                return h
            med = sorted(h)[len(h) // 2]
            off = rng.uniform(-0.1, 0.1) * med
            return [v * a + off for v in h]
        GV.hist_at = hist_scaled
        try:
            r = GV.gen_event(ctx, n, pattern=pattern)
        finally:
            GV.hist_at = orig_hist
        if r:
            r["scale"] = a
        return r
    return fn


def water_fill(sub):
    def fn(ctx, n):
        ctx.__dict__["wf_made"] = Counter({k: (0 if k == sub else 10 ** 6) for k in GV.WATER_FILL_CAUSE})
        return GV.gen_water_fill(ctx, n)
    return fn


# ------------------------------------------------------------------ HVAC stories
HV_CACHE = {}


def hv_pool(tag):
    U = HA.units()
    held = set(HA.heldout_units())
    if "pool" not in HV_CACHE:
        months = HA.MONTHS["test"]
        HV_CACHE["pool"] = {nd: H.window_ends(U[nd], months) for nd in sorted(U)}
    nodes = [nd for nd, e in HV_CACHE["pool"].items() if e and ((nd in held) == (tag == "unseen")) and not U[nd].get("faulty")]
    return U, nodes


def hv_row(rng, node, xs144, c144, ys, c2, lab, tag, sub):
    n = len(ys)
    hist = (xs144[:-n] + ys) if c2["end"] == c144["end"] else list(ys)
    user, st, ev = H.user_prompt(node, H.describe(node), ys, c2)
    hv, info = V.history_items("hvac", "room_temp", hist[-V.HIST:], c2["end"], 1, "C")
    user = user + "\n" + "\n".join(f"{e} {t}" for e, _, t in hv)
    ev = list(ev) + hv
    system = H.SYSTEM_PROMPT + V.system_rules(n) + " " + V.output_schema_hint("hvac")
    lab = {k: v for k, v in lab.items() if not k.startswith("_")}
    GV.validate("hvac", lab, [e[0] for e in ev])
    return {"role": "hvac", "node": node, "metric": "room_temp", "split": "test", "seen": tag, "end_epoch": c2["end"],
            "n": n, "family": "e1", "sub": sub, "pattern": lab["pattern"], "status": lab["status"],
            "likely_cause": lab["likely_cause"], "event_active": lab["event_active"], "onset": lab["onset"], "d": None,
            "hist": [round(v, 4) for v in hist[-V.HIST:]], "ac_on": c2["on"], "setpoint": c2["sp"],
            "prompt": V.F.llama3_prompt(system, user), "completion": json.dumps(lab, ensure_ascii=False) + "<|eot_id|>"}


def hv_window(rng, tag, when, running):
    U, nodes = hv_pool(tag)
    for _ in range(50):
        node = rng.choice(nodes)
        ends = [e for e, r in HV_CACHE["pool"][node] if r == running and WHEN[when](e)]
        if not ends:
            continue
        w = HA.window_at(U[node], node, rng.choice(ends), 144)
        if w:
            return node, w
    return None, None


def ac_not_cooling(rate_lo, rate_hi, hold):
    """AC running (cool mode) in band, then the room warms at +rate C/h for 1.5-2.5 h with the AC still on
    (compressor dead). hold>1: each value held for `hold` buckets (one ingest spread over several 5-min buckets)."""
    def fn(rng, tag, when, n=48):
        node, w = hv_window(rng, tag, when, True)
        if not node:
            return None
        xs144, c144 = w
        xs, c = list(xs144[-n:]), HA.slice_ctx(c144, n)
        if c["mode"] != 1 or sum(c["on"]) < n - 2 or abs(xs[-n // 2] - c["sp"][-n // 2]) > 1.5:
            return None
        L = rng.randint(18, 30)
        o = n - L
        rate = rng.uniform(rate_lo, rate_hi)
        base = xs[o - 1]
        ys = xs[:o] + [round(min(H.TEMP_HI, base + rate * (i - o + 1 - ((i - o) % hold if hold > 1 else 0)) / 12.0
                                 + rng.gauss(0, 0.05)), 2) for i in range(o, n)]
        c2 = H._copy_ctx(c)
        c2["on"] = [1] * n
        lab = H.label_hvac(ys, c2, rng)
        return hv_row(rng, node, xs144, c144, ys, c2, lab, tag, "ac_not_cooling")
    return fn


def hv_case(pattern, running):
    def fn(rng, tag, when, n=48):
        node, w = hv_window(rng, tag, when, running)
        if not node:
            return None
        xs144, c144 = w
        xs, c = list(xs144[-n:]), HA.slice_ctx(c144, n)
        r = H.make_case(pattern, xs, c, rng)
        if r is None:
            return None
        ys, c2, lab = r
        if not WHEN[when](c2["end"]):
            return None
        return hv_row(rng, node, xs144, c144, ys, c2, lab, tag, pattern)
    return fn


# ------------------------------------------------------------------ the suite
ALERT = ("warning", "critical")
LEAK = {"pattern": ("gradual_decrease",), "status": ("warning",), "cause": ("possible_leak",)}
NOCOOL = {"pattern": ("no_cooling_effect", "too_hot", "slow_recovery"), "status": ALERT, "cause": ("ac_not_cooling", "high_heat_load")}
# name: (role, fn, whens, key filter, intended or None (= teacher))
lvl = lambda k: k[2] == "level"
STORIES = {
    "leak_night":          ("water", leak(24, 40), ("night",), lvl, LEAK),
    "leak_day_norefill":   ("water", leak(36, 46), ("day",), lvl, LEAK),
    "fill_valve_stuck":    ("water", water_fill("valve_stuck"), ("day", "night"), lvl, None),
    "overflow_fill":       ("water", water_fill("overflow_fill"), ("day", "night"), lvl, None),
    "refill_then_drain":   ("water", lambda c, n: GV.gen_compound(c, n), ("day", "night"), lambda k: k[2] in ("level", "flow"), None),
    "ph_slow_drift":       ("water", ph_drift, ("day", "night"), lambda k: k[2] == "ph", None),
    "level_gradual_small": ("water", lambda c, n: GV.gen_event(c, n, "gradual_decrease"), ("day", "night"), lambda k: k[2] in ("level", "flow"), None),
    "flow_stuck_zero":     ("water", flat_at(lambda y, r: 0.0, 18, 36), ("day", "night"), lambda k: k[2] == "flow", None),
    "load_growth_11h":     ("power", lambda c, n: GV.gen_event(c, n, "gradual_increase"), ("late_morning",), lambda k: k[2] == "power_kw" and not k[1].startswith("SL-"), None),
    "evening_shutdown":    ("power", lambda c, n: GV.gen_event(c, n, "step_decrease"), ("eve",), lambda k: k[2] == "power_kw" and not k[1].startswith("SL-"), None),
    "weekend_low_load":    ("power", lambda c, n: RW.gen_holiday(c, n), ("any",), lambda k: True, None),
    "power_step_then_grad": ("power", lambda c, n: GV.gen_compound(c, n), ("day", "night"), lambda k: k[2] == "power_kw", None),
    "power_gap_recovery":  ("power", lambda c, n: RW.gen_gap_recovery(c, n), ("day", "night"), lambda k: True, None),
    "co2_stuck_400":       ("air_quality", flat_at(lambda y, r: 400.0, 30, 40), ("day", "night"), lambda k: k[2] == "co2" and k[1].startswith("SR-"), None),
    "co2_drift":           ("air_quality", lambda c, n: GV.gen_fault(c, n, "calib_drift"), ("night",), lambda k: True, None),
    "chatter_at_limit":    ("air_quality", lambda c, n: RW.gen_chatter(c, n), ("day", "night"), lambda k: True, None),
    "single_glitch":       ("air_quality", lambda c, n: RW.gen_glitch(c, n), ("day", "night"), lambda k: True, None),
    "unseen_scale_level":  ("water", scaled_event("gradual_decrease"), ("day", "night"), lvl, None),
    "unseen_scale_power":  ("power", scaled_event("gradual_decrease"), ("day", "night"), lambda k: k[2] == "power_kw", None),
}
HV_STORIES = {
    "ac_not_cooling_14h":  (ac_not_cooling(1.0, 2.0, 1), ("day",), NOCOOL),
    "ac_fast_stepped":     (ac_not_cooling(3.5, 4.5, 3), ("day",), NOCOOL),
    "ac_empty_room_night": (hv_case("stuck_on", True), ("night",), None),
    "ac_stuck_off_work":   (hv_case("stuck_off", False), ("day",), None),
    "ac_slow_recovery":    (hv_case("slow_recovery", True), ("any",), None),
}


def gap(row, intended):
    if not intended:
        return False
    return not (row["pattern"] in intended["pattern"] and row["status"] in intended["status"] and row["likely_cause"] in intended["cause"])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    man0 = json.loads((SRC / "manifest.json").read_text())
    heldout = dict(man0["heldout_nodes"])
    kj = json.loads((SRC / "kthr.json").read_text())
    kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
    V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text()))
    HA.register(); TE.build_calibration()
    rows, miss, cache = [], [], {}
    for name, (role, fn, whens, keyok, intended) in STORIES.items():
        if role not in cache:
            cache = {role: T.load_role(role)}
        S, roles, ends = cache[role]
        for when in whens:
            for tag in ("seen", "unseen"):
                for seed in range(a.seeds):
                    rng = random.Random(f"e1|{name}|{when}|{tag}|{seed}")
                    ctx = SCtx(S, ends, roles, heldout, "test", role, kthr, rng).setup(tag, when, keyok)
                    r = None
                    for _ in range(3000):
                        try:
                            r = fn(ctx, 48)
                        except AssertionError:
                            r = None
                        if r:
                            break
                    if not r:
                        miss.append(f"{name}/{when}/{tag}/{seed}"); continue
                    r["base_split"] = getattr(ctx, "cur", None) if "ctx" in dir() else None
                    r.update(id=f"e1-{name}-{when}-{tag}-{seed}", story=name, when=when, seen_req=tag, intended=intended,
                             label_gap=gap(r, intended))
                    rows.append(r)
        print(f"  {name}: {sum(1 for r in rows if r['story'] == name)}", flush=True)
    cache = None
    for name, (fn, whens, intended) in HV_STORIES.items():
        for when in whens:
            for tag in ("seen", "unseen"):
                for seed in range(a.seeds):
                    rng = random.Random(f"e1|{name}|{when}|{tag}|{seed}")
                    r = None
                    for _ in range(400):
                        try:
                            r = fn(rng, tag, when)
                        except AssertionError:
                            r = None
                        if r:
                            break
                    if not r:
                        miss.append(f"{name}/{when}/{tag}/{seed}"); continue
                    r.update(id=f"e1-{name}-{when}-{tag}-{seed}", story=name, when=when, seen_req=tag, intended=intended,
                             label_gap=gap(r, intended))
                    rows.append(r)
        print(f"  {name}: {sum(1 for r in rows if r['story'] == name)}", flush=True)
    for r in rows:
        r["slices_all"] = ["e1", r["story"], "when_" + r["when"], r.get("seen", "seen")] + (["label_gap"] if r["label_gap"] else [])
        r["off_hours"] = bool(F.is_off_hours(r["end_epoch"])) if r["role"] != "hvac" else bool(H.off_hours(r["end_epoch"]))
    with open(out / "eval3e.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    gold = Counter(f"{r['story']}:{r['pattern']}/{r['status']}/{r['likely_cause']}" for r in rows)
    man = {"what": "E1 story suite (PLAN.md s4), teacher gold", "n": len(rows), "missing": miss,
           "label_gaps": Counter(r["story"] for r in rows if r["label_gap"]), "gold": gold,
           "sha256_16": hashlib.sha256((out / "eval3e.jsonl").read_bytes()).hexdigest()[:16]}
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    print(f"E1 rows {len(rows)}, missing {len(miss)}, label gaps {sum(man['label_gaps'].values())}: {dict(man['label_gaps'])}")


if __name__ == "__main__":
    main()
