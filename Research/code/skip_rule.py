"""skip_rule.py: all-normal skip rule (owner 2026-11-26), recomputed OFFLINE from runs/full/records.jsonl (no reruns).
Rule: when every flagged sensor's domain agent (valid finding status, else the rule status) AND its rule status say normal,
the reasoner is NOT called and the report is a deterministic normal (severity normal, label normal_operation); host cost = agents only.
Variant 'skip+ctx' also requires every context sensor's rule status to be normal. Otherwise the full path is unchanged (all sensors sent).
Output results/skip_rule.json + markdown on stdout (pasted into RESULTS.md)."""
import json, numpy as np
RUN = "runs/full"
R = [json.loads(l) for l in open(RUN + "/records.jsonl")]
RNG = np.random.default_rng(13)


def st(a):
    f = a.get("finding") if a.get("valid") else None
    return (f or {}).get("status") or (a.get("rule") or {}).get("status")


def all_normal(r, ctx):
    ok = all(st(a) == "normal" and (a.get("rule") or {}).get("status") == "normal" for a in r["agents"])
    if ctx:
        ok = ok and all((c.get("rule") or {}).get("status") == "normal" for c in r["context_sensors"])
    return ok


NORMAL = dict(severity="normal", label="normal_operation")


def arm(r, mode):
    if mode != "full" and all_normal(r, mode == "skip+ctx"):
        return NORMAL, r["agents_wall_s_total"], True
    return r["full"], r["agents_wall_s_total"] + (r["reasoner"].get("wall_s") or 0), False


def ci(v):
    v = np.array(v, float)
    if not len(v):
        return "-"
    bs = RNG.choice(v, (2000, len(v))).mean(1)
    return "%.1f [%.1f, %.1f]" % (100 * v.mean(), 100 * np.percentile(bs, 2.5), 100 * np.percentile(bs, 97.5))


B = [r for r in R if r["set"] == "B"]
Dn = [r for r in R if r["set"] == "D" and r["gold"]["severity"] == "normal"]
Df = [r for r in R if r["set"] == "D" and r["gold"]["severity"] == "sensor_fault"]
Fi = [r for r in R if r["set"] == "F" and r["kind"] != "natural" and r.get("gold") and r["gold"].get("label")]
A = [r for r in R if r["set"] == "A"]
js, md = {}, ["| arm | Set B both %% | Set B severity %% | Set B missed critical | D false alarm %% (n=%d) | D fault -> sensor_fault %% (n=%d) | F-injected both %% (n=%d) | reasoner calls skipped (B / D / F / A) | host s per case (B+D+F) |" % (len(Dn), len(Df), len(Fi)),
              "|---|---|---|---|---|---|---|---|---|"]
for mode in ("full", "skip", "skip+ctx"):
    def ev(rs):
        return [arm(r, mode) for r in rs]
    b = ev(B); both = [x.get("label") == r["gold"]["label"] and x.get("severity") == r["gold"]["severity"] for (x, _, _), r in zip(b, B)]
    sev = [x.get("severity") == r["gold"]["severity"] for (x, _, _), r in zip(b, B)]
    crit = [(x, r) for (x, _, _), r in zip(b, B) if r["gold"]["severity"] == "critical"]
    miss = sum(1 for x, r in crit if x.get("severity") != "critical")
    fa = [x.get("severity") != "normal" for x, _, _ in ev(Dn)]
    sf = [x.get("severity") == "sensor_fault" for x, _, _ in ev(Df)]
    f = ev(Fi); fb = [x.get("label") == r["gold"]["label"] and x.get("severity") == r["gold"]["severity"] for (x, _, _), r in zip(f, Fi)]
    sk = [sum(s for _, _, s in ev(rs)) for rs in (B, Dn + Df, Fi, A)]
    cost = np.mean([c for _, c, _ in ev(B + Dn + Df + Fi)])
    js[mode] = dict(B_both=float(np.mean(both)), B_sev=float(np.mean(sev)), B_missed_critical=[miss, len(crit)], D_false_alarm=float(np.mean(fa)), D_fault_sf=float(np.mean(sf)),
                    F_both=float(np.mean(fb)) if fb else None, skipped=dict(B=sk[0], D=sk[1], F=sk[2], A=sk[3]), host_s=float(cost))
    md.append("| %s | %s | %s | %d/%d | %s | %s | %s | %d / %d / %d / %d | %.2f |" % (mode, ci(both), ci(sev), miss, len(crit), ci(fa), ci(sf), ci(fb), *sk, cost))
# skipped F / A cases whose gold (F) is not normal: what the skip would hide
hid = [r["id"] for r in Fi if all_normal(r, False) and r["gold"]["severity"] != "normal"]
md.append("")
md.append("- Skipped F-injected cases with a non-normal gold (the skip hides a real event): %s. Set A (natural, unscored): the skip fires on %d of %d windows." % (", ".join(hid) or "none", js["skip"]["skipped"]["A"], len(A)))
json.dump(js, open("results/skip_rule.json", "w"), indent=1)
print("\n".join(md))
