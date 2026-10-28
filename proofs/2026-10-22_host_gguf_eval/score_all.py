"""Score the host GGUF outputs (raw/<tag>/outputs.jsonl) with the device-eval code (common_v2.score_one for host400,
placement_v2.analyze rules for the placement rows, sim_chain_s24 logic for the app chain), compare v2 vs 3d
(Wilson CIs, exact paired McNemar) and v2-on-host vs v2-on-device (proofs/2026-10-21_v2_confirm).
  py -3 score_all.py      -> results.json, tables.md, stages.svg"""
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
Q = HERE.parents[1]
sys.path.insert(0, str(Q / "Code/smart-city-edge-agent/training/v2/post"))
sys.path.insert(0, str(HERE))
import common_v2 as C  # noqa: E402
from run_phases import windown  # noqa: E402  (verbatim sim_chain_s24 WindowN policy)

CONF = Q / "proofs/2026-10-21_v2_confirm"
TAGS = ["v2", "3d"]
QUIET = {"stable", "vacant", "occupied"}


def rows(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if Path(p).exists() else []


def W(k, n):
    return {"rate": round(k / n, 3), "k": k, "n": n, "ci95": C.wilson(k, n)} if n else None


def fmt(w):
    return f"{100 * w['rate']:.1f} [{100 * w['ci95'][0]:.0f}-{100 * w['ci95'][1]:.0f}] ({w['k']}/{w['n']})" if w else "-"


def pair(a, b, ids):
    """a, b: {id: bool}; exact McNemar on ids present in both."""
    ids = [i for i in ids if a.get(i) is not None and b.get(i) is not None]
    if not ids:
        return None
    m = C.mcnemar([a[i] for i in ids], [b[i] for i in ids])
    return {"n": len(ids), "a": W(sum(a[i] for i in ids), len(ids)), "b": W(sum(b[i] for i in ids), len(ids)),
            "only_a": m["only_a"], "only_b": m["only_b"], "p": m["p"]}


def mc(pr):
    return f"{pr['only_a']} / {pr['only_b']}, p={pr['p']}" if pr else "-"


# ------------------------------------------------------------------ outputs
OUT = {t: {o["key"]: o for o in rows(HERE / "raw" / t / "outputs.jsonl")} for t in TAGS}
DEVP = {f"p|{r['id']}|{r['d']}|{r['n']}": r for r in rows(CONF / "placement_s24/samples.jsonl")}
DEVH = {f"h|{r['id']}": r for r in rows(CONF / "host400_k8/samples.jsonl")}
OUT["device_v2"] = {**DEVP, **DEVH}
SRC = TAGS + ["device_v2"]
res = {"rows": {s: len(OUT[s]) for s in SRC}}
md = ["# Host Q4_0 GGUF eval: v2 vs 3d (laptop CPU llama.cpp), and v2 host vs device\n",
      "Rows available: " + ", ".join(f"{t} {len(OUT[t])}" for t in SRC) + "\n"]

# ------------------------------------------------------------------ placement rows (placement_v2.analyze rules)
truth = {f"p|{p['id']}|{p['d']}|{p['n']}": p["truth"] for p in rows(CONF / "placement_s24/prompts.jsonl")}


def pscore(text, t):
    p = C.parse_answer(text)
    pat = C._norm(p.get("pattern", "")) if p else "INVALID"
    st = C._norm(p.get("status", "")) if p else "INVALID"
    return {"json": p is not None, "ok": pat == t["pattern"], "alarm": st != "normal",
            "flag": st != "normal" or pat not in QUIET, "pat": pat, "st": st}


PS = {s: {k: pscore(o["text"], truth[k]) for k, o in OUT[s].items() if k.startswith("p|")} for s in SRC}
cells = sorted({(int(k.split("|")[2]), int(k.split("|")[3])) for t in TAGS for k in PS[t]})
res["placement_cells"] = {}
md.append("\n## Placement seed 24, fixed window (pattern accuracy on events; clean d=0: false alarm = status != normal)\n")
md.append("| d (min) | n | metric | v2 host | 3d host | McNemar (only v2 / only 3d, p) | v2 device |\n|---|---|---|---|---|---|---|")
for d, n in cells:
    keys = [k for k in truth if k.split("|")[2:] == [str(d), str(n)]]
    met = ("alarm", "flag", "json") if d == 0 else ("ok", "json")
    for m in met:
        per = {s: {k: PS[s][k][m] for k in keys if k in PS[s]} for s in SRC}
        pr = pair(per["v2"], per["3d"], keys)
        cell = {s: W(sum(per[s].values()), len(per[s])) if per[s] else None for s in SRC}
        cell["paired_v2_vs_3d"] = pr
        res["placement_cells"][f"d={d}|n={n}|{m}"] = cell
        name = {"ok": "pattern", "alarm": "false alarm", "flag": "any flag", "json": "JSON valid"}[m]
        md.append(f"| {d} ({5 * d}) | {n} | {name} | {fmt(cell['v2'])} | {fmt(cell['3d'])} | {mc(pr)} | {fmt(cell['device_v2'])} |")


# ------------------------------------------------------------------ app chain (sim_chain_s24 logic, per source)
def raw_ps(text):
    try:
        o = json.loads(C.cut_at_action(text)[0])
        return o.get("pattern"), o.get("status")
    except Exception:  # noqa: BLE001
        return None, None


ctruth = {k.split("|")[1]: t["pattern"] for k, t in truth.items() if not t.get("clean")}
ev_ids = sorted(ctruth)
LAD = {"normal": 48, "warning": 96, "critical": 144, "sensor_fault": 144}
POL = {"WindowN (app)": lambda st, e, prev: windown(st, e[0], "sensor_fault" if prev[1] == "sensor_fault" else prev[1]),
       "fixed 4 h": lambda st, e, prev: 48,
       "old severity ladder": lambda st, e, prev: max(LAD.get(e[1], 48), LAD.get(prev[1], 48))}


def chain(src, pick):
    S = {k: raw_ps(o["text"]) for k, o in OUT[src].items() if k.startswith("p|")}
    r = {"20min": {}, "40min": {}, "1.5h": {}, "3h": {}, "n3h": {}}
    for i in ev_ids:
        e = S.get(f"p|{i}|8|48")
        if e is None:
            continue
        r["40min"][i] = e[0] == ctruth[i]
        if f"p|{i}|4|48" in S:
            r["20min"][i] = S[f"p|{i}|4|48"][0] == ctruth[i]
        n1 = pick("1.5h", e, e)
        if f"p|{i}|18|{n1}" not in S:
            continue
        r1 = S[f"p|{i}|18|{n1}"]
        p1 = r1[0]
        if e[0] in ("spike", "dip") and p1 == "stable":
            p1 = e[0]
        r["1.5h"][i] = p1 == ctruth[i]
        n2 = pick("3h", e, r1)
        if f"p|{i}|36|{n2}" not in S:
            continue
        p2 = S[f"p|{i}|36|{n2}"][0]
        if e[0] in ("spike", "dip") and p2 == "stable":
            p2 = e[0]
        r["3h"][i] = p2 == ctruth[i]
        r["n3h"][i] = n2
    return r


res["chain"] = {}
md.append("\n## App chain per stage (early call d=8 at 4 h; refine d=18 / d=36 at the policy's window; spike/dip keep rule)\n")
md.append("20min = the d=4 (n=48) call alone (no chain). A stage is reported only for cases whose needed rows exist.\n")
md.append("| policy | stage | v2 host | 3d host | McNemar (only v2 / only 3d, p) | v2 device | v2 host vs device: same correctness |\n|---|---|---|---|---|---|---|")
for pol, pick in POL.items():
    CH = {s: chain(s, pick) for s in SRC}
    res["chain"][pol] = {}
    for stage in ("20min", "40min", "1.5h", "3h"):
        a = {s: CH[s][stage] for s in SRC}
        if not a["v2"] and not a["3d"]:
            continue
        # a stage counts only if both host models cover all cases (otherwise partial policies are biased)
        if pol != "WindowN (app)" and (len(a["v2"]) < len(ev_ids) or len(a["3d"]) < len(ev_ids)):
            continue
        pr = pair(a["v2"], a["3d"], ev_ids)
        common = [i for i in ev_ids if i in a["v2"] and i in a["device_v2"]]
        agree = W(sum(a["v2"][i] == a["device_v2"][i] for i in common), len(common))
        e = {s: W(sum(a[s].values()), len(a[s])) if a[s] else None for s in SRC}
        e.update(paired_v2_vs_3d=pr, host_device_same_correctness=agree,
                 paired_host_vs_device=pair(a["v2"], a["device_v2"], ev_ids))
        res["chain"][pol][stage] = e
        md.append(f"| {pol} | {stage} | {fmt(e['v2'])} | {fmt(e['3d'])} | {mc(pr)} | {fmt(e['device_v2'])} | {fmt(agree)} |")
    for s in SRC:
        if CH[s]["3h"]:
            res["chain"][pol].setdefault("per_pattern_3h", {})[s] = {
                p: f"{sum(CH[s]['3h'][i] for i in CH[s]['3h'] if ctruth[i] == p)}/{sum(1 for i in CH[s]['3h'] if ctruth[i] == p)}"
                for p in sorted(set(ctruth.values()))}
            res["chain"][pol].setdefault("mean_n_3h", {})[s] = round(sum(CH[s]["n3h"].values()) / len(CH[s]["n3h"]), 1)
pp = res["chain"]["WindowN (app)"].get("per_pattern_3h", {})
if pp:
    md.append("\nPer-pattern 3 h (WindowN app chain):\n\n| pattern | " + " | ".join(pp) + " |\n|---|" + "---|" * len(pp))
    for p in sorted(set(ctruth.values())):
        md.append(f"| {p} | " + " | ".join(pp[s][p] for s in pp) + " |")

# ------------------------------------------------------------------ host400
ids = json.loads((Q / "proofs/2026-10-20_v2_post/eval_set.json").read_text())["ids"]
by = {r["id"]: r for r in C.read_jsonl(C.DATA / "test.jsonl")}
H = {s: {i: C.score_one(by[i], OUT[s][f"h|{i}"]["text"]) for i in ids if f"h|{i}" in OUT[s]} for s in SRC}
res["host400"] = {}
if H["v2"] or H["3d"]:
    groups = defaultdict(list)
    for i in ids:
        sc = H["device_v2"].get(i) or H["v2"].get(i) or H["3d"].get(i)
        if not sc:
            continue
        groups["ALL"].append(i)
        for g in ("age", "family", "role", "win"):
            groups[f"{g}={sc[g]}"].append(i)
        groups[f"negative={sc['negative']}"].append(i)
    MET = ("json", "pattern", "status", "cause", "action", "event_active", "onset_15", "evidence", "policy",
           "false_alarm", "fault_kind")
    md.append("\n## host400 (frozen eval set, common_v2.score_one; false_alarm: lower is better)\n")
    md.append("| group | metric | v2 host | 3d host | McNemar (only v2 / only 3d, p) | v2 device |\n|---|---|---|---|---|---|")
    order = ["ALL"] + [g for pre in ("age=", "family=", "role=", "win=", "negative=") for g in sorted(groups) if g.startswith(pre)]
    for g in order:
        gi = groups[g]
        res["host400"][g] = {}
        for m in MET:
            per = {s: {i: H[s][i][m] for i in gi if i in H[s] and H[s][i].get(m) is not None} for s in SRC}
            if not per["v2"] and not per["3d"]:
                continue
            e = {s: W(sum(per[s].values()), len(per[s])) if per[s] else None for s in SRC}
            e["paired_v2_vs_3d"] = pr = pair(per["v2"], per["3d"], gi)
            res["host400"][g][m] = e
            if g == "ALL" or m in ("pattern", "status", "cause", "json", "false_alarm"):
                md.append(f"| {g} | {m} | {fmt(e['v2'])} | {fmt(e['3d'])} | {mc(pr)} | {fmt(e['device_v2'])} |")

# ------------------------------------------------------------------ v2 host vs v2 device: does the host predict the device?
hd = {}
pk = [k for k in PS["v2"] if k in PS["device_v2"]]
if pk:
    ev = [k for k in pk if not truth[k].get("clean")]
    hd["placement_rows"] = {
        "n": len(pk),
        "same_pattern": W(sum(PS["v2"][k]["pat"] == PS["device_v2"][k]["pat"] for k in pk), len(pk)),
        "same_pattern_status": W(sum(PS["v2"][k]["pat"] == PS["device_v2"][k]["pat"] and PS["v2"][k]["st"] == PS["device_v2"][k]["st"] for k in pk), len(pk)),
        "same_pattern_correctness_events": W(sum(PS["v2"][k]["ok"] == PS["device_v2"][k]["ok"] for k in ev), len(ev)),
        "identical_answer_text": W(sum(C.cut_at_action(OUT["v2"][k]["text"])[0] == C.cut_at_action(OUT["device_v2"][k]["text"])[0] for k in pk), len(pk)),
        "pattern_acc_events_host_vs_device": pair({k: PS["v2"][k]["ok"] for k in ev}, {k: PS["device_v2"][k]["ok"] for k in ev}, ev)}
hk = [i for i in ids if i in H["v2"] and i in H["device_v2"]]
if hk:
    def same(i, ks):
        a, b = H["v2"][i]["pred"], H["device_v2"][i]["pred"]
        return bool(a and b and all(a[k] == b[k] for k in ks))
    hd["host400"] = {"n": len(hk), "same_pattern": W(sum(same(i, ("pattern",)) for i in hk), len(hk)),
                     "same_pattern_status_cause": W(sum(same(i, ("pattern", "status", "likely_cause")) for i in hk), len(hk)),
                     "identical_answer_text": W(sum(C.cut_at_action(OUT["v2"]["h|" + i]["text"])[0] == C.cut_at_action(OUT["device_v2"]["h|" + i]["text"])[0] for i in hk), len(hk))}
    for m in ("pattern", "status", "cause", "json"):
        hd["host400"][m] = pair({i: H["v2"][i][m] for i in hk}, {i: H["device_v2"][i][m] for i in hk}, hk)
        hd["host400"][m]["same_correctness"] = W(sum(H["v2"][i][m] == H["device_v2"][i][m] for i in hk), len(hk))
res["host_vs_device_v2"] = hd
md.append("\n## v2 host (laptop CPU ggml) vs v2 device (QIDK htpd), same rows (a = host, b = device)\n\n```\n" + json.dumps(hd, indent=1) + "\n```\n")
(HERE / "results.json").write_text(json.dumps(res, indent=1))
(HERE / "tables.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))

# ------------------------------------------------------------------ plot
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    labs, vals = [], {s: [] for s in SRC}

    def add(lab, getter):
        labs.append(lab)
        for s in SRC:
            vals[s].append(getter(s))
    for st, lab in (("20min", "20 min\n(d=4, n=48)"), ("40min", "alert 40 min\n(d=8, n=48)"), ("1.5h", "1.5 h refine\n(chain)"), ("3h", "3 h refine\n(chain)")):
        add(lab, lambda s, st=st: res["chain"]["WindowN (app)"].get(st, {}).get(s))
    add("clean\nfalse alarm", lambda s: res["placement_cells"].get("d=0|n=48|alarm", {}).get(s))
    for m in ("pattern", "status", "cause"):
        add(f"host400\n{m}", lambda s, m=m: res["host400"].get("ALL", {}).get(m, {}).get(s))
    fig, ax = plt.subplots(figsize=(12, 4.8))
    for j, (s, c) in enumerate(zip(SRC, ("#3b6ea8", "#d9822b", "#8a8a8a"))):
        xs = [i + (j - 1) * 0.27 for i in range(len(labs))]
        ys = [v["rate"] if v else 0 for v in vals[s]]
        err = [[(v["rate"] - v["ci95"][0]) if v else 0 for v in vals[s]], [(v["ci95"][1] - v["rate"]) if v else 0 for v in vals[s]]]
        ax.bar(xs, ys, 0.27, yerr=err, capsize=2, color=c,
               label={"v2": "v2 Q4_0 (laptop CPU)", "3d": "3d Q4_0 (laptop CPU)", "device_v2": "v2 Q4_0 (QIDK device, 2026-10-21)"}[s])
    ax.set_xticks(range(len(labs)))
    ax.set_xticklabels(labs, fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("rate (Wilson 95% CI)")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(HERE / "stages.svg")
except Exception as e:  # noqa: BLE001
    print("plot skipped:", e)
