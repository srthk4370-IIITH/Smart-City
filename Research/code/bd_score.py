"""bd_score.py: Set B + D reasoner on the BOARD (board_drive.py bd, adaptive, v4 prompt, same user prompts as the host full arm)
vs the host full run (runs/full/records.jsonl) vs gold. Guards as in the paper: invalid report -> cheap_x template. Skip = Fix 1 (skip_rule.py).
Output results/bd_board.json + markdown on stdout."""
import json, statistics as S, numpy as np
import skip_rule as SK
host = {json.loads(l)["id"]: json.loads(l) for l in open("runs/full/records.jsonl")}
SEVS = {"normal", "warning", "critical", "sensor_fault"}
rows = []
for l in open("results/board_drive/bd.jsonl", encoding="utf-8"):
    d = json.loads(l); r = host[d["id"]]
    try:
        o = json.loads(d["reasoner"]["final"])
    except Exception:
        o = None
    valid = isinstance(o, dict) and o.get("severity") in SEVS and bool(o.get("label"))
    g = (o if valid else r["cheap_x"])
    sk = SK.all_normal(r, False)
    rows.append(dict(id=d["id"], set=r["set"], gold=r["gold"], valid=valid, board=g, board_raw=o if valid else None, host=r["full"], host_raw=r["reasoner"]["report"] if r["reasoner"]["valid"] else None,
                     board_skip=(SK.NORMAL if sk else g), host_skip=(SK.NORMAL if sk else r["full"]), wall=d["reasoner_wall_s"], host_wall=r["reasoner"].get("wall_s"), t=(d["t_start"], d["t_end"])))
json.dump(rows, open("results/bd_board.json", "w"), indent=0)
ok = lambda x, g: bool(x) and x.get("label") == g["label"] and x.get("severity") == g["severity"]
B = [x for x in rows if x["set"] == "B"]; Dn = [x for x in rows if x["set"] == "D" and x["gold"]["severity"] == "normal"]; Df = [x for x in rows if x["set"] == "D" and x["gold"]["severity"] == "sensor_fault"]
pc = lambda a, n: "%d/%d (%.1f %%)" % (a, n, 100 * a / n)
md = ["| measure | board | host |", "|---|---|---|"]
md.append("| valid reports, B+D | %s | %s |" % (pc(sum(x["valid"] for x in rows), len(rows)), pc(sum(x["host_raw"] is not None for x in rows), len(rows))))
md.append("| Set B both correct, raw (invalid = wrong) | %s | %s |" % (pc(sum(ok(x["board_raw"], x["gold"]) for x in B), len(B)), pc(sum(ok(x["host_raw"], x["gold"]) for x in B), len(B))))
md.append("| Set B both correct, guards on | %s | %s |" % (pc(sum(ok(x["board"], x["gold"]) for x in B), len(B)), pc(sum(ok(x["host"], x["gold"]) for x in B), len(B))))
md.append("| Set B label / severity, guards on | %s / %s | %s / %s |" % (pc(sum(x["board"].get("label") == x["gold"]["label"] for x in B), len(B)), pc(sum(x["board"].get("severity") == x["gold"]["severity"] for x in B), len(B)),
          pc(sum(x["host"].get("label") == x["gold"]["label"] for x in B), len(B)), pc(sum(x["host"].get("severity") == x["gold"]["severity"] for x in B), len(B))))
for nm, k in (("D false alarm (normal windows)", "board"), ("D false alarm with skip rule", "board_skip")):
    hk = "host" if k == "board" else "host_skip"
    md.append("| %s | %s | %s |" % (nm, pc(sum(x[k].get("severity") != "normal" for x in Dn), len(Dn)), pc(sum(x[hk].get("severity") != "normal" for x in Dn), len(Dn))))
md.append("| D real faults called sensor_fault | %s | %s |" % (pc(sum(x["board"].get("severity") == "sensor_fault" for x in Df), len(Df)), pc(sum(x["host"].get("severity") == "sensor_fault" for x in Df), len(Df))))
same = sum((x["board"].get("label"), x["board"].get("severity")) == (x["host"].get("label"), x["host"].get("severity")) for x in rows)
md.append("| board = host (label and severity) | %s | - |" % pc(same, len(rows)))
md.append("| reasoner wall s, median (B / D) | %.1f / %.1f | %.1f / %.1f |" % (S.median(x["wall"] for x in B), S.median(x["wall"] for x in Dn + Df), S.median(x["host_wall"] for x in B), S.median(x["host_wall"] for x in Dn + Df)))
b = sum(ok(x["board"], x["gold"]) and not ok(x["host"], x["gold"]) for x in B); c = sum(ok(x["host"], x["gold"]) and not ok(x["board"], x["gold"]) for x in B)
import math
n = b + c; p = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n) if n else 1.0
md.append(""); md.append("- Set B board vs host, both-correct McNemar: board-only right %d, host-only right %d, p = %.2f." % (b, c, p))
print("\n".join(md))
