import sys, random, collections, json
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build")
import big_inc as BI
import build_rsn as B, v2_gen as X
X.install_r4(); BI.install_big()
stats = collections.Counter(); R = random.Random(5)
for nm in BI.NAMES:
    w = X.weights({nm: 1}); got = 0; sev = collections.Counter()
    for _ in range(60):
        try: r = B.run_inc(R, "r4", "train", stats, fam_w=w, agt_p=0.75)
        except Exception as e: stats["exc:%s:%s" % (nm, repr(e)[:80])] += 1; continue
        if r: got += 1; sev[r["family"].split("+")[0]] += 1
    print(nm, got, dict(sev))
print({k: v for k, v in stats.items()})
