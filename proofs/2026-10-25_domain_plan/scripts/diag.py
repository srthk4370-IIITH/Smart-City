"""Diagnosis of the P2/P3 gate (CPU). For each candidate vs mixA50 (both + P1 rules, new leak gold) on dev3f and E1:
  - per-slice wins/losses (pattern/status/cause) with an exact two-sided sign test p
  - gate false-fail rate under H0 (equal models): randomly swap each discordant pair's ref/cand (5,000 permutations),
    re-apply the E2 gate (flat drift <= 0, no fixed slice net loss > 1) -> fraction failing
  - proposed gate: paired bootstrap 95% CI of the total net (pattern+status+cause wins - losses) and of a severity-weighted
    net (status errors on gold warning/critical/sensor_fault rows x3), Holm-corrected sign tests per fixed slice (fail only
    if a slice is significantly worse at alpha 0.05 after Holm).
  python diag.py TAG [TAG ...] -> diag/<TAG>.json + 3 lines per tag"""
import json, math, random, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dp_lib as D  # noqa: E402
import p1_rules as P  # noqa: E402

E1 = Path("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/e1")
OUT = E1.parent / "diag"; OUT.mkdir(exist_ok=True)
RULES = D.expand("ALL_P1"); KEYS = ("pattern", "status", "cause")
FIXED = ("compound", "water_unseen", "gold_gradual_decrease", "hvac", "fam_real_routine", "fam_water_fill", "fam_routine")
rng = random.Random(7)


def binom_p(w, l):
    n = w + l
    if n == 0:
        return 1.0
    k = min(w, l)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def load(d, ref_tag, tag):
    rw = D.load_rows(d / "eval3e.jsonl"); P.regold(rw)
    ref = {i: v[0] for i, v in D.ruled(rw, D.load_samples(d / "eval" / ref_tag / "samples.jsonl"), RULES).items()}
    cand = {i: v[0] for i, v in D.ruled(rw, D.load_samples(d / "eval" / tag / "samples.jsonl"), RULES).items()}
    ids = [i for i in ref if i in cand]
    return rw, ref, cand, ids


def gate_fail(rw, pairs):
    t, fd = D.paired(rw, {i: a for i, a, b in pairs}, {i: b for i, a, b in pairs})
    bad = [1 for s in FIXED if s in t for k in KEYS if t[s][k][3] - t[s][k][4] < -1]
    return fd["net"] > 0 or bool(bad)


def sev(r, s):
    return 3 if s["gold_status"] in ("warning", "critical", "sensor_fault") else 1


def analyse(name, d, ref_tag, tag):
    rw, ref, cand, ids = load(d, ref_tag, tag)
    pairs = [(i, ref[i], cand[i]) for i in ids]
    t, fd = D.paired(rw, ref, cand)
    sl = {}
    for s, v in t.items():
        if v["pattern"][0] < 15:
            continue
        w = sum(v[k][3] for k in KEYS); l = sum(v[k][4] for k in KEYS)
        sl[s] = {"n": v["pattern"][0], "wins": w, "losses": l, "p": round(binom_p(w, l), 4)}
    # permutation null for the old gate: swap within each row (cand<->ref) at random
    nf = 0
    for _ in range(1000):
        pp = [(i, b, a) if rng.random() < 0.5 else (i, a, b) for i, a, b in pairs]
        nf += gate_fail(rw, pp)
    # bootstrap of total / severity nets
    rows_net = []
    for i, a, b in pairs:
        n = sum(bool(b.get(k)) - bool(a.get(k)) for k in KEYS)
        rows_net.append((n, n * sev(rw[i], a)))
    def ci(idx):
        bs = []
        for _ in range(2000):
            smp = [rows_net[rng.randrange(len(rows_net))][idx] for _ in rows_net]
            bs.append(sum(smp))
        bs.sort(); return sum(r[idx] for r in rows_net), bs[50], bs[1949]
    tot, sevw = ci(0), ci(1)
    holm = sorted(((sl[s]["p"], s) for s in FIXED if s in sl and sl[s]["losses"] > sl[s]["wins"]))
    worse = [s for k, (p, s) in enumerate(holm) if p < 0.05 / (len(holm) - k)]
    res = {"set": name, "tag": tag, "n": len(pairs), "flat": fd, "slices": sl, "old_gate_fail_under_H0": nf / 1000,
           "old_gate_fails_here": gate_fail(rw, pairs), "total_net": tot, "sev_net": sevw, "holm_worse_slices": worse,
           "new_gate_pass_point": tot[0] > 0 and sevw[0] >= 0 and not worse, "new_gate_pass_ci": tot[1] > 0 and not worse}
    return res


if __name__ == "__main__":
    for tag in sys.argv[1:]:
        out = []
        for name, d, rt in (("dev", D.L.SETS["dev"], "mixA50"), ("e1", E1, "mixA50cuda")):
            if not (d / "eval" / tag / "samples.jsonl").exists():
                continue
            r = analyse(name, d, rt, tag); out.append(r)
            top = sorted(r["slices"].items(), key=lambda x: x[1]["wins"] - x[1]["losses"])
            print(f"{tag} {name} n{r['n']}: net {r['total_net'][0]:+d} CI[{r['total_net'][1]:+d},{r['total_net'][2]:+d}] sev {r['sev_net'][0]:+d} "
                  f"flat{r['flat']['net']:+d} | old gate fails here={r['old_gate_fails_here']} H0-false-fail={r['old_gate_fail_under_H0']:.2f} | "
                  f"Holm-worse {r['holm_worse_slices']} | worst {[(s, v['wins'], v['losses'], v['p']) for s, v in top[:3]]} best {[(s, v['wins'], v['losses']) for s, v in top[-3:]]}")
        json.dump(out, open(OUT / f"{tag}.json", "w"), indent=1, default=str)
