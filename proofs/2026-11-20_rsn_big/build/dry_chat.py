import sys, random, collections, json, traceback
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/build")
import big_chat as BC
R = random.Random(3); out = collections.defaultdict(list)
for name, fn, n in BC.KINDS:
    ok = bad = none = exc = 0; errs = collections.Counter(); ex = None
    for _ in range(60):
        try: r = fn(R, "train")
        except Exception as e:
            exc += 1; errs["EXC:" + repr(e)[:90]] += 1; continue
        if r is None: none += 1; continue
        e = BC.check(r)
        if e: bad += 1; errs.update(x.split(":")[0] if not x.startswith("num") else x for x in e)
        else: ok += 1; ex = ex or r
    print(name, "ok", ok, "bad", bad, "none", none, "exc", exc, dict(errs))
    if ex:
        print("   Q:", [m["content"] for m in ex["messages"] if m["role"] == "user"][-1][:140]); print("   F:", ex["messages"][-1]["content"][:260].replace("\n", " / "), "| calls", [c["name"] for c in ex["gold_calls"]])
