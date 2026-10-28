import sys; sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-25_domain_plan/scripts")
import dp_lib as D, p1_rules as P
d = D.L.SETS["dev"]; rw = D.load_rows(d / "eval3e.jsonl"); P.regold(rw); R = D.expand("ALL_P1")
S = {t: {i: v[0] for i, v in D.ruled(rw, D.load_samples(d / f"eval/{t}/samples.jsonl"), R).items()} for t in ("mixA50", "v2cuda", "P3W06")}
K = ("pattern", "status", "cause")
gainA = [(i, k) for i in S["mixA50"] for k in K if S["mixA50"][i][k] and not S["v2cuda"][i][k]]   # mixA50 right, v2 wrong
lossA = [(i, k) for i in S["mixA50"] for k in K if not S["mixA50"][i][k] and S["v2cuda"][i][k]]
p3l = [(i, k) for i in S["mixA50"] for k in K if S["mixA50"][i][k] and not S["P3W06"][i][k]]
p3w = [(i, k) for i in S["mixA50"] for k in K if not S["mixA50"][i][k] and S["P3W06"][i][k]]
g, l = set(gainA), set(lossA)
agree = sum(1 for i in S["mixA50"] for k in K if bool(S["P3W06"][i][k]) == bool(S["v2cuda"][i][k]) and bool(S["mixA50"][i][k]) != bool(S["v2cuda"][i][k]))
print(f"mixA50 vs v2: +{len(gainA)}/-{len(lossA)} | P3W06 losses {len(p3l)} of which on mixA50-over-v2 gains {len(set(p3l) & g)} | P3W06 wins {len(p3w)} of which recover v2-right {len(set(p3w) & l)}")
print(f"on the {len(g)+len(l)} decisions where mixA50 and v2 differ, P3W06 sides with v2 on {agree}")
