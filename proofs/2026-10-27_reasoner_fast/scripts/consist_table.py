"""6 prompts x 5 runs: decision consistency per field (share of runs equal to the most common value) and, at the first
token where runs diverge, the top1-top2 logit margin (HTPD_REASON_TRACE). Guarded severity = the app's light guard with
the real rule anchor (q0 INC-0361: critical, q1 INC-0362: warning; RWH prompts have no rule status -> raw)."""
import collections, glob, json, os, re, sys
D = sys.argv[1]
PR = [json.loads(l) for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "prompts.jsonl"), encoding="utf-8")]
ANCHOR = {0: "critical", 1: "warning"}
runs = collections.defaultdict(list)
for p in glob.glob(os.path.join(D, "cons_q*_*.json")):
    q, k = map(int, re.search(r"_q(\d+)_(\d+)\.json", p).groups())
    if k == 0: continue
    o = next((json.loads(l) for l in open(p, encoding="utf-8") if '"outputs"' in l), None)
    if not o: continue
    j = json.loads(o["outputs"][0]["text"])
    tr = [l.split() for l in open(os.path.join(D, "trace", f"trace_{k:03d}.txt"))] if os.path.exists(os.path.join(D, "trace", f"trace_{k:03d}.txt")) else []
    runs[q].append(dict(k=k, sev=j["severity"], label=j["label"], acts=tuple(c["action"] for c in j["checklist"]),
                        checks=tuple((c["ref"], c["verdict"]) for c in j["agent_checks"]), tr=tr, ms=o["total_ms"]))
def cons(xs):
    return max(collections.Counter(xs).values()) / len(xs)
print("| prompt | runs | severity | label | actions | checks | guarded severity | first divergence: step, margin (top1-top2) |")
print("|---|---|---|---|---|---|---|---|")
tot = collections.Counter(); n_all = 0
for q in sorted(runs):
    R = runs[q]; n = len(R); n_all += n
    g = ["warning" if r["sev"] == "normal" and ANCHOR.get(q) in ("warning", "critical") else r["sev"] for r in R]
    row = {f: cons([r[f] for r in R]) for f in ("sev", "label", "acts", "checks")}; row["guard"] = cons(g)
    for f, v in row.items(): tot[f] += v * n
    div = "-"
    trs = [r["tr"] for r in R if r["tr"]]
    if len(trs) > 1:
        L = min(len(t) for t in trs)
        for s in range(L):
            if len({t[s][1] for t in trs}) > 1:
                m = [float(t[s][3]) - float(t[s][5]) for t in trs]
                div = f"step {s}, margins {min(m):.3f}-{max(m):.3f}"
                break
        else:
            div = "none (identical picks)"
        hd = next((s for s in range(L) if len({t[s][6] for t in trs}) > 1), None)
        div += f"; logits bitwise differ from step {hd}" if hd is not None else "; logits bitwise identical"
    vals = collections.Counter(r["sev"] for r in R)
    print(f"| q{q} {PR[q]['id']} | {n} | {row['sev']:.0%} ({dict(vals)}) | {row['label']:.0%} | {row['acts']:.0%} | {row['checks']:.0%} | {row['guard']:.0%} | {div} |")
print(f"| **all** | {n_all} | **{tot['sev']/n_all:.0%}** | **{tot['label']/n_all:.0%}** | {tot['acts']/n_all:.0%} | {tot['checks']/n_all:.0%} | **{tot['guard']/n_all:.0%}** | |")
