"""Study A tables: rename agreement (orig vs ren) and noise floor (orig vs rep) on pattern/status/cause; accuracy vs gold
(C.score_one, raw model output, no app post-rules) for orig/ren with McNemar; absolute B50 table by domain and slice;
parity of the live merged GGUF vs the stored runtime-LoRA B50 dev run. -> raw/A_summary.json, raw/A_tables.md"""
import json, sys, collections
from pathlib import Path
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post")
import common_v2 as C
RAW = Path(__file__).resolve().parent.parent / "raw"
S = [json.loads(l) for l in open(RAW / "samples_A.jsonl")]
by = {v: {s["id"].split("::")[0]: s for s in S if s["variant"] == v} for v in ("orig", "ren", "rep")}
ROWS = {r["id"]: r for r in C.read_jsonl(RAW / "rows_A.jsonl") if r["variant"] == "orig"}
stored = {}
sp = Path.home() / "smartcity_runs/agents_v2_topup3f/eval_dev/eval/B50/samples.jsonl"
for l in open(sp):
    s = json.loads(l); stored[s["id"]] = s
F = ("pattern", "status", "likely_cause")
K = ("pattern", "status", "cause")
def pv(s, f): return (s.get("pred") or {}).get(f)
def keys(i):
    r = ROWS[i]; g = C.gold_of(r)
    ks = ["ALL", "dom_" + r["role"], "gold_pat_" + g["pattern"], "gold_status_" + g["status"], "fam_" + str(r.get("family"))]
    if C.is_negative(r): ks.append("calm_or_routine")
    return ks
def pct(a, n): return f"{a}/{n} ({100*a/n:.1f})" if n else "-"
agg = collections.defaultdict(collections.Counter)
for i, o in by["orig"].items():
    for k in keys(i):
        a = agg[k]; a["n"] += 1
        for f, kk in zip(F, K):
            a["acc_" + kk] += bool(o.get(kk)); a["fa"] += bool(o.get("false_alarm"))
        a["json"] += bool(o.get("json"))
        n = by["ren"].get(i)
        if n:
            a["n_ren"] += 1
            for f, kk in zip(F, K):
                a["agree_" + kk] += pv(o, f) == pv(n, f)
                a["ren_acc_" + kk] += bool(n.get(kk))
                a["w_" + kk] += bool(n.get(kk)) and not o.get(kk); a["l_" + kk] += bool(o.get(kk)) and not n.get(kk)
            a["agree_all3"] += all(pv(o, f) == pv(n, f) for f in F)
            a["ren_fa"] += bool(n.get("false_alarm"))
        p = by["rep"].get(i)
        if p:
            a["n_rep"] += 1; a["rep_agree_all3"] += all(pv(o, f) == pv(p, f) for f in F)
        st = stored.get(i)
        if st:
            a["n_st"] += 1; a["st_agree_all3"] += all(pv(o, f) == pv(st, f) for f in F)
            for kk in K: a["st_acc_" + kk] += bool(st.get(kk))
for k in agg:   # fa only counts once per row
    agg[k]["fa"] //= 3
def mcn(k, kk):
    a = agg[k]; return C.mcnemar([True] * a["l_" + kk] + [False] * a["w_" + kk], [False] * a["l_" + kk] + [True] * a["w_" + kk])["p"] if a["l_" + kk] + a["w_" + kk] else 1.0
md = ["## A1. Rename agreement (same windows, renamed NODE line), live B50 GGUF, host CUDA\n",
      "| slice | n | pattern agree | status agree | cause agree | all 3 agree | noise floor all 3 (orig vs repeat) |", "|---|---|---|---|---|---|---|"]
order = sorted(agg, key=lambda k: (k != "ALL", k.split("_")[0], -agg[k]["n"]))
for k in order:
    a = agg[k]
    if a["n_ren"] < 5: continue
    md.append(f"| {k} | {a['n_ren']} | {pct(a['agree_pattern'], a['n_ren'])} | {pct(a['agree_status'], a['n_ren'])} | {pct(a['agree_cause'], a['n_ren'])} | {pct(a['agree_all3'], a['n_ren'])} | {pct(a['rep_agree_all3'], a['n_rep'])} |")
md += ["\n## A2. Accuracy vs gold, original vs renamed (paired; W/L = renamed right & original wrong / the reverse; McNemar p)\n",
       "| slice | n | pattern orig | pattern ren | W/L p | status orig | status ren | W/L p | cause orig | cause ren | W/L p | false alarms orig -> ren |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for k in order:
    a = agg[k]
    if a["n_ren"] < 5: continue
    cells = []
    for kk in K:
        cells += [pct(a["acc_" + kk], a["n"]), pct(a["ren_acc_" + kk], a["n_ren"]), f"{a['w_'+kk]}/{a['l_'+kk]} {mcn(k, kk):.3g}"]
    md.append(f"| {k} | {a['n_ren']} | " + " | ".join(cells) + f" | {a['fa']} -> {a['ren_fa']} |")
md += ["\n## A3. Absolute B50 accuracy (live merged GGUF, 1,000 stratified held-out dev3f windows; Wilson 95% CI)\n",
       "| slice | n | JSON | pattern | status | cause | false alarms | stored runtime-LoRA B50 run: pattern / status / cause | live vs stored all-3 agree |", "|---|---|---|---|---|---|---|---|---|"]
def ci(k, n):
    lo, hi = C.wilson(k, n); return f"{100*k/n:.1f} [{100*lo:.0f}-{100*hi:.0f}]" if n else "-"
for k in order:
    a = agg[k]
    if a["n"] < 5: continue
    md.append(f"| {k} | {a['n']} | {pct(a['json'], a['n'])} | {ci(a['acc_pattern'], a['n'])} | {ci(a['acc_status'], a['n'])} | {ci(a['acc_cause'], a['n'])} | {a['fa']} | "
              f"{ci(a['st_acc_pattern'], a['n_st'])} / {ci(a['st_acc_status'], a['n_st'])} / {ci(a['st_acc_cause'], a['n_st'])} | {pct(a['st_agree_all3'], a['n_st'])} |")
# full 2,010 stored run by domain
full = collections.defaultdict(collections.Counter)
for i, s in stored.items():
    for k in ("ALL", "dom_" + s["role"]):
        full[k]["n"] += 1
        for kk in K: full[k][kk] += bool(s.get(kk))
md += ["\n## A4. Full dev3f (2,010 windows), stored runtime-LoRA B50 run (eval_dev/eval/B50, mixA50 base + LoRA mix)\n", "| slice | n | pattern | status | cause |", "|---|---|---|---|---|"]
for k, a in sorted(full.items()):
    md.append(f"| {k} | {a['n']} | {ci(a['pattern'], a['n'])} | {ci(a['status'], a['n'])} | {ci(a['cause'], a['n'])} |")
# flips by kind
flips = collections.Counter()
ex = []
for i, o in by["orig"].items():
    n = by["ren"].get(i)
    if n and pv(o, "status") != pv(n, "status"):
        flips[(ROWS[i]["role"], pv(o, "status"), pv(n, "status"), C.gold_of(ROWS[i])["status"])] += 1
md += ["\n## A5. Status flips under renaming (domain, orig -> renamed, gold)\n", "| domain | orig | renamed | gold | n |", "|---|---|---|---|---|"]
for (d, a, b, g), c in flips.most_common(40):
    md.append(f"| {d} | {a} | {b} | {g} | {c} |")
(RAW / "A_tables.md").write_text("\n".join(md) + "\n")
(RAW / "A_summary.json").write_text(json.dumps({"agg": {k: dict(v) for k, v in agg.items()}, "full_stored": {k: dict(v) for k, v in full.items()},
                                                "status_flips": [[list(k), v] for k, v in flips.most_common()]}, indent=1))
print("\n".join(md))
