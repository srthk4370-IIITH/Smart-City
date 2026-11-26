"""scan_natural.py: rule view of every real held-out window (end >= cutoff+12h, 15-min slots) -> natural_scan.json (feeds Sets A/D and forced-single)"""
import json, collections, sys
import pdata as D, pcore as C
T0 = D.CUTOFF + 12 * 3600
slots = list(range(T0 - T0 % 900 + 900, D.DATA_END - 300, 900))
rows = []
for e in slots:
    for s in D.SENSORS:
        xs = D.window(s["node"], s["metric"], e, 144)
        if xs is None:
            continue
        xs = C.rnd(xs, s["role"], s["metric"])
        try:
            f = C.rule_finding(s["role"], s["metric"], xs[-48:], e)
        except Exception as ex:
            continue
        rows.append([e, s["key"], f["pattern"], f["status"]])
json.dump(rows, open("natural_scan.json", "w"))
c = collections.Counter((r[1].split("/")[1], r[3]) for r in rows)
print(len(rows)); print(sorted(c.items()))
