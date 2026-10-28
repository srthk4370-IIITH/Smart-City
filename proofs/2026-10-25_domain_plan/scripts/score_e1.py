"""Score E1 stories: TAG(s) + rules vs story gold (teacher) and intended label; claim flags. Writes e1/score_<TAG>_<rules>.json
  python score_e1.py --tags mixA50 v21 [--rules ALL] [--e1 DIR]"""
import argparse, json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dp_lib as D  # noqa: E402
import p1_rules  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("--tags", nargs="+", required=True); ap.add_argument("--rules", default="ALL")
ap.add_argument("--e1", default="/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/e1"); ap.add_argument("--quiet", action="store_true"); ap.add_argument("--regold", action="store_true")
a = ap.parse_args()
rules = D.expand(a.rules)
E = Path(a.e1)
rows = D.load_rows(E / "eval3e.jsonl")
if a.regold:
    p1_rules.regold(rows)
SAFETY = ("leak_night", "leak_day_norefill", "ac_not_cooling_14h", "ac_fast_stepped")


def intended_ok(r, p):
    it = r.get("intended")
    if not it:
        return None
    return p.get("pattern") in it["pattern"] and p.get("status") in it["status"] and p.get("likely_cause") in it["cause"]


summary = {}
for tag in a.tags:
    sp = E / "eval" / tag / "samples.jsonl"
    if not sp.exists():
        print(f"{tag}: no samples"); continue
    S = D.load_samples(sp)
    R = D.ruled(rows, S, rules)
    per = defaultdict(lambda: defaultdict(int))
    detail = []
    for i, (s, ch) in R.items():
        r = rows[i]
        p = s.get("pred") or {}
        obs = D.obs_of(s.get("text", "")) if not ch else D.obs_of(S[i]["text"])
        fl = D.claim_flags(r, obs, r["off_hours"])
        io = intended_ok(r, p)
        st = per[r["story"]]
        st["n"] += 1; st["pattern"] += bool(s["pattern"]); st["status"] += bool(s["status"]); st["cause"] += bool(s["cause"])
        st["all3"] += bool(s["pattern"] and s["status"] and s["cause"])
        if io is not None:
            st["intended_n"] += 1; st["intended_ok"] += io
        st["claims"] += len(fl)
        detail.append({"id": i, "story": r["story"], "gold": [s["gold_pattern"], s["gold_status"]], "pred": [p.get("pattern"), p.get("status"), p.get("likely_cause")],
                       "rules": [c[0] + ":" + c[1] + "=" + str(c[3]) for c in ch], "intended_ok": io, "claims": fl, "obs": obs})
    tot = defaultdict(int)
    for st in per.values():
        for k, v in st.items():
            tot[k] += v
    saf = defaultdict(int)
    for k in SAFETY:
        for kk, v in per.get(k, {}).items():
            saf[kk] += v
    pct = lambda d, k, n="n": f"{100 * d[k] / d[n]:.0f}" if d.get(n) else "-"
    line = (f"E1 {tag}[{a.rules}] n{tot['n']} p{pct(tot, 'pattern')} s{pct(tot, 'status')} c{pct(tot, 'cause')} all3 {pct(tot, 'all3')} | "
            f"safety intended {saf['intended_ok']}/{saf['intended_n']} gold-status {saf['status']}/{saf['n']} | claims {tot['claims']}")
    print(line)
    if not a.quiet:
        print("   " + " ".join(f"{k}:{st['all3']}/{st['n']}" + (f"(i{st['intended_ok']})" if st.get('intended_n') else "") for k, st in per.items()))
    summary[tag] = {"line": line, "per_story": per, "detail": detail}
    json.dump(summary[tag], open(E / f"score_{tag}_{a.rules.replace(',', '+')}.json", "w"), indent=1, default=str)
