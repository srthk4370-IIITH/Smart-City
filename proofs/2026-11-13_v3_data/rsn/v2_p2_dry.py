import collections, json, random, sys
import build_rsn as B, v2_gen as X, v2_gen_p2 as P2
X.install_r4(); P2.install_p2()
n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
R = random.Random(5); st = collections.Counter(); ok = {}
for nm in P2.NAMES:
    w = X.weights({nm: 1}); got = 0
    for _ in range(n * 6):
        r = B.run_inc(R, "r4", "train", st, fam_w=w, agt_p=0.75)
        if r is not None:
            got += 1; ok.setdefault(nm, r)
            if got >= n: break
    print(nm, got, "/", n)
print(json.dumps(dict(st))[:1500])
for nm, r in ok.items():
    if len(sys.argv) > 2 and sys.argv[2] == nm:
        print(r["messages"][1]["content"][-1500:]); print(r["messages"][-1]["content"][:1500])
