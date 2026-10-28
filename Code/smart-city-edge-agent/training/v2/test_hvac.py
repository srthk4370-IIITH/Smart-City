"""Self-test for training/v2/hvac.py (synthetic windows only, no private data needed).

  py -3 -m pytest training/v2/test_hvac.py      (if pytest is installed)
  py -3 training/v2/test_hvac.py                (plain asserts)
"""
from __future__ import annotations

import math
import random
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import hvac as H  # noqa: E402
import features as F  # noqa: E402

KEY_ORDER = ["pattern", "status", "observations", "likely_cause", "confidence", "event_active", "onset"]
SPEC_FAULT_KINDS = {"stuck", "bias", "drift", "noise", "dropout", "saturation", "quantised"}  # D6
ALLOWED_ACTIONS = set(F.ACTIONS) | set(H.NEW_ACTIONS)  # D9: switch_off_ac (recommendation, needs approval)
LENGTHS = tuple(range(24, 145, 6))  # D10: any N from 24 to 144 in steps of 6
OFFICE = [0.05] * 8 + [0.6] * 11 + [0.2] * 5  # usual on-fraction per IST hour


def end_at(day=12, hour=14, minute=0):
    """A Thursday in March 2025 (train month) unless the day says otherwise."""
    return int(datetime(2025, 3, day, hour, minute, tzinfo=H.IST).timestamp())


def ctx_for(n, on, sp=24.0, end=None, thermo=None, occ=None, mode=1, duty="office"):
    return dict(node="SR-AC-KH02-12", end=end or end_at(), sp=[sp] * n, on=list(on), thermo=thermo, mode=mode,
                alarm=[0] * n, malf=1, missing=[False] * n, occ=occ, duty=duty, hour_on=list(OFFICE))


def quant(v):
    return round(v, 1)  # the real sensor resolution is 0.1 C


def on_base(n, rng, sp=24.0):
    xs = [quant(sp + 0.3 + 0.06 * math.sin(i / 3.0) + rng.gauss(0, 0.03)) for i in range(n)]
    return xs, ctx_for(n, [1] * n, sp)


def off_base(n, rng, level=28.0):
    xs = [quant(level + 0.002 * i + rng.gauss(0, 0.04)) for i in range(n)]
    c = ctx_for(n, [0] * n, duty="idle")
    c["hour_on"] = [0.0] * 24  # a never-run unit, like 66 of the 87 real ones
    return xs, c


def label(xs, ctx, seed=0):
    return H.label_hvac(xs, ctx, random.Random(seed))


def prompt_text(xs, ctx):
    return H.user_prompt(ctx["node"], H.describe(ctx["node"]), xs, ctx)[0]


def check_label(lab, xs, ctx):
    keys = [k for k in lab if not k.startswith("_")]
    assert keys[:7] == KEY_ORDER, keys
    assert keys[-1] == "action"
    assert lab["pattern"] in H.PATTERNS
    assert lab["status"] in ("normal", "warning", "critical", "sensor_fault")
    assert lab["likely_cause"] in H.CAUSES
    assert lab["action"] in ALLOWED_ACTIONS
    assert 0.0 <= lab["confidence"] <= 1.0
    assert isinstance(lab["event_active"], bool)
    assert re.fullmatch(r"\d\d:\d\d", lab["onset"])
    if lab["status"] == "sensor_fault":
        assert lab["fault_kind"] in SPEC_FAULT_KINDS
    else:
        assert "fault_kind" not in lab
    obs = lab["observations"]
    assert 1 <= len(obs) <= 2, obs
    text = prompt_text(xs, ctx)
    for o in obs:
        m = re.search(r"\[(E\d+(?:,E\d+)*)\]$", o)
        assert m, o
        assert all(1 <= int(e[1:]) <= 8 for e in m.group(1).split(",")), o
        body = o[:m.start()]
        assert len(body.split()) <= 18, (len(body.split()), o)
        for num in re.findall(r"[-+]?\d+(?:\.\d+)?%?", re.sub(r"(?<=\d)-(?=\d)", " ", body)):
            assert num.lstrip("+") in text or num in text, (num, o, text)


# ------------------------------------------------------------------------------------- tests
def test_role_spec():
    assert len(set(H.PATTERNS)) == len(H.PATTERNS)
    assert set(H.ACTION_OF) == set(H.CAUSES)
    assert set(H.ACTIONS) <= ALLOWED_ACTIONS and H.NEW_ACTIONS == ("switch_off_ac",)
    assert H.ACTION_OF["unoccupied_running"] == "switch_off_ac"
    assert set(H.FAULT_KIND) == set(H.FAULT_PATTERNS)
    assert set(H.FAULT_KIND.values()) == SPEC_FAULT_KINDS
    assert H.HVAC_ROLE["system_prompt"].startswith("You are the HVAC agent")
    for k, m in H.METRICS.items():
        assert {"unit", "dec", "warn", "crit", "dir", "floor", "lo", "hi"} <= set(m), k


def test_synthetic_labels():
    n = 48
    rng = random.Random(3)
    # running in band -> stable / normal
    xs, c = on_base(n, rng)
    lab = label(xs, c)
    assert lab["pattern"] in ("stable", "normal_cycling") and lab["status"] == "normal", lab
    # AC on for the whole window, room 29 C flat vs setpoint 24 -> no cooling effect
    xs = [quant(29.0 + 0.01 * i) for i in range(n)]
    lab = label(xs, ctx_for(n, [1] * n))
    assert lab["pattern"] == "no_cooling_effect" and lab["status"] in ("warning", "critical"), lab
    assert lab["likely_cause"] == "ac_not_cooling" and lab["action"] == "inspect_hvac"
    # AC started 90 min ago, room falling only 0.5 C/h, still far above band -> slow recovery
    p = n - 18
    xs = [30.0] * p + [quant(30.0 - 0.5 * (i - p) / 12) for i in range(p, n)]
    lab = label(xs, ctx_for(n, [0] * p + [1] * (n - p)))
    assert lab["pattern"] == "slow_recovery" and lab["status"] == "warning", lab
    # AC started 40 min ago and is pulling down fast -> normal pull-down
    p = n - 8
    xs = [29.0] * p + [quant(24.5 + 4.5 * math.exp(-(i - p) / 6)) for i in range(p, n)]
    lab = label(xs, ctx_for(n, [0] * p + [1] * (n - p)))
    assert lab["pattern"] == "pull_down" and lab["status"] == "normal", lab
    # 1-2 reading on-runs -> short cycling
    on = [1, 0, 0] * 16
    xs, _ = on_base(n, rng)
    lab = label(xs, ctx_for(n, on))
    assert lab["pattern"] == "short_cycling" and lab["status"] in ("warning", "critical"), lab
    # running in an empty room for 2 h
    xs, c = on_base(n, rng)
    c["occ"] = [1] * 24 + [0] * 24
    lab = label(xs, c)
    assert lab["pattern"] == "running_empty_room" and lab["likely_cause"] == "unoccupied_running", lab
    assert lab["status"] == "warning" and lab["action"] == "switch_off_ac", lab
    assert "recommend switching it off" in lab["observations"][0], lab
    c["occ"] = None  # no occupancy feed: the pattern cannot fire and the prompt says so
    lab = label(xs, c)
    assert lab["pattern"] != "running_empty_room", lab
    assert "occupancy n/a" in prompt_text(xs, c)
    # overcooling: 19 C while cooling at setpoint 24
    xs = [quant(24.0 - 0.3 * i) for i in range(18)] + [quant(18.9 + 0.1 * (i % 2)) for i in range(30)]
    lab = label(xs, ctx_for(n, [1] * n))
    assert lab["pattern"] == "too_cold" and lab["status"] in ("warning", "critical"), lab
    # off all window in working hours though usually on, room hot -> stuck off
    xs = [quant(27.5 + 0.01 * i) for i in range(n)]
    lab = label(xs, ctx_for(n, [0] * n, end=end_at(hour=15)))
    assert lab["pattern"] == "stuck_off" and lab["likely_cause"] == "unit_not_starting", lab
    # same room at 15:00 on a Sunday, unit never runs then -> not stuck_off
    lab = label(xs, ctx_for(n, [0] * n, end=end_at(day=16, hour=15)))
    assert lab["pattern"] != "stuck_off", lab
    # on all night, room at setpoint, office unit -> stuck on;  continuous unit -> normal
    xs, _ = on_base(n, rng)
    xs = [v - 0.5 for v in xs]
    lab = label(xs, ctx_for(n, [1] * n, end=end_at(hour=3)))
    assert lab["pattern"] == "stuck_on" and lab["action"] == "review_schedule", lab
    lab = label(xs, ctx_for(n, [1] * n, end=end_at(hour=3), duty="continuous"))
    assert lab["status"] == "normal", lab
    # fan mode with a warm room is not "no cooling"
    xs = [quant(29.0 + 0.01 * i) for i in range(n)]
    lab = label(xs, ctx_for(n, [1] * n, mode=3))
    assert lab["status"] == "normal", lab
    # sensor faults
    xs, c = on_base(n, rng)
    xs = xs[:20] + [xs[20]] * 28
    lab = label(xs, c)
    assert lab["pattern"] == "flatline" and lab["fault_kind"] == "stuck", lab
    xs, c = off_base(n, rng)
    c["missing"] = [False] * 30 + [True] * 18
    lab = label(xs, c)
    assert lab["pattern"] == "dropout" and lab["fault_kind"] == "dropout", lab
    xs = xs[:40] + [45.0] * 8
    c["missing"] = [False] * n
    lab = label(xs, c)
    assert lab["pattern"] == "saturation" and lab["status"] == "sensor_fault", lab
    xs, c = on_base(n, rng)
    c["alarm"] = [0] * 40 + [1] * 8
    c["malf"] = 37
    lab = label(xs, c)
    assert lab["pattern"] == "unit_alarm" and "37" in " ".join(lab["observations"]), lab
    # AC off at night, room warming slowly -> normal setback drift
    xs = [quant(26.0 + 0.6 * i / 12) for i in range(n)]
    lab = label(xs, ctx_for(n, [0] * n, end=end_at(hour=23)))
    assert lab["pattern"] == "setback_drift" and lab["status"] == "normal", lab


def _cases(n, seed):
    rng = random.Random(seed)
    bases = [on_base(n, rng, sp=rng.choice((22.0, 24.0, 26.0))) for _ in range(6)] + \
            [off_base(n, rng, level=rng.uniform(26.0, 30.0)) for _ in range(6)]
    for b in bases:
        assert H.base_kind(*b) is not None, "synthetic base must be a valid injection base"
    return rng, bases


def test_every_pattern_injectable():
    for n in (24, 30, 48, 66, 96, 144):
        rng, bases = _cases(n, 11 + n)
        for pat in H.INJECTABLE:
            if n < H.MIN_LEN.get(pat, 0):
                continue
            ok = 0
            for t in range(300):
                xs, c = bases[t % len(bases)]
                r = H.make_case(pat, xs, c, rng)
                if r is None:
                    continue
                ys, c2, lab = r
                check_label(lab, ys, c2)
                ok += 1
                if ok >= 3:
                    break
            assert ok >= 1, f"pattern {pat} never produced at n={n}"


def test_values_and_determinism():
    n = 48
    rng, bases = _cases(n, 5)
    m = H.METRICS[("hvac", "room_temp")]
    for pat in H.INJECTABLE:
        for t in range(40):
            xs, c = bases[t % len(bases)]
            r = H.inject_hvac(pat, xs, c, rng)
            if r is None:
                continue
            ys, c2, meta = r
            assert len(ys) == n and all(v == v and m["lo"] <= v <= m["hi"] for v in ys), pat
            assert all(16 <= v <= 32 for v in c2["sp"]), pat
            assert set(c2["on"]) <= {0, 1}
            assert 0 <= meta["onset"] < n and 1.5 <= meta["size"] <= 12.0
            lab = H.label_hvac(ys, c2, random.Random(1))
            check_label(lab, ys, c2)
    xs, c = bases[0]
    a = H.make_case("short_cycling", xs, c, random.Random(42))
    b = H.make_case("short_cycling", xs, c, random.Random(42))
    assert a is not None and a[0] == b[0] and a[2] == b[2], "same rng seed must give the same case"


def test_series_format_all_lengths():
    rng = random.Random(4)
    for n in LENGTHS:
        xs, c = on_base(n, rng)
        text = prompt_text(xs, c)
        temp = next(line for line in text.splitlines() if line.startswith("ROOM TEMP (10-min means): "))
        state = next(line for line in text.splitlines() if line.startswith("AC STATE (10-min, 1=on): "))
        assert len(temp.split(": ")[1].split()) == n // 2, (n, temp)
        assert len(state.split(": ")[1]) == n // 2, (n, state)
        assert f"{n} x 5 min" in text
        lab = label(xs, c)
        check_label(lab, xs, c)


def test_new_faults_and_faulty_units():
    n = 48
    rng = random.Random(8)
    # hot thermistor: reads 41 C after hours of cooling -> biased_reading (bias)
    xs = [quant(41.0 + 0.1 * (i % 3)) for i in range(n)]
    lab = label(xs, ctx_for(n, [1] * n))
    assert lab["pattern"] == "biased_reading" and lab["fault_kind"] == "bias", lab
    # whole-degree readings -> quantised
    xs, c = on_base(n, rng)
    xs = xs[:30] + [float(v) for v in (24, 25, 25, 24, 24, 25, 26, 25, 24, 24, 25, 25, 24, 25, 24, 24, 25, 25)]
    lab = label(xs, c)
    assert lab["pattern"] == "quantised" and lab["fault_kind"] == "quantised", lab
    check_label(lab, xs, c)
    # D11: a faulty unit's window is never a base; its real fault windows are kept as labelled faults
    xs = [quant(41.0 + 0.1 * (i % 3)) for i in range(n)]
    c = ctx_for(n, [1] * n)
    c["faulty"] = True
    assert H.base_kind(xs, c) is None
    assert H.make_case("stable", xs, c, rng) is None
    r = H.make_case("biased_reading", xs, c, rng)
    assert r is not None and r[0] == xs and r[2]["status"] == "sensor_fault", r
    xs2, c2 = on_base(n, rng)
    c2["faulty"] = True
    assert H.real_fault_case(xs2, c2, rng) is None, "a normal-looking window of a faulty unit is not used"
    # D7: a short clean decline with the AC off is no longer a calibration drift
    xs = [quant(29.0 - 1.0 * i / 12) for i in range(24)]
    xs = [29.0] * (n - 24) + xs
    c = ctx_for(n, [0] * n, end=end_at(hour=15), duty="idle")
    c["hour_on"] = [0.0] * 24
    assert label(xs, c)["pattern"] != "calibration_drift"


def test_window_ends_dense_on():
    n, L = 48, 2000
    b0 = end_at() - L * 300
    rows = {}
    for i in range(L):
        on = 1 if (i // 200) % 2 else 0  # alternating 200-reading off / on blocks
        rows[b0 + i * 300] = (on, 0.0, 25.0, 24.0, 1, 0, 1)
    unit = {"rows": rows}
    ends = H.window_ends(unit, months=(2, 3), n=n, stride_off=12, stride_on=2)
    on_ends = sum(1 for _, r in ends if r)
    off_ends = sum(1 for _, r in ends if not r)
    assert on_ends > 3 * off_ends, (on_ends, off_ends)


def test_onset_sampler():
    rng = random.Random(0)
    ages = [48 - H.sample_onset(48, rng) for _ in range(5000)]
    assert min(ages) >= 3 and max(ages) <= 48
    assert sum(4 <= a <= 12 for a in ages) / len(ages) > 0.4, "extra weight on 20-60 min ages"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all HVAC tests passed")
