"""Pick rsn_v3 between two gated candidates (4B from Kaggle, 2B from the laptop), owner rule 2026-10-30:
1. only candidates whose own gate passed (gate.json pass: RWH + RWH-2 strict >= rsn_v1, dev within 1 item, chat up);
2. one passes -> it; both -> the MORE ACCURATE: report metrics on RWH + RWH-2 (severity, label, check_recall, check_prec, req
   higher; schema_err lower) compared in items (difference x rows carrying the metric, summed over the two sets);
   metrics within 1 item count as tied. More metrics clearly better wins; if each wins some, the larger summed item margin;
3. report metrics all tied -> chat dev v3 pass rate (more than 1 item apart wins);
4. still tied -> the faster candidate (--fast, default the 2B).
Writes COMPARE.md + compare.json next to --out; exit 0 with a winner, 1 if none passed.
  python3 compare_candidates.py --a 4b=kaggle/gate/t4b --b 2b=kaggle/gate/t2b --fast 2b --out kaggle/gate/compare_<id>"""
import argparse
import json
import os
import sys

UP = ["severity", "label", "check_recall", "check_prec", "req"]
DOWN = ["schema_err"]


def load(spec):
    name, d = spec.split("=", 1)
    g = json.load(open(os.path.join(d, "gate.json")))
    return name, d, g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--fast", default="2b")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    (na, da, ga), (nb, db, gb) = load(a.a), load(a.b)
    res = {"candidates": {na: {"dir": da, "pass": ga["pass"]}, nb: {"dir": db, "pass": gb["pass"]}}, "metrics": {}}
    passing = [n for n, g in ((na, ga), (nb, gb)) if g["pass"]]
    why = ""
    if not passing:
        winner, why = None, "no candidate passed its gate"
    elif len(passing) == 1:
        winner, why = passing[0], "only %s passed its gate" % passing[0]
    else:
        wins = {na: 0, nb: 0}
        margin = 0.0                  # items in favour of a (positive) / b (negative)
        for m in UP + DOWN:
            items = 0.0
            for s in ("rwh", "rwh2"):
                sa, sb = ga["suites"].get(s), gb["suites"].get(s)
                if not sa or not sb or sa["new"].get(m) is None or sb["new"].get(m) is None:
                    continue
                n = max(sa["new"]["_counts"][m], sb["new"]["_counts"][m])
                d = (sa["new"][m] - sb["new"][m]) * n
                items += d if m in UP else -d
            res["metrics"][m] = round(items, 2)
            if items > 1 + 1e-9:
                wins[na] += 1
            elif items < -1 - 1e-9:
                wins[nb] += 1
            margin += items
        if wins[na] != wins[nb] and (wins[na] == 0 or wins[nb] == 0):
            winner = na if wins[na] > wins[nb] else nb
            why = "more accurate on RWH + RWH-2 (%s)" % res["metrics"]
        elif wins[na] or wins[nb]:
            winner = na if margin > 0 else nb
            why = "mixed metric wins %s; larger summed item margin %.1f" % (wins, margin)
        else:
            ca, cb = ga["chat"]["new"], gb["chat"]["new"]
            d = (ca["pass_rate"] - cb["pass_rate"]) * max(ca["n"], cb["n"])
            res["chat_items"] = round(d, 2)
            if abs(d) > 1 + 1e-9:
                winner = na if d > 0 else nb
                why = "report metrics tied within 1 item; chat dev v3 pass rate decides (%+.1f items)" % d
            else:
                winner = a.fast
                why = "tied within noise on report metrics and chat: the faster candidate (%s)" % a.fast
    res.update(winner=winner, why=why)
    os.makedirs(a.out, exist_ok=True)
    json.dump(res, open(os.path.join(a.out, "compare.json"), "w"), indent=1)
    L = ["# rsn_v3 candidate choice: **%s**" % (winner or "none"), "", why, "",
         "Rule: only gate-passing candidates; more accurate on RWH + RWH-2 report metrics (items, 1-item noise), then chat dev v3 "
         "pass rate, then the faster (%s)." % a.fast, "", "| candidate | gate | dir |", "|---|---|---|"]
    L += ["| %s | %s | %s |" % (n, "PASS" if c["pass"] else "FAIL", c["dir"]) for n, c in res["candidates"].items()]
    if res["metrics"]:
        L += ["", "Item differences %s - %s on RWH + RWH-2 (positive = %s better): %s" % (na, nb, na, res["metrics"])]
    open(os.path.join(a.out, "COMPARE.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L[:3]))
    sys.exit(0 if winner else 1)


if __name__ == "__main__":
    main()
