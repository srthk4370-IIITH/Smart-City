"""rsn_v3 incident training set (local, stdlib python3): the UNCHANGED round-1 generator (pipeline/gen_incidents.py make())
at a new seed, aimed at rsn_v1's weak families, verified with the round-1 verify.py, written to --out (round-1 data/ is
never written).
1. pool: --pool rows drawn with the round-1 family weights (1.0 / 1.6) except WEAK families x3; real-agent rows keep the
   round-1 share but only re-use real_pool rows that round 1 already trained on (matched by node + evidence lines in
   round-1 incidents_train.ok.jsonl; precedent: round-2 UPLOAD_MANIFEST), never the held-out (RWH) rows.
2. verify.py check_incident on every row; failures dropped.
3. drop rows whose user message equals one in round-1 incidents_dev / incidents_rwh (no eval leakage).
4. weighted selection without replacement to --target rows: weight 3 for rows with the "+tool:" or "+inject" modifier
   (rsn_v1 weak on tool/inject variants), 1 otherwise; + all round-1 borderline rows (incidents_border.ok.jsonl, 600).
5. build_mix.fix (short incident system prompt, dict tool args) -> incidents3_train.jsonl; incidents_dev60.jsonl (round-1
   dev rows, loss curve only); incidents3_report.json (family counts before/after, real-row provenance, md5).
  python3 gen_incidents_v3.py --out DIR [--seed 31] [--pool 26000] [--target 12000]"""
import argparse
import collections
import hashlib
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
R1 = os.path.abspath(os.path.join(HERE, "..", "..", "2026-10-25_reasoner_final"))
sys.path.insert(0, os.path.join(R1, "pipeline"))
import gen_incidents as G  # noqa: E402
import families as F  # noqa: E402
import verify as V  # noqa: E402
from build_mix import fix  # noqa: E402

WEAK = ["single_glitch", "drift_low", "insufficient", "recovery_gap", "stale_related", "coincidence", "class_fills", "acidic", "chatter",
        "outage", "indoor_emission", "agent_miss"]
R1_BOOST = ["ac_fail_hot", "slow_leak", "dust_ingress", "co2_glitch", "acidic", "stale_related", "insufficient", "coincidence",
            "agent_miss", "contradict", "holiday_low", "class_fills"]


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def base_family(f):
    return f.split(":")[0].split("+")[0]


def used_pool_rows(pool, r1_rows):
    """real_pool train rows that round 1 trained on: node and every evidence line appear in one real_agent prompt"""
    texts = collections.defaultdict(list)
    for r in r1_rows:
        if r["family"].startswith("real_agent"):
            u = r["messages"][1]["content"]
            for tok in set(x for x in u.split() if x.count("-") >= 3):
                texts[tok.strip("(),:;")].append(u)
    used = []
    for p in pool:
        cands = texts.get(p["node"], [])
        evs = [e[1] for e in p["ev"]][:4]
        if any(all(e in u for e in evs) for u in cands):
            used.append(p)
    return used


FILLER = re.compile(r"\b(?:currently|clearly|approximately|roughly|just|still|also|so far|right now|at the moment|basically|"
                    r"actually|really|quite|very)\s+", re.I)


def _balance(t):
    for o, c in (("(", ")"), ("[", "]")):
        if t.count(o) > t.count(c):
            t += c
    return t


def shorten(t, n):
    """filler words out; then whole sentences, then a clause boundary, then a word boundary, until <= n characters"""
    t = re.sub(r"\s{2,}", " ", FILLER.sub("", t or "")).strip()
    if len(t) <= n:
        return t
    acc = ""
    for p in re.split(r"(?<=[.!?])\s+", t):
        if len((acc + " " + p).strip()) > n:
            break
        acc = (acc + " " + p).strip()
    if acc:
        return acc
    cut = max(t.rfind(s, 0, n) for s in (", ", "; ", " - ", ": ", " ("))
    if cut >= int(n * 0.4):
        return _balance(t[:cut].rstrip(" ,;:-("))
    return _balance(t[:n].rsplit(" ", 1)[0].rstrip(" ,;:-("))


def compact_report(rep):
    """same keys, enums, ids and srcs; fewer words: <= 3 observations (<= 70 chars), checklist why <= 60, explanation <= 120,
    filler-free root_cause / causal_chain"""
    rep = dict(rep)
    obs = [dict(o, text=shorten(o.get("text", ""), 70)) for o in (rep.get("observations") or [])[:3]]
    rep["observations"] = obs
    rep["checklist"] = [dict(c, why=shorten(c.get("why", ""), 60)) if "why" in c else c for c in rep.get("checklist") or []]
    rep["explanation"] = shorten(rep.get("explanation", ""), 120)
    for k in ("root_cause", "causal_chain"):
        if isinstance(rep.get(k), str):
            rep[k] = re.sub(r"\s{2,}", " ", FILLER.sub("", rep[k])).strip()
    return rep


def make_rwh2(a, r1, pool_path, exclude):
    """held-out RWH-2: new seed, held-out nodes/real rows (split heldout, like RWH), families balanced (equal weight each,
    real-agent at the round-1 share), verify.py pass, no overlap with train/dev/RWH. Original (non-compact) gold."""
    heldpool = [r for r in load(pool_path) if r["split"] == "heldout"]
    fams = list(F.FAMILIES)
    kinds = fams + ["real"]
    wts = [1.0] * len(fams) + [len(fams) * 0.45]
    R = random.Random(a.rwh2_seed)
    out, seen, tries = [], set(exclude), 0
    while len(out) < a.rwh2 and tries < a.rwh2 * 20:
        tries += 1
        ex = G.make(R, R.choices(kinds, wts)[0], "heldout", heldpool)
        u = ex["messages"][1]["content"]
        if u in seen or V.check_incident(ex):
            continue
        seen.add(u)
        ex["id"] = "rwh2-%05d" % len(out)
        out.append(ex)
    d = os.path.join(a.out, "..", "heldout")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "incidents_rwh2.jsonl"), "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    c = collections.Counter(base_family(r["family"]) for r in out)
    json.dump({"rows": len(out), "seed": a.rwh2_seed, "families": dict(c.most_common())}, open(os.path.join(d, "rwh2_report.json"), "w"), indent=1)
    print("RWH-2: %d rows, %d families" % (len(out), len(c)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--pool", type=int, default=26000)
    ap.add_argument("--target", type=int, default=12000)
    ap.add_argument("--weak-mult", type=float, default=3.0)
    ap.add_argument("--mod-mult", type=float, default=3.0, help="selection weight of +tool / +inject rows")
    ap.add_argument("--real-share", type=float, default=0.45, help="real-agent weight / sum of family weights (round 1: 0.45)")
    ap.add_argument("--no-chatter", action="store_true", help="exclude the chatter family (round 2 did; see report)")
    ap.add_argument("--no-compact", action="store_true", help="keep the generator's full gold text")
    ap.add_argument("--rwh2", type=int, default=0, help="also write heldout/incidents_rwh2.jsonl with this many rows (never trained on)")
    ap.add_argument("--rwh2-seed", type=int, default=4242)
    a = ap.parse_args()
    assert a.seed != 7, "seed 7 is round 1's"
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    D1 = os.path.join(R1, "data")
    r1_train = load(os.path.join(D1, "incidents_train.ok.jsonl"))
    pool = [r for r in load(os.path.join(D1, "real_pool.jsonl")) if r["split"] == "train"]
    used = used_pool_rows(pool, r1_train)
    print("real_pool: %d train rows, %d matched to round-1 training rows (only these are re-used)" % (len(pool), len(used)), flush=True)
    fams = list(F.FAMILIES)
    w = {k: (1.6 if k in R1_BOOST else 1.0) for k in fams}
    for k in WEAK:
        w[k] *= a.weak_mult
    if a.no_chatter:
        w["chatter"] = 0.0
    kinds = fams + ["real"]
    wts = [w[k] for k in fams] + [sum(w.values()) * a.real_share]   # round 1: 0.45 x the family weight sum (31 % of rows)
    R = random.Random(a.seed)
    rows, bad = [], collections.Counter()
    for i in range(a.pool):
        kind = R.choices(kinds, wts)[0]
        ex = G.make(R, kind, "train", used)
        ex["id"] = "inc3-%06d" % i
        e = V.check_incident(ex)
        if e:
            for x in set(y.split(":")[0] for y in e):
                bad[x] += 1
            continue
        rows.append(ex)
        if (i + 1) % 5000 == 0:
            print("  generated %d (%d pass) %.0f s" % (i + 1, len(rows), time.time() - t0), flush=True)
    npool = len(rows)
    held = set()
    for n in ("incidents_dev.ok.jsonl", "incidents_rwh.ok.jsonl", "incidents_dev.jsonl", "incidents_rwh.jsonl"):
        for r in load(os.path.join(D1, n)):
            held.add(r["messages"][1]["content"])
    seen, dedup = set(), []
    leak = dup = 0
    for r in rows:
        u = r["messages"][1]["content"]
        if u in held:
            leak += 1
            continue
        if u in seen:
            dup += 1
            continue
        seen.add(u)
        dedup.append(r)
    border = load(os.path.join(D1, "incidents_border.ok.jsonl"))
    need = max(0, a.target - len(border))
    keyed = []
    for r in dedup:
        wt = a.mod_mult if ("+tool:" in r["family"] or "+inject" in r["family"]) else 1.0
        keyed.append((R.random() ** (1.0 / wt), r))          # Efraimidis-Spirakis weighted sampling w/o replacement
    keyed.sort(key=lambda x: -x[0])
    pick = [r for _, r in keyed[:need]] + border
    R.shuffle(pick)
    # compact gold text (owner-approved latency change): deterministic, re-verified; a row whose compact form fails verify keeps
    # its original text
    cstats = collections.Counter()
    samples = []
    if not a.no_compact:
        for r in pick:
            orig = r["messages"][-1]["content"]
            new = json.dumps(compact_report(json.loads(orig)), ensure_ascii=False)
            if new == orig:
                cstats["unchanged"] += 1
                continue
            r2 = dict(r, messages=r["messages"][:-1] + [dict(r["messages"][-1], content=new)])
            if V.check_incident(r2):
                cstats["kept_original_verify_fail"] += 1
                continue
            if len(samples) < 1500 and R.random() < 0.1:
                samples.append([orig, new])
            r["messages"] = r2["messages"]
            cstats["compacted"] += 1
        json.dump(samples, open(os.path.join(a.out, "compact_samples.json"), "w"), ensure_ascii=False)
    out = [fix(dict(r)) for r in pick]
    if a.rwh2:
        make_rwh2(a, R1, os.path.join(D1, "real_pool.jsonl"), held | seen)
    p_train = os.path.join(a.out, "incidents3_train.jsonl")
    with open(p_train, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    devrows = [fix(dict(r)) for r in load(os.path.join(D1, "incidents_dev.ok.jsonl"))[:60]]
    with open(os.path.join(a.out, "incidents_dev60.jsonl"), "w", encoding="utf-8") as f:
        for r in devrows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def comp(rs):
        c = collections.Counter(base_family(r["family"]) for r in rs)
        c["+tool (any family)"] = sum(1 for r in rs if "+tool:" in r["family"])
        c["+inject (any family)"] = sum(1 for r in rs if "+inject" in r["family"])
        return dict(sorted(c.items(), key=lambda x: -x[1]))
    rep = {"seed": a.seed, "pool_generated": a.pool, "pool_verified": npool, "verify_fail_reasons": dict(bad), "leak_vs_dev_rwh": leak,
           "duplicates": dup, "border_rows": len(border), "rows": len(out), "weights": {"weak_mult": a.weak_mult, "mod_mult": a.mod_mult,
           "weak": WEAK, "chatter": not a.no_chatter}, "real_pool_rows_used_by_round1": len(used),
           "composition_round1": comp(r1_train), "composition_v3": comp(pick), "composition_v3_without_border": comp([r for r in pick if r not in border]),
           "compact": dict(cstats), "md5": hashlib.md5(open(p_train, "rb").read()).hexdigest(), "seconds": round(time.time() - t0)}
    json.dump(rep, open(os.path.join(a.out, "incidents3_report.json"), "w"), indent=1)
    print("incidents3: %d rows (pool %d -> verified %d, leak %d, dup %d, border %d) in %.0f s" % (len(out), a.pool, npool, leak, dup,
                                                                                               len(border), time.time() - t0))


if __name__ == "__main__":
    main()
