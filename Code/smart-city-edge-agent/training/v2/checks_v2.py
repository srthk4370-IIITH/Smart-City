"""Automatic QA of the v2 dataset (spec decision #22). Writes checks.json + checks.md next to the data.

  py -3 checks_v2.py [--data data/sft_v2]

Checks (each counts pass/fail over all rows; hard checks must have 0 failures):
  json            completion parses, ends with <|eot_id|>, key order = frozen schema
  enums           pattern/status/cause per role, fault_kind only (and always) for sensor_fault, onset HH:MM,
                  event_active bool, confidence in [0,1], action = backend derivation
  obs_count       1-2 observations, each ending with cited ids
  evidence_ids    every cited id exists in the prompt's evidence block
  numbers         every number / HH:MM in an observation appears in the prompt's user text
  rebuild         prompt rebuilt from the stored history equals the stored prompt (v1 roles)
  v1_equal_48     at N=48 the user text up to E8 is byte-identical to v1 features.build_user_prompt
  leakage         held-out node in train/dev; window end or history start outside the split's months
  duplicates      identical prompts within or across splits
  amplitude       values inside metric lo..hi (dropout zeros excepted); injected size within 1.5-12
  shape           per-family sanity: stable windows calm; flatline-stuck has a flat run; saturation at the rail;
                  dropout min = 0; boundary rows labelled stable/normal
False-alarm definition (D3, acceptance d): a false alarm is status != normal on a calm or routine window.
The label-side table "false_alarm_label_rate" shows status != normal among the negative families (stable,
routine, real_routine, zero_idle, boundary rows, HVAC hard negatives); routine windows keep their honest shape
pattern (e.g. step_increase) with status normal, so a pattern != stable is NOT an alarm.
Soft flags (reported, not failures): completion generated part > 70 tokens, prompt > 900 tokens, words > 14.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import features_v2 as V  # noqa: E402
import generate_dataset as G  # noqa: E402
import generate_v2 as GV  # noqa: E402
import hvac_adapter as HA  # noqa: E402
import teacher_v2 as TE  # noqa: E402

F = V.F
NUM = re.compile(r"(?<![A-Za-z0-9.:])[-+]?\d+(?:\.\d+)?(?![\d:])")
TIME = re.compile(r"\b\d\d:\d\d\b")
MONTHS = {"train": range(1, 9), "dev": (9, 10), "test": (11, 12)}
HARD = ("json", "enums", "obs_count", "evidence_ids", "numbers", "rebuild", "v1_equal_48", "leakage", "duplicates",
        "amplitude", "shape")


def present(num, text):
    s = num.lstrip("+-")
    return re.search(r"(?<![\d.])[-+]?" + re.escape(s) + r"(?![\d])", text) is not None


def month(e):
    return datetime.fromtimestamp(e, V.IST).month


def check_row(r, heldout, res, flags, ex):
    rid = r["id"]
    role = r["role"]

    def fail(name, why):
        res[name][1] += 1
        if len(ex[name]) < 12:
            ex[name].append(f"{rid}: {why}")

    def ok(name):
        res[name][0] += 1

    user = V.user_text(r["prompt"])
    c = r["completion"]
    try:
        assert c.endswith("<|eot_id|>")
        t = json.loads(c[: -len("<|eot_id|>")])
        assert tuple(t) == tuple(k for k in V.KEY_ORDER if k in t)
        ok("json")
    except Exception as e:  # noqa: BLE001
        fail("json", repr(e))
        return
    try:
        assert t["pattern"] in V.PATTERNS[role], t["pattern"]
        assert t["status"] in V.STATUSES
        assert t["likely_cause"] in V.CAUSES[role], t["likely_cause"]
        assert ("fault_kind" in t) == (t["status"] == "sensor_fault")
        assert "fault_kind" not in t or t["fault_kind"] in V.FAULT_KINDS
        assert isinstance(t["event_active"], bool)
        assert re.fullmatch(r"\d\d:\d\d", t["onset"])
        assert 0 <= t["confidence"] <= 1
        if role == "hvac":
            assert t["action"] == HA.H.action_of(t["likely_cause"], t["status"])
        else:
            assert t["action"] == TE.action_of(t["likely_cause"], t["status"])
        ok("enums")
    except Exception as e:  # noqa: BLE001
        fail("enums", repr(e))
    obs = t["observations"]
    if 1 <= len(obs) <= 2 and all(re.search(r"\[E\d+(,E\d+)*\]$", o) for o in obs):
        ok("obs_count")
    else:
        fail("obs_count", str(obs))
    eids = set(re.findall(r"^(E\d+) ", user, re.M))
    bad = [i for o in obs for i in re.findall(r"E\d+", o[o.rindex("["):]) if i not in eids]
    (fail("evidence_ids", str(bad)) if bad else ok("evidence_ids"))
    miss = []
    for o in obs:
        body = o[: o.rindex("[")]
        for tm in TIME.findall(body):
            if tm not in user:
                miss.append(tm)
        for nm in NUM.findall(TIME.sub(" ", body)):
            if not present(nm, user):
                miss.append(nm)
        w = len(body.split())
        flags["obs_words"].append(w)
    (fail("numbers", f"{miss} in {obs}") if miss else ok("numbers"))
    # rebuild
    n = r["n"]
    if role != "hvac":
        try:
            p2, st, ev, info = V.agent_prompt(role, r["node"], G.describe(r["node"]), r["metric"], r["hist"], n, r["end_epoch"])
            (ok("rebuild") if p2 == r["prompt"] else fail("rebuild", "prompt differs"))
            if n == 48 and "TANK: " not in user:  # the v2 TANK line (water level) has no v1 counterpart
                xs = r["hist"][-48:]
                (ok("v1_equal_48") if V.v1_prefix_equal(role, r["node"], G.describe(r["node"]), r["metric"], xs, r["end_epoch"])
                 else fail("v1_equal_48", "differs from v1"))
        except Exception as e:  # noqa: BLE001
            fail("rebuild", repr(e))
            st = None
    else:
        st = None
    # leakage
    sp = r["split"]
    hstart = r["end_epoch"] - (r["hist_len"] - 1) * 300
    lk = []
    if sp in ("train", "dev") and r["node"] in heldout.get(role, []):
        lk.append("held-out node")
    months = MONTHS[sp]
    if sp == "test" and r["seen"] == "unseen_sepoct":  # D8: held-out water sensors' Sep-Oct windows
        months = MONTHS["dev"]
    if month(r["end_epoch"]) not in months or month(hstart) not in months:
        lk.append(f"months {month(hstart)}-{month(r['end_epoch'])}")
    if sp == "test" and (r["seen"] in ("unseen", "unseen_sepoct")) != (r["node"] in heldout.get(role, [])):
        lk.append("seen tag")
    (fail("leakage", ",".join(lk)) if lk else ok("leakage"))
    # amplitude
    am = []
    if role != "hvac":
        m = V.METRICS[(role, r["metric"])]
        xs = r["hist"][-n:]
        if r.get("sub") != "dropout" and any(v < m["lo"] - 1e-9 or v > m["hi"] + 1e-9 for v in xs):
            am.append("outside lo..hi")
    if r.get("size") is not None and r["family"] != "hvac" and not (1.5 - 1e-6 <= r["size"] <= 16.5):
        am.append(f"size {r['size']}")
    (fail("amplitude", ",".join(am)) if am else ok("amplitude"))
    # shape
    sh = []
    if st is not None and role != "occupancy":
        fam, sub = r["family"], r.get("sub")
        if fam == "stable" and not GV.pcalm(role, r["metric"], r["hist"][-n:]):
            sh.append("stable window not calm")
        if sub == "stuck" and st["flat_run"] < 6:
            sh.append("stuck without flat run")
        if sub == "saturation" and st["max"] < V.METRICS[(role, r["metric"])]["hi"]:
            sh.append("saturation below rail")
        if sub == "dropout" and st["min"] != 0.0:
            sh.append("dropout min != 0")
        if r.get("small") and (t["pattern"] != "stable"):
            sh.append("boundary not stable")
        if t["pattern"] == "spike" and fam == "event" and not r.get("small") and st["max"] - sorted(r["hist"][-n:])[n // 2] <= 0:
            sh.append("spike without peak")
    (fail("shape", ",".join(sh)) if sh else ok("shape"))
    if r.get("gen_tokens") is not None:
        flags["gen_tokens"].append(r["gen_tokens"])
        flags["prompt_tokens"].append(r["prompt_tokens"])
        if r["gen_tokens"] > 70:
            flags["gen_over_70"] += 1
        if r["prompt_tokens"] > 900:
            flags["prompt_over_900"] += 1


NEG_FAMILIES = ("stable", "routine", "real_routine", "zero_idle")


def is_negative(r):
    return (r["family"] in NEG_FAMILIES or r.get("small") or
            (r["family"] == "hvac" and r.get("routine")) or (r["family"] == "occupancy" and r["pattern"] in ("vacant", "occupied")))


def fa_table(d):
    """Status != normal among the negative (calm / routine) rows per split and family: should be ~0 except the
    deliberate warning routines (short-cycling pump, off-hours drain) - those are listed separately."""
    out = {}
    for sp in ("train", "dev", "test"):
        c = defaultdict(lambda: [0, 0])
        for l in open(d / f"{sp}.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if not is_negative(r):
                continue
            k = f"{r['role']}/{r['family']}" + ("/boundary" if r.get("small") else "")
            c[k][1] += 1
            c[k][0] += r["status"] != "normal"
        out[sp] = {k: {"not_normal": v[0], "n": v[1]} for k, v in sorted(c.items())}
    return out


def balance(rows):
    t = defaultdict(Counter)
    for r in rows:
        t["role x pattern"][f"{r['role']}/{r['pattern']}"] += 1
        t["role x status"][f"{r['role']}/{r['status']}"] += 1
        t["role x family"][f"{r['role']}/{r['family']}"] += 1
        t["fault_kind"][str(r["fault_kind"])] += 1
        t["window n"][r["n"]] += 1
        d = r.get("d")
        t["age (readings since onset)"]["none" if d is None else "3-12 (<=1h)" if d <= 12 else "13-36 (1-3h)" if d <= 36 else ">36 (>3h)"] += 1
        s = r.get("size")
        t["size (x noise)"]["none" if s is None else "<3 boundary" if s < 3 else "3-6" if s < 6 else "6-9" if s < 9 else ">=9"] += 1
        t["confidence"][r["confidence"]] += 1
        t["event_active"][str(r["event_active"])] += 1
        t["seen"][r["seen"]] += 1
        t["status != normal (D3 alarm)"][str(r["status"] != "normal")] += 1
    return {k: dict(sorted(v.items(), key=lambda x: str(x[0]))) for k, v in t.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(GV.DATA / "sft_v2"))
    a = ap.parse_args()
    d = Path(a.data)
    HA.register()
    man = json.loads((d / "manifest.json").read_text())
    if (d / "node_limits.json").exists():
        V.NODE_LIMITS.update(json.loads((d / "node_limits.json").read_text()))
    heldout = man["heldout_nodes"]
    res = {k: [0, 0] for k in HARD}
    ex = defaultdict(list)
    flags = {"gen_tokens": [], "prompt_tokens": [], "obs_words": [], "gen_over_70": 0, "prompt_over_900": 0}
    seen = {}
    out = {"splits": {}}
    for sp in ("train", "dev", "test"):
        rows = [json.loads(l) for l in open(d / f"{sp}.jsonl", encoding="utf-8")]
        for r in rows:
            h = hashlib.sha256(r["prompt"].encode()).hexdigest()
            if h in seen:
                res["duplicates"][1] += 1
                ex["duplicates"].append(f"{r['id']} == {seen[h]}")
            else:
                res["duplicates"][0] += 1
                seen[h] = r["id"]
            check_row(r, heldout, res, flags, ex)
        out["splits"][sp] = {"n": len(rows), "balance": balance(rows)}
        print(f"{sp}: {len(rows)} rows checked", flush=True)
    w = sorted(flags["obs_words"])
    out["results"] = {k: {"pass": v[0], "fail": v[1], "examples": ex.get(k, [])} for k, v in res.items()}
    out["soft_flags"] = {"generated_tokens_over_70": flags["gen_over_70"], "prompt_tokens_over_900": flags["prompt_over_900"],
                         "observation_words": {"mean": round(sum(w) / len(w), 1), "p95": w[int(0.95 * (len(w) - 1))], "max": w[-1],
                                               "over_14": sum(1 for x in w if x > 14)}}
    out["all_hard_pass"] = all(v[1] == 0 for v in res.values())
    out["false_alarm_definition"] = "status != normal (D3)"
    out["false_alarm_label_rate"] = fa_table(d)
    (d / "checks.json").write_text(json.dumps(out, indent=1, default=str))
    L = ["# v2 dataset checks\n", f"all hard checks pass: **{out['all_hard_pass']}**\n", "| check | pass | fail |\n|---|---|---|\n"]
    for k, v in res.items():
        L.append(f"| {k} | {v[0]} | {v[1]} |\n")
    L.append(f"\nsoft flags: {json.dumps(out['soft_flags'])}\n")
    for k in HARD:
        if ex.get(k):
            L.append(f"\n## {k} failures (first {len(ex[k])})\n" + "".join(f"- {e}\n" for e in ex[k]))
    (d / "checks.md").write_text("".join(L), encoding="utf-8")
    print("".join(L[:3 + len(res) + 1]))


if __name__ == "__main__":
    main()
