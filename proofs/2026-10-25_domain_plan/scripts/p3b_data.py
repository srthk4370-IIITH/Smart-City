"""P3b replay fix. Two steps:
  pool  : 7,000 random v2-train rows (no eval duplicates, no old-definition day drains) -> ~/smartcity_runs/agents_p3/pool/eval3e.jsonl
          (host_eval3e format) so mixA50 can answer them on the GPU.
  build : replay = pool rows mixA50 answers right on pattern+status+cause (raw output, = train_3e's "replay rows the reference
          answers correctly"), 3,600 of them, + the 1,200 new P3 rows -> train_p3b.jsonl (+ manifest).
  python p3b_data.py pool | build"""
import hashlib, json, random, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
H = Path.home() / "smartcity_runs"; POOL = H / "agents_p3/pool"; P3 = H / "agents_p3/data"
SRC = Path("/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/data/sft_v2/train.jsonl")
step = sys.argv[1]
if step == "pool":
    new = [json.loads(l) for l in open(P3 / "train_p3.jsonl")]
    used = {r["id"] for r in new if r.get("p3_bucket") == "replay"}
    seen = {hashlib.sha256(r["prompt"].encode()).hexdigest() for r in new}
    import dp_lib as D  # noqa: F401  (path setup)
    import p1_rules as P
    F, V = P.F, P.L.F
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    random.Random(5102).shuffle(rows)
    out, drop = [], 0
    for r in rows:
        if len(out) >= 7000:
            break
        if hashlib.sha256(r["prompt"].encode()).hexdigest() in seen:
            continue
        if r["role"] == "water" and r.get("metric") == "level" and r["pattern"] == "gradual_decrease" and r["likely_cause"] == "tank_draining":
            xs = r["hist"][-r["n"]:]
            if not F.is_off_hours(r["end_epoch"]) and P.long_drain(xs, P.L.F.compute_stats(xs, P.L.F.METRICS[("water", "level")]["dec"])["noise"]):
                drop += 1; continue
        r["slices_all"] = ["ALL", "pool"]
        out.append(r)
    POOL.mkdir(parents=True, exist_ok=True)
    with open(POOL / "eval3e.jsonl", "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"pool {len(out)} rows (dropped {drop} old day drains), roles {dict(Counter(r['role'] for r in out))}")
else:
    S = {}
    for l in open(POOL / "eval/mixA50cuda/samples.jsonl"):
        s = json.loads(l); S.setdefault(s["id"], s)
    pool = {json.loads(l)["id"]: json.loads(l) for l in open(POOL / "eval3e.jsonl", encoding="utf-8")}
    ok = [pool[i] for i, s in S.items() if s.get("pattern") and s.get("status") and s.get("cause") and i in pool]
    random.Random(5103).shuffle(ok)
    rep = ok[:3600]
    new = [json.loads(l) for l in open(P3 / "train_p3.jsonl") if json.loads(l).get("p3_bucket") != "replay"]
    rows = new + [dict(r, p3_bucket="replay_ok", type="sft") for r in rep]
    for r in rows:
        r.setdefault("type", "sft"); r.pop("slices_all", None)
    random.Random(5104).shuffle(rows)
    p = P3 / "train_p3b.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    man = {"rows": len(rows), "new": len(new), "replay_correct": len(rep), "pool_answered": len(S), "pool_correct": len(ok),
           "replay_roles": Counter(r["role"] for r in rep), "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16]}
    p.with_suffix(".manifest.json").write_text(json.dumps(man, indent=1))
    print(f"train_p3b {len(rows)} rows: new {len(new)} + replay {len(rep)} (mixA50 right on {len(ok)}/{len(S)} pool rows)")
