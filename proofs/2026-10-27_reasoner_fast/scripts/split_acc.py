"""Split vs single on RWH prompts: gold agreement (severity, label, first action, all actions as a set) and agreement
with the single-stream answer, plus mean reasoner time. usage: split_acc.py <ab dir> [first_q]"""
import collections, glob, json, os, re, sys
D = sys.argv[1]; q0 = int(sys.argv[2]) if len(sys.argv) > 2 else 0
PR = [json.loads(l) for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "prompts.jsonl"), encoding="utf-8")]
res = collections.defaultdict(dict); REF = os.environ.get("REF", "single")
for p in glob.glob(os.path.join(D, "*_q*_*.json")):
    m = re.match(r"(.+)_q(\d+)_(\d+)\.json", os.path.basename(p)); c, q, k = m.group(1), int(m.group(2)), int(m.group(3))
    if k == 0 or q < q0: continue
    o = next((json.loads(l) for l in open(p, encoding="utf-8") if '"outputs"' in l), None)
    try: j = json.loads(o["outputs"][0]["text"])
    except Exception: j = None
    res[c][q] = (j, o["total_ms"] / 1000 if o else None)
def f(j): return (j["severity"], j["label"], j["checklist"][0]["action"] if j["checklist"] else None, frozenset(c["action"] for c in j["checklist"]))
print("| config | n | parse | sev=gold | label=gold | action1=gold | action set=gold | sev=single | label=single | mean s |")
print("|---|---|---|---|---|---|---|---|---|---|")
for c in sorted(res, key=lambda x: (x != REF, x)):
    R = res[c]; n = len(R); ok = [q for q in R if R[q][0]]
    g = lambda i: sum(f(R[q][0])[i] == f(json.loads(PR[q]["gold"]))[i] for q in ok)
    s = lambda i: sum(1 for q in ok if q in res[REF] and res[REF][q][0] and f(R[q][0])[i] == f(res[REF][q][0])[i])
    t = [R[q][1] for q in R if R[q][1]]
    print(f"| {c} | {n} | {len(ok)} | {g(0)} | {g(1)} | {g(2)} | {g(3)} | {s(0)} | {s(1)} | {sum(t)/len(t):.1f} |")
