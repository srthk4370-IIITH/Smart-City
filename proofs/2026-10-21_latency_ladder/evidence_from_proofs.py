"""Every number in PLAN.md section 2 that comes from data already on the laptop (no device access).
  py -3 evidence_from_proofs.py   -> evidence.json (+ a short printout)
Sources (read only):
  proofs/2026-10-21_v2_app/{chaos_v7,chaos_synthcache,stress}/stress_report.json   v2 chaos through the app
  proofs/2026-10-16_htpd_v6_app_stress_report_final.json                            v1 (htpd v6) chaos through the app
  proofs/2026-10-21_v2_app/{refine_v7,refine_stream,refine_combined,refine_d4,recheck4}/INC-*.json   single agents + synth
  proofs/2026-10-21_htpd_v7_ab/ab_*.json, run_ab.log                                 htpd-direct A/B (v7)
"""
import glob, json, re, statistics as st
from collections import Counter
from pathlib import Path

H = Path(__file__).resolve().parent
P = Path(r"C:\Users\hp\Desktop\qidk\proofs")
out = {}

# ---- chaos through the app (v2) and v1 for comparison
def chaos(path, label):
    d = json.load(open(path, encoding="utf-8"))
    temps = {}
    for r in d["results"]:
        m = re.match(r"(chaos \w+ #\d+): board below 80 C \((\d+) C\)", r["check"])
        if m:
            temps[m[1]] = int(m[2])
    rows = []
    for i in d["incidents"]:
        if not i["tag"].startswith("chaos"):
            continue
        n = len([a for a in i["agents"]])
        bad = [a["ref"] for a in i["agents"] if not a["valid"]]
        rows.append(dict(src=label, tag=i["tag"], id=i["id"], agents=n, roles=dict(Counter(a["role"] for a in i["agents"])),
                         npu_calls=i["npu_calls"], solo_reruns=max(0, i["npu_calls"] - n - 1), invalid_kept=bad,
                         total_s=round(i["total_ms"] / 1000, 1), board_c_after=temps.get(i["tag"])))
    return rows

v2 = []
for sub in ("chaos_v7", "chaos_synthcache", "stress"):
    v2 += chaos(P / "2026-10-21_v2_app" / sub / "stress_report.json", sub)
v1 = chaos(P / "2026-10-16_htpd_v6_app_stress_report_final.json", "v1_htpd_v6")
v2big = [r for r in v2 if r["agents"] >= 13]
out["chaos_v2"] = v2
out["chaos_v1"] = v1
out["chaos_summary"] = {
    "v2_13_14_agents_s": sorted(r["total_s"] for r in v2big),
    "v2_median_s": st.median(r["total_s"] for r in v2big),
    "v2_round1_s": [r["total_s"] for r in v2big if r["tag"].endswith("simultaneous #1")],
    "v2_later_rounds_s": [r["total_s"] for r in v2big if not r["tag"].endswith("simultaneous #1")],
    "v2_with_solo_rerun": sum(1 for r in v2big if r["solo_reruns"] > 0),
    "v2_incidents": len(v2big),
    "v1_s": [r["total_s"] for r in v1], "v1_agents": [r["agents"] for r in v1],
    "v1_roles_have_hvac": any("hvac" in r["roles"] for r in v1),
}

# ---- single-agent incidents and synthesizer calls through the app (v2, htpd v6/v7)
single, synth = [], []
for sub in ("refine_v7", "refine_stream", "refine_combined", "refine_d4", "recheck4"):
    for f in sorted(glob.glob(str(P / "2026-10-21_v2_app" / sub / "INC-*.json"))):
        j = json.load(open(f, encoding="utf-8"))
        stage = Path(f).stem.split("_")[-1]
        ag = [a for a in (j.get("agents") or []) if a.get("latency_ms")]
        if len(ag) == 1:
            a = ag[0]
            single.append(dict(src=sub, inc=j["id"], stage=stage, role=a["role"], ms=round(a["latency_ms"]), ttft_ms=round(a.get("ttft_ms") or 0),
                               tokens=a.get("gen_tokens"), tok_s=round(a.get("tokens_per_s") or 0, 1)))
        fin = j.get("final") or {}
        if fin.get("latency_ms"):
            synth.append(dict(src=sub, inc=j["id"], stage=stage, ms=round(fin["latency_ms"]), ttft_ms=round(fin.get("ttft_ms") or 0),
                              tokens=fin.get("gen_tokens"), tok_s=round(fin.get("tokens_per_s") or 0, 1)))
def summ(xs, key):
    v = [x[key] for x in xs]
    return dict(n=len(v), median=st.median(v), min=min(v), max=max(v)) if v else {}
early = [s for s in single if s["stage"] == "early"]
ref = [s for s in single if s["stage"] != "early"]
out["single_agent"] = {
    "early_ms": summ(early, "ms"), "early_ttft_ms": summ(early, "ttft_ms"), "early_tok_s": summ(early, "tok_s"), "early_tokens": summ(early, "tokens"),
    "refine_ms": summ(ref, "ms"), "refine_tok_s": summ(ref, "tok_s"),
    "slowest_early": sorted(early, key=lambda s: -s["ms"])[:5],
    "v1_mode3_median_s": 3.8,
}
out["synth_small_incidents"] = synth

# ---- htpd-direct A/B (v7): rep-2 artefact and the thermal drift of run_ab.sh
ab = {}
for f in sorted(glob.glob(str(P / "2026-10-21_htpd_v7_ab" / "ab_*.json"))):
    tag = Path(f).stem[3:]
    d = json.load(open(f))
    ab[tag] = {k: dict(total_s=round(v["total_ms"] / 1e3, 2), prefill_s=round((v["prefill_ms"] or 0) / 1e3, 2),
                       decode_s=round((v["total_ms"] - (v["prefill_ms"] or 0)) / 1e3, 2), max_tokens=max(v["tokens"]),
                       mean_tokens=round(sum(v["tokens"]) / len(v["tokens"]), 1), batches=v.get("batches"))
               for k, v in d.items()}
out["ab_v7"] = ab
log = open(P / "2026-10-21_htpd_v7_ab" / "run_ab.log", encoding="utf-8").read()
seq = re.findall(r"^(\w+) B13: n=13 total ([\d.]+)s", log, re.M)
out["run_ab_sequence_B13_s"] = seq
out["run_ab_cooling_reads"] = re.findall(r"^board (\d+)$", log, re.M)
b1 = ab.get("L7r1", {}).get("B1", {})
if b1:
    out["rep2_artefact"] = dict(ab_B1_decode_tok_s=round(b1["mean_tokens"] / b1["decode_s"], 1),
                                app_early_tok_s_median=out["single_agent"]["early_tok_s"].get("median"),
                                note="rep 2 replays the SAME prompts: htpd's recent-output drafts hold the exact answers")

# ---- verified-draft rows: k per stream = max(1, min(K, ROWS / streams - 1))
out["draft_k_by_streams"] = {f"K{K}_rows{R}": {n: max(1, min(K, R // n - 1)) for n in (1, 2, 3, 4, 6, 8, 10, 13, 14)}
                             for K, R in ((4, 32), (8, 32), (8, 64), (8, 48))}

json.dump(out, open(H / "evidence.json", "w"), indent=1)
cs = out["chaos_summary"]
print("v2 chaos 13-14 agents:", cs["v2_13_14_agents_s"], "median", cs["v2_median_s"], "| round 1:", cs["v2_round1_s"], "later:", cs["v2_later_rounds_s"])
print("v2 chaos with a solo re-run:", cs["v2_with_solo_rerun"], "of", cs["v2_incidents"])
print("v1 chaos:", cs["v1_s"], "agents", cs["v1_agents"], "hvac agents in v1:", cs["v1_roles_have_hvac"])
sa = out["single_agent"]
print("single agent early ms:", sa["early_ms"], "tok/s", sa["early_tok_s"], "| refinements ms:", sa["refine_ms"])
print("run_ab.sh B13 in run order:", seq, "cooling reads:", out["run_ab_cooling_reads"])
print("rep-2 artefact:", out.get("rep2_artefact"))
print("k per stream:", out["draft_k_by_streams"])
