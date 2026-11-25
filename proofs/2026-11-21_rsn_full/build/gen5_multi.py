"""gen5_multi.py N: multi-domain incidents (2-5 flagged domains), gold by construction, scenes dated 2025-01..2025-12-10 (pre-cutoff). family gen5_multidomain."""
import sys, os, json, random, collections, datetime as dt
BIGB = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build"; sys.path.insert(0, BIGB)
import build_big as BB, big_inc as BI, v2_gen as X
B, G, M = BB.B, BB.G, X.M
CUT_DATE = dt.date(2025, 12, 10)
_scen = M.scen
def scen(R, i, novel=False, months=None, hours=None):
    ms = [m for m in (months or range(1, 12)) if m <= 11] or [5]
    sc = _scen(R, i, novel, ms, hours)
    e = sc["end"]; d = dt.date(2025, e.month, min(e.day, 28))
    sc["end"] = e.replace(year=2025, month=d.month, day=d.day); return sc
M.scen = scen
N = int(sys.argv[1]); OUT = sys.argv[2]
X.install_r4(); BI.install_big()
R = random.Random(52111)
bu, be, bq, seen, qseen = BB.bans_and_seen()
FAMW = {"occ_load": 1, "occ_fault": 1, "heat_multihop": 3, "heat_trans": 2, "heat_three": 3, "ac_fail": 2, "wx_fault_co2": 1, "pm_ingress": 2, "pump_trip": 3, "leak": 3, "dry_run": 2,
        "level_fault": 1, "rain_level": 2, "indep": 5, "worse": 2, "pf_chain": 2, "heat_feeder2": 3, "pf_chain4": 3}
st = collections.Counter(); sink = B.Sink(OUT)
def mk():
    r = B.run_inc(R, "r4", "train", st, fam_w=X.weights(FAMW), agt_p=0.75)
    if r is None: return None
    if len(r.get("flagged_domains") or []) < 2: st["drop_single_domain"] += 1; return None
    r.update(src_real=False, family_gen5="gen5_multidomain", gen5="multidomain", block="gen5_multidomain"); r["family"] = "gen5_multidomain:" + r["family"]
    return r
B.gen_block("gen5_multi", N, R, mk, sink, st, (bu, be), seen); sink.close()
print(sink.n, dict(st)); print(collections.Counter(len(json.loads(l).get("flagged_domains") or []) for l in open(OUT)))
