"""Real-data check of training/v2/hvac.py (aggregates only). Run: py -3 realcheck.py"""
import sys, random
from collections import Counter, defaultdict
sys.path.insert(0, r"C:\Users\hp\Desktop\qidk\Code\smart-city-edge-agent\training\v2")
sys.path.insert(0, r"C:\Users\hp\Desktop\qidk\Code\smart-city-edge-agent\training")
import hvac as H, test_hvac as T

U = H.load_hvac_series(r"C:\Users\hp\Desktop\qidk\Code\smart-city-edge-agent\data\series")
rng = random.Random(9)
bases = defaultdict(list); real = Counter(); real_st = Counter(); fails = Counter(); words = []
faulty_real = Counter(); tot = amb = 0
for node, u in U.items():
    for n in (24, 48, 96, 144):
        for xs, ctx in H.hvac_windows(u, node, n=n, stride=96):
            tot += 1
            if u["faulty"]:
                r = H.real_fault_case(xs, ctx, rng)
                faulty_real[r[2]["pattern"] if r else "not_used"] += 1
                continue
            if H.is_ambiguous_real(xs, ctx):
                amb += 1
                continue
            lab = H.label_hvac(xs, ctx, rng)
            try:
                T.check_label(lab, xs, ctx)
            except AssertionError as e:
                fails[("real", lab["pattern"], str(e)[:90])] += 1
            if n == 48:
                real[lab["pattern"]] += 1; real_st[lab["status"]] += 1
            k = H.base_kind(xs, ctx)
            if k:
                bases[(n, k)].append((xs, ctx))
# D12 sampler balance (4 h windows, train months)
run = Counter()
for node, u in U.items():
    for _, r in H.window_ends(u, months=tuple(range(1, 9)), n=48, stride_off=12, stride_on=2):
        run["running" if r else "off"] += 1
got = Counter(); per_n = Counter()
for (n, k), B in bases.items():
    for pat in H.INJECTABLE:
        if n < H.MIN_LEN.get(pat, 0):
            continue
        for _ in range(25):
            xs, ctx = rng.choice(B)
            r = H.make_case(pat, xs, ctx, rng)
            if not r:
                continue
            ys, c, lab = r
            got[pat] += 1; per_n[n] += 1
            words += [len(o.split()) for o in lab["observations"]]
            try:
                T.check_label(lab, ys, c)
            except AssertionError as e:
                fails[("inj", pat, str(e)[:90])] += 1
r48 = sum(real.values())
print("windows", tot, "ambiguous skipped", amb)
print("real 4h labels (non-faulty, non-ambiguous)", r48, dict(real.most_common()))
print("real 4h status rates", {k: f"{v / r48:.2%}" for k, v in real_st.items()})
print("faulty units' windows (D11):", dict(faulty_real.most_common()))
print("D12 window_ends train months, 4h, stride on 10 min / off 60 min:", dict(run))
print("bases", {k: len(v) for k, v in sorted(bases.items())})
print("injected ok", dict(got), dict(per_n))
print("obs words max", max(words), "mean", round(sum(words) / len(words), 1))
print("check failures", sum(fails.values()))
for k, v in fails.most_common(8):
    print(v, k)
