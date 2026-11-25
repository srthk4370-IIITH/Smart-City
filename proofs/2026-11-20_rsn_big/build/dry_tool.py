import sys, random, collections, time
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build")
import build_big as BB, build_rsn as B, v2_gen as X
X.install_r4(); R = random.Random(1); st = collections.Counter(); t = time.time(); n = tool = 0; fams = collections.Counter()
for _ in range(300):
    r = B.run_inc(R, "r1", "train", st); n += r is not None
    if r is not None and any(m.get("tool_calls") for m in r["messages"]): tool += 1; fams[r["family"]] += 1
print(n, tool, round(time.time() - t, 1), dict(fams), dict(st))
