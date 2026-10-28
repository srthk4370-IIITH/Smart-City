import glob, json, os, re, sys, collections
V, RF = sys.argv[1], sys.argv[2]
PR = [json.loads(l) for l in open(f"{RF}/bench/prompts.jsonl", encoding="utf-8")]
def load(d, name):
    out = {}
    for p in glob.glob(f"{d}/{name}_q*_*.json"):
        q, k = map(int, re.search(r"_q(\d+)_(\d+)\.json", p).groups())
        if k == 0: continue
        o = next((json.loads(l) for l in open(p, encoding="utf-8") if '"outputs"' in l), None)
        j = None; stop = None; ms = None
        if o:
            stop = o["outputs"][0].get("stop"); ms = o.get("total_ms")
            try: j = json.loads(o["outputs"][0]["text"])
            except Exception: j = None
        out.setdefault(q, []).append(dict(j=j, stop=stop, ms=ms))
    return out
def sl(j): return (j["severity"], j["label"]) if j else None
gold = {q: sl(json.loads(PR[q]["gold"])) for q in range(len(PR))}
v1 = load(f"{RF}/raw/split6", "sp3"); par = load(f"{V}/raw_par", "sp3x"); v2 = load(f"{V}/raw_v2", "sp3v2"); co = load(f"{V}/raw_cons", "sp3c")
r = {}
qs = range(10, 15)
r["par_parse"] = sum(1 for q in qs if par.get(q) and par[q][0]["j"] and par[q][0]["stop"] == "json")
r["par_same"] = sum(1 for q in qs if par.get(q) and v1.get(q) and sl(par[q][0]["j"]) == sl(v1[q][0]["j"]))
r["par_ms"] = round(sum(par[q][0]["ms"] or 0 for q in qs if par.get(q)) / 5000, 1); r["v1_ms"] = round(sum(v1[q][0]["ms"] or 0 for q in qs if v1.get(q)) / 5000, 1)
qs2 = range(10, 20)
r["v2_parse"] = sum(1 for q in qs2 if v2.get(q) and v2[q][0]["j"] and v2[q][0]["stop"] == "json")
r["v2_stops"] = dict(collections.Counter(v2[q][0]["stop"] for q in qs2 if v2.get(q)))
for tag, d in (("v1", v1), ("v2", v2)):
    r[f"{tag}_sev_gold"] = sum(1 for q in qs2 if d.get(q) and d[q][0]["j"] and d[q][0]["j"]["severity"] == gold[q][0])
    r[f"{tag}_lab_gold"] = sum(1 for q in qs2 if d.get(q) and d[q][0]["j"] and d[q][0]["j"]["label"] == gold[q][1])
r["v2_ms"] = round(sum(v2[q][0]["ms"] or 0 for q in qs2 if v2.get(q)) / 10000, 1)
r["v2_q11"] = v2.get(11, [{}])[0].get("stop")
cons_same = 0
for q in (11, 12, 13):
    sev = [x["j"]["severity"] if x["j"] else None for x in co.get(q, [])]
    if sev: cons_same += max(collections.Counter(sev).values())
r["cons"] = f"{cons_same}/9"
sp6 = load(f"{V}/raw_sp6", "sp6c")
r["sp6_parse"] = sum(1 for q in qs if sp6.get(q) and sp6[q][0]["j"] and sp6[q][0]["stop"] == "json")
r["sp6_same_as_sp3x"] = sum(1 for q in qs if sp6.get(q) and par.get(q) and sl(sp6[q][0]["j"]) == sl(par[q][0]["j"]))
r["sp6_ms"] = round(sum(sp6[q][0]["ms"] or 0 for q in qs if sp6.get(q)) / 5000, 1)
r["parity"] = r["par_parse"] == 5 and r["par_same"] >= 4
r["v2_pass"] = r["v2_parse"] == 10 and r["v2_sev_gold"] >= r["v1_sev_gold"] and r["v2_lab_gold"] >= r["v1_lab_gold"] and cons_same >= 8
print(json.dumps(r))
