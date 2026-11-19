"""Score board lab outputs on the RWH bench (q10-q39, q10 warm-up skipped): parse, severity/label/action vs gold,
agent-check recall/precision vs gold checks, verify.check_incident schema/grounding errors, mean reasoner seconds.
usage: python3 -I score_lab.py <dir with <cfg>_q<N>_<k>.json files> [first_q] [--rows rows.jsonl]"""
import collections, glob, json, os, re, sys
Q = "/mnt/c/Users/hp/Desktop/qidk/proofs"
sys.path.insert(0, Q + "/2026-10-25_reasoner_final/pipeline")
import verify as V  # noqa: E402
PR = [json.loads(l) for l in open(Q + "/2026-10-27_reasoner_fast/bench/prompts.jsonl", encoding="utf-8")]
D = sys.argv[1]; q0 = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 10
ROWS = sys.argv[sys.argv.index("--rows") + 1] if "--rows" in sys.argv else None
SCHEMA = {"key", "sev_enum", "label_enum", "checklist", "obs_count", "checks", "domains", "evidence_count", "json"}
res = collections.defaultdict(dict)
for p in glob.glob(os.path.join(D, "*_q*_*.json")):
    m = re.match(r"(.+)_q(\d+)_(\d+)\.json$", os.path.basename(p))
    if not m: continue
    c, q, k = m.group(1), int(m.group(2)), int(m.group(3))
    if k == 0 or q < q0: continue
    o = next((json.loads(l) for l in open(p, encoding="utf-8") if '"outputs"' in l), None)
    txt = o["outputs"][0]["text"] if o and o.get("outputs") else ""
    try: j = json.loads(txt)
    except Exception: j = None
    res[c][q] = dict(j=j, s=(o or {}).get("total_ms", 0) / 1000 or None, txt=txt, stop=(o or {}).get("stop"))
def errs(q, rep):
    p = PR[q]["prompt"]
    try: return V.check_incident({"messages": [{"role": "system", "content": p}, {"role": "user", "content": p},
                                               {"role": "assistant", "content": json.dumps(rep)}]})
    except Exception as e: return ["crash:" + str(e)[:40]]
rows = []; out = []
hdr = "| config | n | parse | sev=gold | label=gold | action1=gold | action set=gold | check recall | check prec | schema err | ungrounded | bad id | mean s | max s |"
out += [hdr, "|" + "---|" * 14]
for c in sorted(res):
    R = res[c]; n = len(R); ok = [q for q in sorted(R) if isinstance(R[q]["j"], dict)]
    sev = lab = a1 = aset = 0; rec = []; prec = []; se = ug = bid = 0
    for q in sorted(R):
        g = json.loads(PR[q]["gold"]); j = R[q]["j"]
        r = dict(cfg=c, q=q, s=R[q]["s"], parsed=isinstance(j, dict), gold_sev=g["severity"], gold_label=g["label"])
        if isinstance(j, dict):
            gs = {(x.get("ref"), x.get("verdict")) for x in g.get("agent_checks") or []}
            ps = [x for x in j.get("agent_checks") or [] if isinstance(x, dict)]
            acts = [x.get("action") for x in j.get("checklist") or [] if isinstance(x, dict)]
            gacts = [x["action"] for x in g["checklist"]]
            e = errs(q, j); kinds = {x.split(":")[0] for x in e}
            r.update(sev=j.get("severity"), label=j.get("label"), title=j.get("title"), sev_ok=j.get("severity") == g["severity"],
                     label_ok=j.get("label") == g["label"], a1_ok=bool(acts) and acts[0] == gacts[0], aset_ok=set(acts) == set(gacts),
                     errs=e, schema_err=bool(kinds & SCHEMA), ungrounded=bool(kinds & {"num", "time", "date"}), bad_id="id" in kinds)
            sev += r["sev_ok"]; lab += r["label_ok"]; a1 += r["a1_ok"]; aset += r["aset_ok"]
            se += r["schema_err"]; ug += r["ungrounded"]; bid += r["bad_id"]
            if gs:
                r["check_recall"] = sum(1 for (rf, v) in gs if any(x.get("ref") == rf and x.get("verdict") == v for x in ps)) / len(gs); rec.append(r["check_recall"])
            if ps:
                grefs = {rf for rf, _ in gs}; r["check_prec"] = sum(1 for x in ps if x.get("ref") in grefs) / len(ps); prec.append(r["check_prec"])
        else:
            r["raw"] = R[q]["txt"][:300]; r["stop"] = R[q]["stop"]
        rows.append(r)
    t = [R[q]["s"] for q in R if R[q]["s"]]
    f = lambda v: "%.2f (%d)" % (sum(v) / len(v), len(v)) if v else "-"
    out.append(f"| {c} | {n} | {len(ok)} | {sev} | {lab} | {a1} | {aset} | {f(rec)} | {f(prec)} | {se} | {ug} | {bid} | {sum(t)/len(t):.1f} | {max(t):.1f} |")
# gold vs itself (verify baseline: how many errors the checker flags on the reference answers)
ge = [errs(q, json.loads(PR[q]["gold"])) for q in range(q0, 40)]
out.append(f"\ngold baseline on q{q0}-q39: schema err {sum(bool({x.split(':')[0] for x in e} & SCHEMA) for e in ge)}, "
           f"ungrounded {sum(bool({x.split(':')[0] for x in e} & {'num','time','date'}) for e in ge)}, bad id {sum(any(x.startswith('id:') for x in e) for e in ge)}")
print("\n".join(out))
if ROWS:
    with open(ROWS, "w") as fh:
        for r in rows: fh.write(json.dumps(r) + "\n")
