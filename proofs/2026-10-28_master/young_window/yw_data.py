"""Young-window top-up data (2026-10-28). Events that have lasted k = 3..7 readings, all six gate-study shapes
(spike, step, trend, flatline, noisy, fault) x four roles, balanced, from TRAIN months on seen nodes (the gate study and
dev3f / E1 use test + Sep-Oct months; prompts are also de-duplicated against every eval file). Teacher gold at each k.
  new   : python yw_data.py new --per 30 --val 8   -> ~/smartcity_runs/agents_yw/data/{new_train,new_val}.jsonl
  build : python yw_data.py build --ratio 3       -> train_yw.jsonl = new_train + B50-correct replay (pool answered by B50)"""
import argparse, hashlib, json, random, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
H = Path.home() / "smartcity_runs"; OUT = H / "agents_yw/data"; POOL = H / "agents_p3/pool"
R3F = H / "agents_v2_topup3f"
ap = argparse.ArgumentParser(); ap.add_argument("step"); ap.add_argument("--per", type=int, default=30)
ap.add_argument("--val", type=int, default=8); ap.add_argument("--ratio", type=float, default=3.0)
ap.add_argument("--pool", default=str(POOL))
a = ap.parse_args(); OUT.mkdir(parents=True, exist_ok=True); POOL = Path(a.pool)
hsh = lambda p: hashlib.sha256(p.encode()).hexdigest()
if a.step == "new":
    import e1_stories as E
    from e1_stories import GV, V, TE, HA, SRC, T
    seen = set()
    for f in [R3F / "eval_dev/eval3e.jsonl", R3F / "eval_test/eval3e.jsonl", R3F / "eval_rw5dev/eval3e.jsonl", R3F / "eval_rw5test/eval3e.jsonl",
              Path("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/e1/eval3e.jsonl"),
              Path("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/gate_study/eval3e.jsonl")]:
        if f.exists():
            seen |= {hsh(json.loads(l)["prompt"]) for l in open(f, encoding="utf-8")}
        else:
            print("missing eval file (skipped in de-dup):", f, flush=True)
    gate_keys = {(json.loads(l)["node"], json.loads(l)["end_epoch"]) for l in open("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/gate_study/eval3e.jsonl")}
    man0 = json.loads((SRC / "manifest.json").read_text()); heldout = dict(man0["heldout_nodes"])
    kj = json.loads((SRC / "kthr.json").read_text()); kthr = defaultdict(lambda: 99, {tuple(k.split("/")): v["thr"] for k, v in kj.items()})
    V.NODE_LIMITS.update(json.loads((SRC / "node_limits.json").read_text())); HA.register(); TE.build_calibration()

    class TCtx(E.SCtx):  # train months only
        def _ends(self, key):
            if key not in self._ec:
                self._ec[key] = [(e, "train") for e in self.ends[key].get("train", []) if self.when(e)]
            return self._ec[key]
    SH = {"spike": lambda c, n, i: GV.gen_event(c, n, "spike"),
          "step": lambda c, n, i: GV.gen_event(c, n, ("step_increase", "step_decrease")[i % 2]),
          "trend": lambda c, n, i: GV.gen_event(c, n, ("gradual_increase", "gradual_decrease")[i % 2]),
          "flatline": lambda c, n, i: GV.gen_fault(c, n, "stuck"),
          "noisy": lambda c, n, i: GV.gen_fault(c, n, "noise_increase"),
          "fault": lambda c, n, i: GV.gen_fault(c, n, ("bias", "dropout")[i % 2])}
    orig = GV.sample_d
    rows, st = {"train": [], "val": []}, Counter()
    for role in ("air_quality", "water", "power", "weather"):
        S, roles, ends = T.load_role(role)
        for shape, fn in SH.items():
            for split, quota in (("train", a.per), ("val", a.val)):
                got, i = 0, 0
                while got < quota and i < quota * 80:
                    i += 1
                    k = 3 + i % 5
                    GV.sample_d = lambda rng, n, dmin=3, k=k: k
                    ctx = TCtx(S, ends, roles, heldout, "train", role, kthr, random.Random(f"yw|{split}|{role}|{shape}|{i}")).setup("seen", "any", lambda kk: True)
                    r = None
                    for _ in range(200):
                        try:
                            r = fn(ctx, 48, i)
                        except (AssertionError, ZeroDivisionError):
                            r = None
                        if r:
                            break
                    GV.sample_d = orig
                    if not r or hsh(r["prompt"]) in seen or (r["node"], r["end_epoch"]) in gate_keys:
                        continue
                    seen.add(hsh(r["prompt"]))
                    r.update(id=f"yw-{split}-{role}-{shape}-{i}", shape=shape, k=k, type="sft", yw=True, slices_all=["yw", f"shape_{shape}", f"k{k}"])
                    rows[split].append(r); got += 1
                st[f"{split}/{role}/{shape}"] = got
            print(role, shape, st[f"train/{role}/{shape}"], st[f"val/{role}/{shape}"], flush=True)
    for split in rows:
        with open(OUT / f"new_{split}.jsonl", "w", encoding="utf-8") as fh:
            for r in rows[split]:
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(f"new: train {len(rows['train'])} val {len(rows['val'])}, k {dict(Counter(r['k'] for r in rows['train']))}")
else:
    new = [json.loads(l) for l in open(OUT / "new_train.jsonl", encoding="utf-8")]
    S = {}
    for l in open(POOL / "eval/B50Q/samples.jsonl"):
        s = json.loads(l); S.setdefault(s["id"], s)
    pool = {json.loads(l)["id"]: json.loads(l) for l in open(POOL / "eval3e.jsonl", encoding="utf-8")}
    ok = [pool[i] for i, s in S.items() if s.get("pattern") and s.get("status") and s.get("cause") and i in pool]
    random.Random(7301).shuffle(ok)
    rep = [dict(r, type="sft", yw=False) for r in ok[: int(a.ratio * len(new))]]
    rows = new + rep
    for r in rows:
        r.pop("slices_all", None)
    random.Random(7302).shuffle(rows)
    p = OUT / "train_yw.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    man = {"rows": len(rows), "new": len(new), "replay_b50_correct": len(rep), "pool_answered": len(S), "pool_correct": len(ok),
           "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}
    p.with_suffix(".manifest.json").write_text(json.dumps(man, indent=1))
    print("train_yw", man)
