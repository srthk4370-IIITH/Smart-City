#!/usr/bin/env python3
"""Early-AI gate study analysis: raw/rows_s*.jsonl -> raw/summary.json + printed tables.
Per row: the app's Mode-3 report (agents B50 + reasoner rsn_v3_4b_r3) on the event after k = 3..8 abnormal readings.
Reference = the same event's k = 8 run (the current gate). Gold = teacher status at k = 8 (event family truth).
  sev_ok   : report severity == gold status (critical / warning / sensor_fault / normal->normal)
  cls_ok   : sensor-fault vs process call right (label or severity sensor_fault <=> gold sensor_fault)
  flip     : early severity or label differs from the k = 8 report of the same event
  chk      : Jaccard of checklist action sets vs k = 8
A shape clears k when, over groups where both runs produced a valid AI report: paired sev_ok and cls_ok drops vs k = 8 are
<= 5 pp AND not significant (losses - wins < 2 * sqrt(losses + wins)), and the flip rate is <= 15 %."""
import glob, json, math, sys
from collections import defaultdict
from pathlib import Path

P = Path(__file__).resolve().parent.parent / (sys.argv[1] if len(sys.argv) > 1 else "raw")  # v5 rerun: analyze.py raw_v5
rows = {}
for f in sorted(glob.glob(str(P / "rows_s*.jsonl"))):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        rows[r["id"]] = r
G = defaultdict(dict)
for r in rows.values():
    G[r["group"]][r["k"]] = r
SEV = {"critical": "critical", "warning": "warning", "sensor_fault": "sensor_fault", "normal": "normal"}


def sev(r):  # the severity the app shows (after finaliseSeverity / severityGuard), else the report's
    return r.get("inc_severity") or r.get("severity")


def ai(r):
    return r and r.get("gated") and r.get("valid") and r.get("severity") and "rules" not in (r.get("source") or "")


def is_fault(r):
    return sev(r) == "sensor_fault" or r.get("label") == "sensor_fault"


out, tab = {}, []
shapes = sorted({r["shape"] for r in rows.values()})
for sh in shapes + ["ALL"]:
    gs = [g for g in G.values() if sh == "ALL" or next(iter(g.values()))["shape"] == sh]
    res = {}
    for k in range(3, 9):
        n = gated = valid = 0
        sev8 = sevk = cls8 = clsk = fl = fl_sev = fl_lab = both = 0
        sw = sl = cw = cl = 0
        jac = []
        for g in gs:
            r, r8 = g.get(k), g.get(8)
            if not r or not r8 or r.get("error"):
                continue
            n += 1
            gated += bool(r.get("gated"))
            valid += bool(ai(r))
            if not (ai(r) and ai(r8)):
                continue
            both += 1
            gold = SEV.get(r8["gold_status"], r8["gold_status"])
            gf = r8["gold_status"] == "sensor_fault"
            a8, ak = sev(r8) == gold, sev(r) == gold
            c8, ck = is_fault(r8) == gf, is_fault(r) == gf
            sev8 += a8; sevk += ak; cls8 += c8; clsk += ck
            sw += ak and not a8; sl += a8 and not ak; cw += ck and not c8; cl += c8 and not ck
            fs, flb = sev(r) != sev(r8), r["label"] != r8["label"]
            fl_sev += fs; fl_lab += flb; fl += fs or flb
            a, b = set(r.get("checklist") or []), set(r8.get("checklist") or [])
            jac.append(len(a & b) / len(a | b) if a | b else 1.0)
        d = lambda x, y: (x - y) / both * 100 if both else 0.0
        sig = lambda w, l: (l - w) >= 2 * math.sqrt(l + w) and l > w
        clear = both >= 8 and d(sevk, sev8) >= -5 and d(clsk, cls8) >= -5 and not sig(sw, sl) and not sig(cw, cl) and fl / both <= 0.15
        res[k] = dict(n=n, gated=gated, ai_valid=valid, paired=both, sev_acc=round(sevk / both, 3) if both else None,
                      sev_acc_k8=round(sev8 / both, 3) if both else None, sev_d_pp=round(d(sevk, sev8), 1), sev_wins=sw, sev_losses=sl,
                      cls_acc=round(clsk / both, 3) if both else None, cls_acc_k8=round(cls8 / both, 3) if both else None,
                      cls_d_pp=round(d(clsk, cls8), 1), flip=round(fl / both, 3) if both else None,
                      flip_sev=round(fl_sev / both, 3) if both else None, flip_label=round(fl_lab / both, 3) if both else None,
                      checklist_jaccard=round(sum(jac) / len(jac), 3) if jac else None, clear=bool(clear) if k < 8 else None)
    ks = [k for k in range(3, 8) if res[k]["clear"] and all(res[j]["clear"] for j in range(k, 8))]
    out[sh] = dict(by_k=res, min_k=min(ks) if ks else None)
    for k in range(3, 9):
        x = res[k]
        tab.append(f"{sh:8} k{k} n{x['n']:3} gated{x['gated']:3} ai{x['ai_valid']:3} paired{x['paired']:3} "
                   f"sev {x['sev_acc']}/{x['sev_acc_k8']} ({x['sev_d_pp']:+} pp, w{x['sev_wins']} l{x['sev_losses']}) "
                   f"cls {x['cls_acc']}/{x['cls_acc_k8']} ({x['cls_d_pp']:+}) flip {x['flip']} (sev {x['flip_sev']} lab {x['flip_label']}) "
                   f"chk {x['checklist_jaccard']} clear {x['clear']}")
    tab.append(f"{sh:8} -> min clear k = {out[sh]['min_k']}")
(P / "summary.json").write_text(json.dumps({"rows": len(rows), "groups": len(G), "shapes": out}, indent=1))
print("\n".join(tab))
