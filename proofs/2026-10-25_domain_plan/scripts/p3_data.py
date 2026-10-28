"""P3 SFT file (PLAN.md P3): small top-up from mixA50, heavy replay.
  new (train months, seen nodes, teacher-labelled with the P1 label definition):
    hvac_story   : AC on in band, then +1-2 C/h, or 3.5-4.5 C/h held 2-4 buckets (stepped ingest) -> no_cooling_effect / too_hot
    hvac_events  : too_hot / slow_recovery / stuck_off / running_empty_room via hvac.make_case, daytime
    gd_flat      : v2 gradual_decrease events whose window has a flat run >= 6 readings (gradual vs flatline look-alikes)
    day_leak     : 3-4 h daytime tank drains with no refill (new definition: warning / possible_leak)
  replay: random v2 train rows (C1-dropped rows included, all families), >= 3x the new rows; daytime long-drain rows labelled
          normal under the old definition are dropped. De-duplicated by prompt against every eval file (dev3f, test, rw5, E1).
  python p3_data.py --out FILE [--hvac 450 --hvac-ev 200 --gd 400 --leak 150 --ratio 3]"""
import argparse, hashlib, json, random, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_stories as E  # noqa: E402
from e1_stories import GV, V, TE, HA, SRC, T, F, H  # noqa: E402

R3F = Path.home() / "smartcity_runs/agents_v2_topup3f"
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True)
ap.add_argument("--hvac", type=int, default=450); ap.add_argument("--hvac-ev", type=int, default=200)
ap.add_argument("--gd", type=int, default=400); ap.add_argument("--leak", type=int, default=150)
ap.add_argument("--ratio", type=float, default=3.0); ap.add_argument("--seed", type=int, default=5101)
a = ap.parse_args()
hsh = lambda p: hashlib.sha256(p.encode()).hexdigest()
seen = set()
for f in [R3F / "eval_dev/eval3e.jsonl", R3F / "eval_test/eval3e.jsonl", R3F / "eval_rw5dev/eval3e.jsonl", R3F / "eval_rw5test/eval3e.jsonl",
          Path("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/e1/eval3e.jsonl")]:
    seen |= {hsh(json.loads(l)["prompt"]) for l in open(f, encoding="utf-8")}
man0 = json.loads((SRC / "manifest.json").read_text()); heldout = dict(man0["heldout_nodes"])
kj = json.loads((SRC / "kthr.json").read_text()); kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text())); HA.register(); TE.build_calibration()


class TCtx(E.SCtx):  # train months only
    def _ends(self, key):
        if key not in self._ec:
            self._ec[key] = [(e, "train") for e in self.ends[key].get("train", []) if self.when(e)]
        return self._ec[key]


rng = random.Random(a.seed)
new, stats = [], Counter()


def add(r, bucket):
    if not r:
        return False
    h = hsh(r["prompt"])
    if h in seen:
        return False
    seen.add(h); r["p3_bucket"] = bucket; new.append(r); stats[bucket] += 1
    return True


# HVAC: train months, seen units
HA.MONTHS_TEST = HA.MONTHS["test"]; HA.MONTHS["test"] = HA.MONTHS["train"]   # hv_pool reads MONTHS["test"]
E.HV_CACHE.clear()
hv_fns = [E.ac_not_cooling(1.0, 2.0, 1), E.ac_not_cooling(3.5, 4.5, 2), E.ac_not_cooling(3.5, 4.5, 3), E.ac_not_cooling(3.0, 4.5, 4)]
tries = 0
while stats["hvac_story"] < a.hvac and tries < a.hvac * 200:
    tries += 1
    try:
        r = rng.choice(hv_fns)(rng, "seen", rng.choice(("day", "any")))
    except AssertionError:
        r = None
    if r and r["pattern"] in ("no_cooling_effect", "too_hot", "slow_recovery", "pull_down"):
        add(r, "hvac_story")
ev = [E.hv_case(p, run) for p, run in (("too_hot", True), ("slow_recovery", True), ("stuck_off", False), ("running_empty_room", True))]
tries = 0
while stats["hvac_events"] < a.hvac_ev and tries < a.hvac_ev * 200:
    tries += 1
    try:
        add(rng.choice(ev)(rng, "seen", "any"), "hvac_events")
    except AssertionError:
        pass
HA.MONTHS["test"] = HA.MONTHS_TEST
print("hvac", dict(stats), flush=True)

# continuous roles
for role, quota, bucket, fn, keyok, when in (
        ("water", a.leak, "day_leak", E.leak(36, 46), E.lvl, "day"),
        ("water", a.gd // 2, "gd_flat", lambda c, n: GV.gen_event(c, n, "gradual_decrease"), lambda k: True, "any"),
        ("power", a.gd // 4, "gd_flat", lambda c, n: GV.gen_event(c, n, "gradual_decrease"), lambda k: True, "any"),
        ("air_quality", a.gd - a.gd // 2 - a.gd // 4, "gd_flat", lambda c, n: GV.gen_event(c, n, "gradual_decrease"), lambda k: True, "any")):
    S, roles, ends = T.load_role(role)
    ctx = TCtx(S, ends, roles, heldout, "train", role, kthr, random.Random(f"p3|{role}|{bucket}|{a.seed}")).setup("seen", when, keyok)
    got, tries = 0, 0
    while got < quota and tries < quota * 400:
        tries += 1
        try:
            r = fn(ctx, rng.choice((48, 48, 96)))
        except (AssertionError, ZeroDivisionError):
            continue
        if not r:
            continue
        if bucket == "gd_flat":
            st = F.compute_stats(r["hist"][-r["n"]:], V.METRICS[(role, r["metric"])]["dec"])
            if r["pattern"] != "gradual_decrease" or st["flat_run"] < 6:
                continue
        if bucket == "day_leak" and r["likely_cause"] != "possible_leak":
            continue
        got += add(r, bucket)
    print(role, bucket, got, flush=True)

# replay
rep = [json.loads(l) for l in open(SRC / "train.jsonl", encoding="utf-8")]
rng.shuffle(rep)
need, out_rep, drop = int(a.ratio * len(new)), [], 0
import p1_rules as P  # noqa: E402
for r in rep:
    if len(out_rep) >= need:
        break
    if hsh(r["prompt"]) in seen:
        continue
    if r["role"] == "water" and r.get("metric") == "level" and r["pattern"] == "gradual_decrease" and r["likely_cause"] == "tank_draining":
        n = r["n"]; xs = r["hist"][-n:]; st = F.compute_stats(xs, V.METRICS[("water", "level")]["dec"])
        if not F.is_off_hours(r["end_epoch"]) and P.long_drain(xs, st["noise"]):
            drop += 1; continue
    r["p3_bucket"] = "replay"; out_rep.append(r)
rows = new + out_rep
rng.shuffle(rows)
with open(a.out, "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps({k: v for k, v in r.items() if k not in ("intended",)}, ensure_ascii=False, default=str) + "\n")
man = {"rows": len(rows), "new": dict(stats), "replay": len(out_rep), "replay_dropped_old_day_drain": drop,
       "new_labels": Counter(f"{r['p3_bucket']}:{r['pattern']}/{r['status']}" for r in new),
       "replay_roles": Counter(r["role"] for r in out_rep), "sha256_16": hashlib.sha256(Path(a.out).read_bytes()).hexdigest()[:16], "args": vars(a)}
Path(a.out).with_suffix(".manifest.json").write_text(json.dumps(man, indent=1, default=str))
print(f"P3 data {len(rows)} rows: new {dict(stats)}, replay {len(out_rep)} (dropped {drop} old-definition day drains) -> {a.out}")
