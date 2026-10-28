"""Seed library for the retrieval preliminary (2026-10-29). GENERATION, not evaluation.
  run   : python3 seed_run.py run --port P --tag T [--n 1000] [--until 0845]   finalized reasoner on balanced TRAIN-split incidents
  build : python3 seed_run.py build --tag T                                     valid outputs -> rag_seed.json (+ manifest)
Items: proofs/2026-10-25_reasoner_final/data/incidents_train.ok.jsonl only (no dev / test / RWH / P0 / E1 / gate-study items), balanced
by family (prompt-injection families excluded). Same prompt and tool loop as the board's reasoner v3 (run_v3.run_items).
Kept: parsed, and the app's validity checks clean (score_v3: no ungrounded number/time/date, no bad id, unit, direction,
severity-floor or schema error). Each seed = the structured vector + text of retrieval.go (SeedDoc), provenance "seed:<id>, model:<tag>"."""
import argparse, json, math, os, random, re, sys, time
from collections import Counter, defaultdict
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__))
RE = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_reasoner_final"
sys.path.insert(0, os.path.join(RE, "eval"))
ap = argparse.ArgumentParser(); ap.add_argument("step"); ap.add_argument("--port", type=int, default=18097); ap.add_argument("--tag", required=True)
ap.add_argument("--n", type=int, default=1000); ap.add_argument("--until", default="0845")
a = ap.parse_args()
OUT = os.path.join(HERE, f"gen_{a.tag}.jsonl")
rows = [json.loads(l) for l in open(os.path.join(RE, "data", "incidents_train.ok.jsonl"), encoding="utf-8")]
rows = [r for r in rows if "+inject" not in r["family"] and r.get("split", "train") == "train"]


def pick(rows, n):
    by = defaultdict(list)
    for r in rows:
        by[r["family"]].append(r)
    rng = random.Random(29)
    for v in by.values():
        rng.shuffle(v)
    out, i = [], 0
    while len(out) < n and any(i < len(v) for v in by.values()):
        for f in sorted(by):
            if i < len(by[f]) and len(out) < n:
                out.append(by[f][i])
        i += 1
    return out


sel = pick(rows, a.n)
if a.step == "run":
    import run_v3 as R
    cli = R.RB.Client(a.port, 1200)
    ist = lambda: int(datetime.utcfromtimestamp(time.time() + 19800).strftime("%H%M"))
    done = R.done_ids(OUT)
    todo = [r for r in sel if r["id"] not in done]
    print(f"seed run: {len(done)} done, {len(todo)} to do", flush=True)
    for k in range(0, len(todo), 20):
        if ist() >= int(a.until) and ist() < 1200:
            print("deadline reached", flush=True)
            break
        R.run_items(cli, todo[k:k + 20], OUT, 0)
        time.sleep(2)
    sys.exit(0)

# ---- build
import score_v3 as SV
recs = {}
for l in open(OUT):
    x = json.loads(l); recs[x["id"]] = x
byid = {r["id"]: r for r in sel}
RX_S = re.compile(r"^(S\d+) \[FLAGGED\]: (\S+) (\S+) \[[^\]]*\] at .*\((\w[\w ]*)\)\s*$", re.M)
RX_AG = re.compile(r"^  agent: pattern=(\S+) status=(\S+) cause=(\S+)", re.M)
RX_CTX = re.compile(r"CONTEXT: \w{3} \d+ \w{3} \d{4} (\d\d):(\d\d)")
LIM = {"air_quality/co2": 1500, "air_quality/pm25": 120, "air_quality/pm10": 250, "air_quality/temp": 34, "air_quality/rh": 85,
       "water/tds": 1000, "water/ph": 9.0, "power/pf": 0.7, "weather/temp": 42, "weather/rh": 97, "weather/wind": 15, "hvac/room_temp": 34}
FLOOR = {"air_quality/co2": 40, "air_quality/pm25": 6, "air_quality/pm10": 10, "air_quality/temp": 0.6, "air_quality/rh": 3, "water/level": 4,
         "water/flow": 0.4, "water/tds": 15, "water/ph": 0.25, "power/pf": 0.03, "weather/temp": 0.8, "weather/rh": 4, "weather/wind": 0.6}
NUM = r"(-?\d+(?:\.\d+)?)"


def bin_of(v, *edges):
    for i, e in enumerate(edges):
        if v < e:
            return i
    return len(edges)


def features(user):
    fl = RX_S.findall(user)
    if not fl:
        return None
    ref, node, metric, role = fl[0]
    role = role.strip().replace(" ", "_")
    blk = user[user.index(f"{ref} [FLAGGED]"):]
    nxt = re.search(r"^S\d+ \[", blk[5:], re.M)
    blk = blk[: 5 + nxt.start()] if nxt else blk
    ag = RX_AG.search(blk)
    if not ag:
        return None
    pat, st, cause = ag.groups()
    last = re.search(rf"{ref}\.E1 (?:last|room now|current state) = ?{NUM}", blk)
    half = re.search(rf"{ref}\.E7 halves {NUM} -> ", blk)
    noise = re.search(rf"{ref}\.E8 noise {NUM}", blk)
    mag = pct = 0
    if last and half:
        lv, hv = float(last.group(1)), float(half.group(1))
        sd = max(float(noise.group(1)) if noise else 0.0, FLOOR.get(f"{role}/{metric}", 0.0), 1e-9)
        mag = bin_of(abs(lv - hv) / sd, 2, 4, 8, 16)
        if f"{role}/{metric}" in LIM:
            pct = 1 + bin_of(lv / LIM[f"{role}/{metric}"], 0.6, 0.8, 1.0, 1.2)
    ctx = RX_CTX.search(user)
    tod = int(ctx.group(1)) // 4 if ctx else 0
    sev = {"warn": "warning"}.get(st, st)
    return {"role": role, "metric": metric, "domains": sorted({x[3].strip().replace(" ", "_") for x in fl}), "pattern": pat, "status": sev,
            "cause": cause, "mag_bin": mag, "pct_bin": pct, "tod_bin": tod, "n_sensors": min(3, len(fl))}


seeds, why = [], Counter()
for i, rec in recs.items():
    row = byid.get(i)
    if not row:
        continue
    o = SV.score_incident(row, rec)
    if not o.get("parsed"):
        why["unparsed"] += 1; continue
    if any(o.get(k) for k in ("ungrounded", "bad_id", "unit_err", "direction_err", "floor_viol", "schema_err", "title_conflict")):
        why["invalid"] += 1; continue
    rep = SV.parse((rec.get("final") or {}).get("content"))
    f = features(row["messages"][1]["content"])
    if not f:
        why["no_features"] += 1; continue
    txt = [rep.get("title", ""), rep.get("root_cause", ""), rep.get("label", "")] + [x.get("text", "") for x in rep.get("observations") or [] if isinstance(x, dict)]
    txt += [f["pattern"], f["cause"]]
    acts = [c.get("action") for c in rep.get("checklist") or [] if isinstance(c, dict) and c.get("action")]
    seeds.append(dict(id=f"seed:{i}", provenance=f"seed:{i}, model:{a.tag}", text=" ".join(t for t in txt if t), severity=rep.get("severity", ""),
                      label=rep.get("label", ""), action=acts[0] if acts else "", root_cause=rep.get("root_cause", ""), **f))
    why["kept"] += 1
json.dump(seeds, open(os.path.join(HERE, "rag_seed.json"), "w"), indent=0)
man = {"tag": a.tag, "generated": len(recs), "selected": len(sel), "outcome": why, "roles": Counter(s["role"] for s in seeds),
       "severities": Counter(s["severity"] for s in seeds), "families": len({byid[s["id"][5:]]["family"] for s in seeds})}
json.dump(man, open(os.path.join(HERE, "manifest.json"), "w"), indent=1)
print("seed build", json.dumps(man)[:400])
