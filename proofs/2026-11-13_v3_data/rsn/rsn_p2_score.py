"""score <dev_p2.jsonl> <res_ft.jsonl> <res_p2.jsonl>: new-family accuracy of two models. A row counts as correct when the severity equals
the gold severity AND the report is hygienic (every cited id is S<n>.E<n> and a line of the prompt; sensor_fault only when gold is sensor_fault).
prints JSON {ft:{acc,sev,hyg,n,per_family}, p2:{...}}"""
import collections, json, re, sys
rows = {}
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l); rows[r["id"]] = r


def rep_of(final):
    if isinstance(final, dict):
        return final
    t = final or ""
    i = t.find("{")
    while i >= 0:
        try:
            return json.loads(t[i:t.rfind("}") + 1])
        except Exception:
            i = t.find("{", i + 1)
    return None


def score(path):
    per = collections.defaultdict(lambda: [0, 0, 0, 0]); n = sev = hyg = ok = vl = 0
    for l in open(path, encoding="utf-8"):
        o = json.loads(l); r = rows.get(o["id"])
        if not r:
            continue
        g = json.loads(r["messages"][-1]["content"]); u = r["messages"][1]["content"]
        p = rep_of(o.get("final")); n += 1; vl += bool(p)
        s = bool(p) and p.get("severity") == g["severity"]
        ids = []
        if p:
            ids = list(p.get("evidence") or []) + [i for ob in (p.get("observations") or []) for i in (ob.get("src") or [])] + \
                  [i for c in (p.get("agent_checks") or []) for i in (c.get("src") or [])]
        h = bool(p) and all(re.fullmatch(r"S\d+\.E\d+", str(i)) and (str(i) + " ") in u for i in ids) and (p.get("severity") != "sensor_fault" or g["severity"] == "sensor_fault")
        sev += s; hyg += h; ok += (s and h)
        f = r.get("p2_family", "?"); a = per[f]; a[0] += 1; a[1] += s; a[2] += h; a[3] += (s and h)
    d = max(n, 1)
    return dict(n=n, valid=round(vl / max(n, 1), 4), acc=round(ok / d, 4), sev=round(sev / d, 4), hyg=round(hyg / d, 4), per_family={k: v for k, v in sorted(per.items())})


print(json.dumps({"ft": score(sys.argv[2]), "p2": score(sys.argv[3])}))
