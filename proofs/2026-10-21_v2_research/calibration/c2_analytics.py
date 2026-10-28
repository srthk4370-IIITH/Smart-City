"""Accuracy analytics for the v2 agent on the device (no retrain): where pattern / status / cause go wrong.

  py -3 c2_analytics.py            (after c0_rows.py; reads rows.json, writes analytics.md + analytics.json)

Sources: placement_v2 + placement_s24 (real sensor data with an injected, known pattern; truth = pattern only,
clean -> stable) and host400 + test_all (teacher-labelled test rows: pattern, status, cause).
"3 h" = placement d = 36 (180 min after onset) at the window the app's 3 h refinement would pick
(features_v2.go WindowN('3h', early pattern, early status, age 36): the early call = d 8, n 48).
Status checks re-apply the teacher's own status rule (training/generate_dataset.status_of) to the numbers the
prompt shows (E1 last, E2 max, E3 min, LIMITS): on placement rows with the TRUE pattern ("teacher-rule
status"), on test rows with the model's OWN pattern (what a backend status rule would give).
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAIN = HERE.parents[2] / "Code" / "smart-city-edge-agent" / "training"
sys.path.insert(0, str(TRAIN))
import features as F  # noqa: E402
import generate_dataset as G  # noqa: E402

PLACE = ("placement_v2", "placement_s24")
TESTS = ("host400", "test_all")
SEV = {"normal": 0, "warning": 1, "critical": 2, "sensor_fault": 3}


def wil(k, n, z=1.96):
    if n == 0:
        return "-"
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{100 * p:.0f}% [{100 * max(0, c - h):.0f}-{100 * min(1, c + h):.0f}] n={n}"


def fam(p):
    return {"flatline": "flat", "spike": "transient", "dip": "transient", "erratic": "noisy", "oscillation": "noisy",
            "stable": "stable", "gradual_increase": "trend", "gradual_decrease": "trend", "exponential_increase": "trend",
            "step_increase": "step", "step_decrease": "step", "throttling": "step"}.get(p, "invalid")


def window_3h(early_pat, early_status):
    f = fam(early_pat)
    if early_status == "sensor_fault":
        return 144 if f in ("flat", "noisy") else 96
    if f == "flat" or f == "noisy":
        return 144
    if f in ("transient", "invalid", "step"):
        return 96
    return 48


def teacher_status(role, metric, pattern, r):
    """generate_dataset.status_of on the prompt's numbers (limit metrics only; base mean = first SERIES mean)."""
    if (role, metric) not in F.METRICS or r.get("last") is None or r.get("max") is None:
        return None
    m = F.METRICS[(role, metric)]
    if m["warn"] is None:
        return None
    st = {"last": r["last"], "max": r["max"], "min": r["min"], "range": r["max"] - r["min"], "mean": r["last"]}
    base = r["series_head"][0] if r.get("series_head") else r["last"]
    try:
        return G.status_of(role, metric, pattern, st, base)
    except Exception:  # noqa: BLE001
        return None


def table(rows, key, ok="ok_pattern", minn=1, sort_by_err=True, head=None):
    g = defaultdict(list)
    for r in rows:
        if r.get(ok) is not None:
            g[key(r)].append(bool(r[ok]))
    items = [(k, v) for k, v in g.items() if len(v) >= minn]
    items.sort(key=(lambda kv: (sum(kv[1]) / len(kv[1]), -len(kv[1]))) if sort_by_err else (lambda kv: str(kv[0])))
    if head:
        items = items[:head]
    return [(k, sum(v), len(v)) for k, v in items]


def md_table(title, rows, cols=("key", "accuracy [Wilson 95%]", "errors")):
    out = [f"\n### {title}\n", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for k, s, n in rows:
        out.append(f"| {k if not isinstance(k, tuple) else ' / '.join(map(str, k))} | {wil(s, n)} | {n - s} |")
    return out


SUGGESTIONS = """
## 4. Suggestions that need no retraining (written from the 2026-10-21 run of this script; recheck the numbers above after a rerun)

1. **Do not add a backend status override for limit metrics.** On the test rows with LIMITS, the model's status is already 94%. The teacher's own status_of applied to the model's pattern scores 92%: it would fix 7 rows and break 23, all of them sensor_fault rows where the v2 fault rules override the limit rule. The hybrid version (keep sensor_fault, otherwise apply the limit rule) changes nothing on these rows: 579/613 either way. The LIMITS line and the teacher agree (Go Metrics = training METRICS). The only mismatch is wording: the prompt says "above X" while the teacher uses >= X, which matters only when a value sits exactly at the limit.
2. **Status errors are concentrated in roles that have no LIMITS line** (power 67%, water 71% on the test rows, against 95% for air quality). The teacher grades power_kw and water flow/level by relative change, `(max-min)/start level`: above 1.5 gives critical, above 0.3 on a trend gives warning. The prompt never states that rule. Typical errors: a large step_increase or throttling with a relative change of 7-34 called normal (gold critical), and moderate power drops (relative change 0.4-1.0) called normal (gold warning). A narrow backend escalation (model pattern in {step_increase, exponential_increase, throttling, spike, dip, step_decrease}, model status normal, relative change > 1.5 -> critical) would fire 10 times on the test rows: 6 fixes and 3 breaks (routine startup, recurring spike, short cycle). That is too few rows to adopt. It would also change alerting, so it is reported here, not implemented. A fair test needs labelled power/water placement events with status truth.
3. **A placement-design caveat, not a model error.** On air-quality and power-factor sensors, 373 placement rows with an injected step_increase or step_decrease were called sensor_fault, because the v2 teacher's bias/bias_jump fault family looks like a step. Likewise, 192 flow flatlines injected at 0 L look like idle flow. A placement truth that allows "step or bias fault" would score these fairly. Without that, status agreement on placement (79%) understates the model.
4. **Clean-window false alarms (placement, n=600):** power 33%, water 22%, air 17%. The main ones:
   - power_kw critical/spike (42): real load spikes in "clean" windows. The teacher grades any unexplained spike >= warning, so these are label-consistent.
   - flow sensor_fault/flatline (20): long zero-flow runs at 8/12 h.
   - pf sensor_fault/flatline (11): pf pinned at 0.999.

   The pf case is the one clean rule candidate. A backend downgrade "pf flatline at >= 0.995 -> normal" would remove 9 clean false alarms and break no true flatline in either placement seed, but it contradicts the teacher (any non-zero flatline is a sensor_fault), so it needs a labelling decision first.
5. **Cause:** most cause errors follow from an upstream error (pattern wrong 74, status wrong 14, both right 12). Deriving the cause in the backend with the v1 teacher cause_of scores worse than the model: 82% against 87%. It breaks 31 air-quality rows (normal_conditions -> outdoor_pollution_ingress) that the v2 routine rules label normal. So keep the model's cause. The cheap win is the water flow possible_leak <-> high_demand/normal_usage pair (7 errors), which depends only on off-hours (22:00-06:00). The prompt shows the window time, but the agent ignores it. A backend rule for water flow (step_increase/exponential_increase or stable non-zero flow off-hours -> possible_leak, which is the teacher's rule) fixes 4 of the 26 rule-fixes above. It would change a cause label but not alerting.
6. **Pattern at 3 h** (app chain, both seeds, 87% [84-90]):
   - exponential_increase -> gradual_increase is the largest single error (12 of 46), mostly on WM-WF-KH98-40 (8).
   - spike -> stable (9) is next, mostly SR-EM-KH04-01 (5); the event is over at 3 h, and the refinement "event over" rule already keeps the early spike.

   The worst sensors are SR-EM-KH04-02 (69%), WM-WF-KH98-40 (81%) and SR-EM-KH04-01 (84%). Air quality is at 98%. A curvature-based backend override does not work: E7 curvature > 0 on 143 true gradual_increase rows against 60 true exponential_increase rows (placement_v2, d >= 18, model said gradual_increase), and curvature/slope > 1 gives 129 against 60. These two patterns are not separable from the evidence lines. The useful lever is to treat both as the same family in alerting and in the title (both are "rising").
7. **Confidence is now informative (D4):** answers whose onset is <= 6 readings old, or dated to the start of a long window, get 0.16-0.69. The UI can show these as "tentative" without any model change, using a threshold such as < 0.7. That would be a display change only.
"""


def main():
    R = json.load(open(HERE / "rows.json", encoding="utf-8"))
    P = [r for r in R if r["src"] in PLACE]
    T = [r for r in R if r["src"] in TESTS]
    J, md = {}, ["# v2 agent accuracy analytics (device, no retrain)", "",
                 f"Rows: placement {len(P)} (placement_v2 + placement_s24), teacher-labelled test {len(T)} (host400 + test_all, deduplicated).",
                 "Pattern scoring is exact match (common_v2). Wilson 95% intervals. Generated by c2_analytics.py."]

    # ---------------------------------------------------------------- the 3 h app chain on placement
    key = {(r["src"], r["id"], r["d"], r["n"]): r for r in P}
    chain = []
    for r in P:
        if r["d"] == 36 and not r["clean"]:
            e = key.get((r["src"], r["id"], 8, 48))
            if e and r["n"] == window_3h(e["pred"], e["pred_status"]):
                chain.append(dict(r, early=e["pred"], early_status=e["pred_status"]))
    J["chain_3h_acc"] = (sum(r["ok_pattern"] for r in chain), len(chain))
    md.append(f"\n## 1. Pattern errors\n\nApp chain at 3 h (d=36 at the WindowN window): {wil(*J['chain_3h_acc'])}.")
    md += md_table("Placement events, 3 h app chain: by role", table(chain, lambda r: r["role"]))
    md += md_table("Placement events, 3 h app chain: by metric", table(chain, lambda r: (r["role"], r["metric"])))
    md += md_table("Placement events, 3 h app chain: by true pattern (worst first)", table(chain, lambda r: r["gold_pattern"]))
    conf3 = defaultdict(Counter)
    for r in chain:
        if not r["ok_pattern"]:
            conf3[r["gold_pattern"]][r["pred"]] += 1
    md.append("\n3 h confusions (true -> predicted, count): " + "; ".join(
        f"{t} -> " + ", ".join(f"{p} {c}" for p, c in cc.most_common(3)) for t, cc in sorted(conf3.items(), key=lambda kv: -sum(kv[1].values()))))
    worst_nodes = table(chain, lambda r: r["node"], minn=4, head=15)
    md += md_table("Worst sensors (node ids) at 3 h, >= 4 events (both seeds)", worst_nodes)
    J["worst_nodes_3h"] = worst_nodes
    nodepat = defaultdict(Counter)
    for r in chain:
        if not r["ok_pattern"]:
            nodepat[r["node"]][f'{r["gold_pattern"]}->{r["pred"]}'] += 1
    md.append("\nWhat those sensors get wrong: " + "; ".join(
        f"{k}: " + ", ".join(f"{a} {c}" for a, c in nodepat[k].most_common(3)) for k, s, n in worst_nodes[:8] if n - s > 0))
    # all delays: role / node / month
    ev = [r for r in P if not r["clean"]]
    md += md_table("Placement events, all ages and windows: by role x readings since onset", table(ev, lambda r: (r["role"], f"d={r['d']:02d}"), sort_by_err=False))
    md += md_table("Placement (events + clean): by month of the window", table(P, lambda r: r["month"], sort_by_err=False))
    md += md_table("Placement clean windows: called 'stable' (by role)", table([r for r in P if r["clean"]], lambda r: r["role"], sort_by_err=False))
    md += md_table("Test rows: pattern by role", table(T, lambda r: r["role"], sort_by_err=False))
    md += md_table("Test rows: pattern by month", table(T, lambda r: r["month"], sort_by_err=False))
    md += md_table("Test rows: worst sensors (>= 5 rows)", table(T, lambda r: r["node"], minn=5, head=12))
    md += md_table("Test rows: worst gold patterns (>= 5 rows)", table(T, lambda r: r["gold_pattern"], minn=5, head=12))

    # ---------------------------------------------------------------- status
    md.append("\n## 2. Status (normal / warning / critical / sensor_fault)")
    md += md_table("Test rows: status accuracy by role", table(T, lambda r: r["role"], ok="ok_status", sort_by_err=False))
    cm = defaultdict(Counter)
    for r in T:
        cm[r["role"]][(r["gold_status"], r["pred_status"])] += 1
    md.append("\nTest rows: status confusions (gold -> predicted, errors only):")
    for role, c in sorted(cm.items()):
        md.append(f"- {role}: " + ", ".join(f"{g}->{p} {k}" for (g, p), k in c.most_common() if g != p))
    cw = sum(k for c in cm.values() for (g, p), k in c.items() if {g, p} == {"warning", "critical"})
    J["test_crit_warn_confusions"] = cw
    # backend status rule with the model's own pattern
    rows_lim, rule_ok, mod_ok, fixed, broke = 0, 0, 0, Counter(), Counter()
    for r in T:
        ts = teacher_status(r["role"], r["metric"], r["pred"], r)
        if ts is None or r["gold_status"] is None:
            continue
        rows_lim += 1
        rule_ok += ts == r["gold_status"]; mod_ok += r["pred_status"] == r["gold_status"]
        if ts == r["gold_status"] and r["pred_status"] != r["gold_status"]:
            fixed[(r["gold_status"], r["pred_status"])] += 1
        if ts != r["gold_status"] and r["pred_status"] == r["gold_status"]:
            broke[(r["gold_status"], ts)] += 1
    J["test_status_rule_vs_model"] = {"rows": rows_lim, "rule_ok": rule_ok, "model_ok": mod_ok,
                                      "fixed": {f"{a}->{b}": v for (a, b), v in fixed.items()}, "broken": {f"{a}->{b}": v for (a, b), v in broke.items()}}
    md.append(f"\nTest rows with LIMITS (limit metrics, n={rows_lim}): model status {wil(mod_ok, rows_lim)}; the teacher's status rule "
              f"applied in the backend to the model's own pattern and the prompt numbers {wil(rule_ok, rows_lim)}. "
              f"The rule would fix {sum(fixed.values())} ({dict(fixed)}) and break {sum(broke.values())} ({dict(broke)}).")
    # placement: teacher-rule status (true pattern) vs model status
    pl = []
    for r in P:
        ts = teacher_status(r["role"], r["metric"], r["gold_pattern"], r)
        if ts is not None:
            pl.append(dict(r, t_status=ts, ok_t=r["pred_status"] == ts, rule_own=teacher_status(r["role"], r["metric"], r["pred"], r)))
    md += md_table("Placement, limit metrics: model status vs teacher-rule status (true pattern), by role x d", table(pl, lambda r: (r["role"], f"d={r['d']:02d}"), ok="ok_t", sort_by_err=False))
    pc = Counter((r["t_status"], r["pred_status"]) for r in pl if not r["ok_t"])
    md.append("\nPlacement status confusions vs teacher rule (rule -> model): " + ", ".join(f"{a}->{b} {k}" for (a, b), k in pc.most_common(10)))
    own_ok = sum(r["rule_own"] == r["t_status"] for r in pl)
    md.append(f"\nPlacement, limit metrics (n={len(pl)}): model status agrees with the teacher rule {wil(sum(r['ok_t'] for r in pl), len(pl))}; "
              f"the rule applied to the model's OWN pattern agrees {wil(own_ok, len(pl))}.")
    J["placement_status_vs_rule"] = {"n": len(pl), "model": sum(r["ok_t"] for r in pl), "rule_on_own_pattern": own_ok,
                                     "confusions": {f"{a}->{b}": k for (a, b), k in pc.most_common()}}
    # which number drives status: last vs max
    drv = Counter()
    for r in pl:
        if r["ok_t"] or r["pred_status"] not in ("warning", "critical") and r["t_status"] not in ("warning", "critical"):
            continue
        m = F.METRICS[(r["role"], r["metric"])]
        if m["dir"] != "high":
            continue
        sev = lambda v: 2 if v >= m["crit"] else 1 if v >= m["warn"] else 0  # noqa: E731
        drv[("model=max-level" if SEV.get(r["pred_status"], -1) == sev(r["max"]) else
             "model=last-level" if SEV.get(r["pred_status"], -1) == sev(r["last"]) else "model=neither",
             "rule uses " + ("max" if r["gold_pattern"] in ("spike", "throttling") else "last"))] += 1
    md.append("\nPlacement status disagreements on high-limit metrics, which value the model's status matches: " +
              ", ".join(f"{a} / {b}: {k}" for (a, b), k in drv.most_common()))
    J["status_driver"] = {f"{a}|{b}": k for (a, b), k in drv.items()}
    # boundary: value within 5% of a limit
    near = [r for r in pl if r["t_status"] in ("warning", "critical") or r["pred_status"] in ("warning", "critical")]
    nb = []
    for r in near:
        m = F.METRICS[(r["role"], r["metric"])]
        v = r["max"] if r["gold_pattern"] in ("spike", "throttling") else r["last"]
        if m["dir"] == "low":
            v = r["min"] if r["gold_pattern"] in ("spike", "dip") else r["last"]
        close = any(abs(v - L) <= 0.05 * abs(L) for L in (m["warn"], m["crit"]))
        nb.append(dict(r, close=close))
    md += md_table("Placement status (alerting rows) by closeness of the deciding value to a limit (within 5%)", table(nb, lambda r: "near a limit" if r["close"] else "clear of limits", ok="ok_t", sort_by_err=False))
    # clean false alarms by role and status
    cl = [r for r in P if r["clean"]]
    md.append("\nPlacement clean windows, status != normal (false alarm): " + ", ".join(
        f"{ro} {wil(sum(r['pred_status'] != 'normal' for r in cl if r['role'] == ro), sum(1 for r in cl if r['role'] == ro))}" for ro in sorted({r['role'] for r in cl})))
    fa = Counter((r["role"], r["metric"], r["pred_status"], r["pred"]) for r in cl if r["pred_status"] != "normal")
    md.append("\nTop clean false alarms (role, metric, status, pattern): " + ", ".join(f"{'/'.join(map(str, k))} {v}" for k, v in fa.most_common(8)))

    # ---------------------------------------------------------------- cause
    md.append("\n## 3. Cause (test rows; placement has no cause truth)")
    md += md_table("Cause accuracy by role", table(T, lambda r: r["role"], ok="ok_cause", sort_by_err=False))
    cc = defaultdict(Counter)
    for r in T:
        if not r["ok_cause"]:
            cc[r["role"]][(r["gold_cause"], r["pred_cause"])] += 1
    for role, c in sorted(cc.items()):
        md.append(f"- {role}: " + ", ".join(f"{g}->{p} {k}" for (g, p), k in c.most_common(5)))
    expl = Counter()
    for r in T:
        if r["ok_cause"] is False:
            expl["pattern also wrong" if not r["ok_pattern"] else "status also wrong" if not r["ok_status"] else "pattern+status right"] += 1
    md.append("\nCause errors explained by an upstream error: " + ", ".join(f"{k} {v}" for k, v in expl.most_common()))
    J["cause_error_upstream"] = dict(expl)
    # backend cause_of with the model's own pattern + status (v1 teacher rule; v2 routine rules not modelled)
    dc_rows = dc_ok = mc_ok = 0
    dfix, dbreak = Counter(), Counter()
    for r in T:
        if r["role"] not in ("air_quality", "water", "power", "weather") or not r.get("end_epoch"):
            continue
        try:
            c = G.cause_of(r["role"], r["metric"], r["pred"], r["pred_status"], F.is_off_hours(r["end_epoch"]), r["node"].startswith("SR-"), abs(r["last"] or 0) < 1e-6)
        except Exception:  # noqa: BLE001
            continue
        if r["pred_status"] == "sensor_fault":
            c = "sensor_fault"
        dc_rows += 1; dc_ok += c == r["gold_cause"]; mc_ok += r["pred_cause"] == r["gold_cause"]
        if c == r["gold_cause"] and r["pred_cause"] != r["gold_cause"]:
            dfix[(r["role"], r["gold_cause"], r["pred_cause"])] += 1
        if c != r["gold_cause"] and r["pred_cause"] == r["gold_cause"]:
            dbreak[(r["role"], r["gold_cause"], c)] += 1
    md.append(f"\nCause derived in the backend by the teacher's cause_of(model pattern, model status, off-hours, indoor) vs the model's cause "
              f"(n={dc_rows}): rule {wil(dc_ok, dc_rows)}, model {wil(mc_ok, dc_rows)}; rule fixes {sum(dfix.values())}, breaks {sum(dbreak.values())}.")
    md.append("Fixes: " + ", ".join(f"{'/'.join(map(str, k))} {v}" for k, v in dfix.most_common(6)))
    md.append("Breaks: " + ", ".join(f"{'/'.join(map(str, k))} {v}" for k, v in dbreak.most_common(6)))
    J["cause_rule_vs_model"] = {"n": dc_rows, "rule_ok": dc_ok, "model_ok": mc_ok}
    md.append(SUGGESTIONS)
    (HERE / "analytics.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    json.dump(J, open(HERE / "analytics.json", "w"), indent=1, default=str)
    print("\n".join(md))


if __name__ == "__main__":
    main()
