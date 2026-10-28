"""Automatic P2/P3 decisions for the overnight queue (all scores with the P1 rules + new leak gold, ref = mixA50).
  pick.py e1top N TAG...    -> the N best tags by E1 all-3 (ties: safety), one per line; only tags at least as good as ref
  pick.py gaps TAG          -> exit 0 if HVAC/compound E1 gaps remain for TAG (any of those stories below 100% all-3)
  pick.py final TAG...      -> JSON: per tag E1 + dev3f E2 gate; winner = gate PASS, E1 all-3 >= ref, best (dev status net, E1 all-3)
Ref tags: E1 mixA50cuda, dev mixA50."""
import json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dp_lib as D  # noqa: E402
import p1_rules as P  # noqa: E402

E1 = Path("/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/e1")
RULES = D.expand("ALL_P1")
SAFETY = ("leak_night", "leak_day_norefill", "ac_not_cooling_14h", "ac_fast_stepped")
GAPS = ("ac_not_cooling_14h", "ac_fast_stepped", "ac_slow_recovery", "refill_then_drain", "power_step_then_grad", "power_gap_recovery")
_rows = {}


def rows(d):
    if d not in _rows:
        _rows[d] = D.load_rows(d / "eval3e.jsonl"); P.regold(_rows[d])
    return _rows[d]


def e1(tag):
    sp = E1 / "eval" / tag / "samples.jsonl"
    rw = rows(E1)
    if not sp.exists():
        return None
    S = D.ruled(rw, D.load_samples(sp), RULES)
    if len(S) < len(rw):
        return None
    per = defaultdict(lambda: [0, 0])
    saf = [0, 0]
    for i, (s, _) in S.items():
        ok = bool(s["pattern"] and s["status"] and s["cause"])
        st = rw[i]["story"]; per[st][0] += ok; per[st][1] += 1
        it = rw[i].get("intended")
        if st in SAFETY and it:
            p = s.get("pred") or {}
            saf[1] += 1; saf[0] += p.get("pattern") in it["pattern"] and p.get("status") in it["status"] and p.get("likely_cause") in it["cause"]
    n = sum(v[1] for v in per.values())
    return {"all3": round(100 * sum(v[0] for v in per.values()) / n, 2), "safety": saf[0], "safety_n": saf[1],
            "gaps": {k: f"{per[k][0]}/{per[k][1]}" for k in GAPS if k in per}, "gap_open": any(per[k][0] < per[k][1] for k in GAPS if k in per)}


def dev_gate(tag):
    d = D.L.SETS["dev"]; rw = rows(d)
    sp = d / "eval" / tag / "samples.jsonl"
    if not sp.exists() or sum(1 for _ in open(sp)) < len(rw):
        return None
    ref = {i: v[0] for i, v in D.ruled(rw, D.load_samples(d / "eval/mixA50/samples.jsonl"), RULES).items()}
    cand = {i: v[0] for i, v in D.ruled(rw, D.load_samples(sp), RULES).items()}
    t, fd = D.paired(rw, ref, cand)
    ok, line = D.gate_line("dev", t, fd)
    a = t["ALL"]
    return {"pass": ok, "line": line, "status_net": a["status"][3] - a["status"][4], "pattern_net": a["pattern"][3] - a["pattern"][4], "flat_net": fd["net"]}


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    ref = e1("mixA50cuda")
    if cmd == "e1top":
        n, tags = int(args[0]), args[1:]
        sc = [(t, e1(t)) for t in tags]
        sc = [(t, s) for t, s in sc if s and (s["all3"], s["safety"]) >= (ref["all3"] - 1.0, ref["safety"])]
        sc.sort(key=lambda x: (-x[1]["all3"], -x[1]["safety"]))
        print("\n".join(t for t, _ in sc[:n]))
    elif cmd == "gaps":
        s = e1(args[0]) if args[0] != "ref" else ref
        sys.exit(0 if (s is None or s["gap_open"]) else 1)
    elif cmd == "final":
        res = {"ref": {"e1": ref}, "cands": {}}
        best = None
        for t in args:
            r = {"e1": e1(t), "dev": dev_gate(t)}
            res["cands"][t] = r
            # must BEAT mixA50 + P1 on both: E2 gate PASS with a positive net (status + pattern), E1 all-3 above ref, safety not lower
            if r["e1"] and r["dev"] and r["dev"]["pass"] and r["dev"]["status_net"] + r["dev"]["pattern_net"] > 0 \
                    and r["e1"]["all3"] > ref["all3"] and r["e1"]["safety"] >= ref["safety"]:
                key = (r["dev"]["status_net"] + r["dev"]["pattern_net"], r["e1"]["all3"])
                if best is None or key > best[0]:
                    best = (key, t)
        res["winner"] = best[1] if best else "mixA50 (no candidate passed)"
        print(json.dumps(res, default=str))
