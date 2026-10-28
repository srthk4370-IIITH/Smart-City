"""Score post-rules on stored v2 outputs, per slice. Prints a short summary; full tables -> --out JSON.

  python eval_rules.py --sets dev rw5dev --rules limit rel_power ... [--combo limit,floor] [--out f.json]
Each rule alone (and each --combo) vs v2 as stored. 'worst' = largest drop (pts) over all slices with n >= MIN_N and
keys pattern/status/cause/fault_kind/policy; 'gate' = target improves and worst drop <= 1 pt.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

import trackb_lib as L

GATE_KEYS = ("pattern", "status", "cause", "fault_kind", "policy", "event_active")
MIN_N = 10


def summarise(tab):
    gains, drops = [], []
    for s, row in tab.items():
        if row["n"] < MIN_N:
            continue
        for k in GATE_KEYS:
            if k not in row:
                continue
            n, b, a, w, l = row[k]
            d = 100.0 * (a - b) / n
            if d > 0:
                gains.append((d, s, k, n, b, a, w, l))
            elif d < 0:
                drops.append((d, s, k, n, b, a, w, l))
    return sorted(gains, reverse=True), sorted(drops)


def fmt(t):
    d, s, k, n, b, a, w, l = t
    return f"{s}.{k} {100*b/n:.1f}->{100*a/n:.1f} ({d:+.1f}, W/L {w}/{l}, n={n})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", nargs="+", default=["dev", "rw5dev"])
    ap.add_argument("--rules", nargs="*", default=list(L.RULES))
    ap.add_argument("--combo", nargs="*", default=[])
    ap.add_argument("--out")
    ap.add_argument("--show", type=int, default=4)
    ap.add_argument("--tag", default="v2cuda")
    a = ap.parse_args()
    res = {}
    runs = [(r, [r]) for r in a.rules] + [(c, c.split(",")) for c in a.combo]
    for ds in a.sets:
        for name, rules in runs:
            pairs, ch = L.run_rules(ds, rules, a.tag)
            tab = L.slice_table(pairs)
            gains, drops = summarise(tab)
            kc = Counter(k for c in ch for _, k, _, _ in c["changes"])
            allr = tab["ALL"]
            tot = " ".join(f"{k} {allr[k][3]}/{allr[k][4]}" for k in ("pattern", "status", "cause", "fault_kind", "policy") if k in allr)
            worst = drops[0][0] if drops else 0.0
            print(f"[{ds}] {name}: rows changed {len(ch)} {dict(kc)} | ALL W/L {tot} | worst {worst:+.1f}")
            for g in gains[:a.show]:
                print("   +", fmt(g))
            for d in drops[:a.show]:
                print("   -", fmt(d))
            res[f"{ds}:{name}"] = {"table": tab, "changes": ch}
    if a.out:
        with open(a.out, "w") as f:
            json.dump(res, f, default=str)


if __name__ == "__main__":
    main()
