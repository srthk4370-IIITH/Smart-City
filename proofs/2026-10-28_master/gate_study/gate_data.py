"""Gate-length study data (2026-10-28): the SAME event (same node, window end, size, shape draws) generated with the event
having lasted k = 3..8 readings (training/v2 generators, d forced to k; every other random draw identical across k), teacher
gold at each k. Test + Sep-Oct months, seen and held-out nodes, 4 h window (n = 48).
Shapes: spike, step, trend, flatline (stuck), noisy (noise_increase fault), fault (bias / dropout); roles air_quality, water,
power, weather.   python gate_data.py --out DIR [--groups 20]  -> DIR/eval3e.jsonl (+ manifest.json)"""
import argparse, hashlib, json, random, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
import e1_stories as E  # noqa: E402
from e1_stories import GV, V, TE, HA, SRC, T  # noqa: E402

KS = (3, 4, 5, 6, 7, 8)
SHAPES = {
    "spike": lambda c, n, i: GV.gen_event(c, n, "spike"),
    "step": lambda c, n, i: GV.gen_event(c, n, ("step_increase", "step_decrease")[i % 2]),
    "trend": lambda c, n, i: GV.gen_event(c, n, ("gradual_increase", "gradual_decrease")[i % 2]),
    "flatline": lambda c, n, i: GV.gen_fault(c, n, "stuck"),
    "noisy": lambda c, n, i: GV.gen_fault(c, n, "noise_increase"),
    "fault": lambda c, n, i: GV.gen_fault(c, n, ("bias", "dropout")[i % 2]),
}
ROLES = ("air_quality", "water", "power", "weather")
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--groups", type=int, default=20)
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
man0 = json.loads((SRC / "manifest.json").read_text()); heldout = dict(man0["heldout_nodes"])
kj = json.loads((SRC / "kthr.json").read_text()); kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text())); HA.register(); TE.build_calibration()
orig_sd = GV.sample_d
rows, stats = [], Counter()
for role in ROLES:
    S, roles, ends = T.load_role(role)
    for shape, fn in SHAPES.items():
        got, seed = 0, 0
        while got < a.groups and seed < a.groups * 60:
            seed += 1
            tag = ("seen", "unseen")[seed % 2]
            grp = []
            for k in KS:
                GV.sample_d = lambda rng, n, dmin=3, k=k: k
                ctx = E.SCtx(S, ends, roles, heldout, "test", role, kthr, random.Random(f"gate|{role}|{shape}|{seed}")).setup(tag, "any", lambda kk: True)
                r = None
                for _ in range(300):
                    try:
                        r = fn(ctx, 48, seed)
                    except (AssertionError, ZeroDivisionError):
                        r = None
                    if r:
                        break
                if not r:
                    break
                grp.append((k, r))
            GV.sample_d = orig_sd
            if len(grp) != len(KS) or len({(r["node"], r["metric"], r["end_epoch"]) for _, r in grp}) != 1:
                stats["group_mismatch"] += 1
                continue
            gid = f"{role}-{shape}-{seed}"
            for k, r in grp:
                r.update(id=f"gate-{gid}-k{k}", group=gid, shape=shape, k=k, slices_all=["gate", f"shape_{shape}", f"k{k}", role])
                rows.append(r)
            got += 1
        stats[f"{role}/{shape}"] = got
        print(role, shape, got, flush=True)
with open(out / "eval3e.jsonl", "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
gold = Counter(f"{r['shape']}:k{r['k']}:{r['pattern']}/{r['status']}" for r in rows)
(out / "manifest.json").write_text(json.dumps({"rows": len(rows), "groups": stats, "gold": gold,
                                               "sha256_16": hashlib.sha256((out / "eval3e.jsonl").read_bytes()).hexdigest()[:16]}, indent=1))
print(f"gate study rows {len(rows)} ({len(rows) // len(KS)} groups x {len(KS)} k), mismatched groups {stats['group_mismatch']}")
