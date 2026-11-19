import json, collections, re, sys
c = collections.Counter(); fam = collections.Counter(); nd = collections.Counter()
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l)
    u = r["messages"][1]["content"]
    roles = re.findall(r"^S\d+ \[FLAGGED\]: .* \((\w+)\)$", u, re.M)
    k = len(set(roles)); c[(len(roles), k)] += 1
    if k >= 2: fam[r["family"].split("+")[0]] += 1
    rep = json.loads(r["messages"][-1]["content"]); nd[len(rep["affected_domains"])] += 1
print(c.most_common()); print(fam.most_common(30)); print(nd)
