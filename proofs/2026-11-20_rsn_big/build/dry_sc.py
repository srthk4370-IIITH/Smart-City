import sys, random, collections, json, re
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build")
import build_big as BB, big_inc as BI, v2_gen as X, build_rsn as B
X.install_r4(); BI.install_big(); G = B.G
R = random.Random(2); c = collections.Counter()
w = X.weights({"big_co2": 1, "big_pm": 1, "big_temp": 1, "occ_load": 1, "worse": 1, "dry_run": 1, "pump_trip": 1})
for _ in range(60):
    r, why = G.gen_r4(R, 0, "train", fam_w=w, refine=1.0, agt=True)
    if r is None: c["none:" + str(why)] += 1; continue
    c["fam:" + r["family"].split("+")[0] + ("+refine" if "refine" in r["family"] else "")] += 1
    u = r["messages"][1]["content"]; prev = re.findall(r"^  R\d+ \d\d:\d\d (\w+):", u, re.M)
    c["prev" if prev else "noprev"] += 1
    r2 = BB.sev_change(r); c["sc" if "+sevchange" in r2["family"] else "nosc"] += 1
    e = G.full_check(r2) if "+sevchange" in r2["family"] else []
    if e: c["fail:" + e[0][:40]] += 1
print(dict(c))
# replicate mk_sc exactly with fin
stats = collections.Counter()
def fin(r, kind):
    e = G.full_check(r)
    if e:
        stats["fail:%s:%s" % (kind, e[0].split(":")[0])] += 1; return None
    return r
out = 0
for _ in range(60):
    agt = R.random() < 0.75
    r, why = G.gen_r4(R, 0, "train", fam_w=w, refine=1.0, agt=agt)
    if r is None: stats["none"] += 1; continue
    r = BB.sev_change(r)
    if "+sevchange" not in r["family"]: stats["nosc"] += 1; continue
    r = fin(r, "r4")
    out += r is not None
print(out, dict(stats))
