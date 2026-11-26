"""pilot_score.py <run tag>: discordance between the arms and per-arm label / severity accuracy vs the injection gold -> PILOT.md (+ pilot_scores.json).
Arms: full = reasoner report (fallback template if the reasoner output fails the label/severity gate), cheap = Go isolatedReport port (domain agents + template),
cheap_x = Go fallbackReport port (cross-domain template; what a multi-domain 'cheap' path would more naturally be). Gold only for injected cases."""
import collections, json, sys, statistics as S, datetime as dt
import pdata as D

tag = sys.argv[1] if len(sys.argv) > 1 else "pilot"
RUN = "%s/runs/%s" % (D.PAPER, tag)
recs = [json.loads(l) for l in open(RUN + "/records.jsonl")]
recs = [r for r in recs if r["full"] is not None]


def sev_of(rep):
    return (rep or {}).get("severity")


def lab_of(rep):
    return (rep or {}).get("label")


def f1(pred, gold):
    p, g = set(pred or []), set(gold or [])
    if not p and not g:
        return 1.0
    tp = len(p & g)
    return 0.0 if tp == 0 else 2 * tp / (len(p) + len(g))


def rate(xs):
    return round(100 * sum(xs) / len(xs), 1) if xs else None


ARMS = {"full": "full", "cheap": "cheap", "cheap_x": "cheap_x"}
out = {"n": len(recs), "arms": {}, "by_stratum": {}}
for arm, k in ARMS.items():
    out["arms"][arm] = dict(label_acc=rate([lab_of(r[k]) == r["gold"]["label"] for r in recs]), severity_acc=rate([sev_of(r[k]) == r["gold"]["severity"] for r in recs]),
                            both_acc=rate([lab_of(r[k]) == r["gold"]["label"] and sev_of(r[k]) == r["gold"]["severity"] for r in recs]),
                            domain_f1=round(100 * S.mean(f1(r[k]["affected_domains"], r["gold"]["affected_domains"]) for r in recs), 1),
                            missed_critical=sum(1 for r in recs if r["gold"]["severity"] == "critical" and sev_of(r[k]) != "critical"),
                            n_critical=sum(1 for r in recs if r["gold"]["severity"] == "critical"))
disc = lambda r, a, b: lab_of(r[a]) != lab_of(r[b]) or sev_of(r[a]) != sev_of(r[b])
out["discordance_cheap_vs_full_pct"] = rate([disc(r, "cheap", "full") for r in recs])
out["discordance_cheap_x_vs_full_pct"] = rate([disc(r, "cheap_x", "full") for r in recs])
out["discordance_label_only_cheap_vs_full_pct"] = rate([lab_of(r["cheap"]) != lab_of(r["full"]) for r in recs])
out["discordance_severity_only_cheap_vs_full_pct"] = rate([sev_of(r["cheap"]) != sev_of(r["full"]) for r in recs])
out["oracle_headroom_pct"] = rate([(lab_of(r["full"]) == r["gold"]["label"] and sev_of(r["full"]) == r["gold"]["severity"]) and not (lab_of(r["cheap"]) == r["gold"]["label"] and sev_of(r["cheap"]) == r["gold"]["severity"]) for r in recs])
out["reverse_headroom_pct"] = rate([(lab_of(r["cheap"]) == r["gold"]["label"] and sev_of(r["cheap"]) == r["gold"]["severity"]) and not (lab_of(r["full"]) == r["gold"]["label"] and sev_of(r["full"]) == r["gold"]["severity"]) for r in recs])
for st in sorted({r["stratum"] for r in recs}):
    rr = [r for r in recs if r["stratum"] == st]
    out["by_stratum"][st] = dict(n=len(rr), discordance_pct=rate([disc(r, "cheap", "full") for r in rr]),
                                 full_label=rate([lab_of(r["full"]) == r["gold"]["label"] for r in rr]), cheap_label=rate([lab_of(r["cheap"]) == r["gold"]["label"] for r in rr]),
                                 full_sev=rate([sev_of(r["full"]) == r["gold"]["severity"] for r in rr]), cheap_sev=rate([sev_of(r["cheap"]) == r["gold"]["severity"] for r in rr]))
rs = [r["reasoner"] for r in recs]
ag_wall = [r["agents_wall_s_total"] for r in recs]
ph = recs[0]["agent_phase"]
out["runtime"] = dict(reasoner_wall_s_mean=round(S.mean(x["wall_s"] for x in rs), 1), reasoner_wall_s_median=round(S.median(x["wall_s"] for x in rs), 1),
                      reasoner_wall_s_max=round(max(x["wall_s"] for x in rs), 1), prefill_tokens_mean=round(S.mean(x["prefill_tokens"] for x in rs)),
                      decode_tokens_mean=round(S.mean(x["decode_tokens"] for x in rs)), agent_calls_per_case=round(S.mean(r["triggers"]["n_agents"] for r in recs), 2),
                      agent_phase_wall_s=ph.get("phase_wall_s"), agent_phase_per_case_s=round((ph.get("phase_wall_s") or 0) / max(1, len(recs)), 1), agent_np=ph.get("np"),
                      per_case_total_s=round((ph.get("phase_wall_s") or 0) / max(1, len(recs)) + S.mean(x["wall_s"] for x in rs), 1))
out["health"] = dict(reasoner_valid_pct=rate([x["valid"] for x in rs]), fallback_fired=sum(x["fallback_fired"] for x in rs), think_on_pct=rate([x["think_on"] for x in rs]),
                     tool_calls=sum(len(x["tool_calls"]) for x in rs), agents_invalid=sum(r["triggers"]["agent_invalid"] for r in recs),
                     rule_agent_disagree_pct=rate([r["triggers"]["rule_agent_disagree"] for r in recs]), any_critical_pct=rate([r["triggers"]["any_critical"] for r in recs]),
                     app_would_escalate_pct=rate([r["triggers"]["app_would_escalate"] for r in recs]), site_linked_pct=rate([r["triggers"]["site_linked"] for r in recs]),
                     agent_low_conf_pct=rate([r["triggers"]["agent_low_conf"] for r in recs]))
# confusion lists for the two arms
conf = collections.Counter((r["gold"]["label"], lab_of(r["full"]), lab_of(r["cheap"])) for r in recs)
json.dump(out, open("%s/pilot_scores.json" % D.PAPER if tag == "pilot" else RUN + "/scores.json", "w", newline="\n"), indent=1)
a = out["arms"]
md = ["# PILOT: %d Set B cases (stratified N=2 / 3-4 / 5+), injected faults in real held-out campus windows" % len(recs), "",
      "Generated %s by pilot_score.py from `runs/%s/records.jsonl` (one run per case: agents + reasoner on the host; cheap arm computed offline from the same agent outputs)." % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), tag), "",
      "## Headline", "",
      "- **Discordance (cheap = isolatedReport vs full = reasoner; label OR severity differs): %s %%** (label only %s %%, severity only %s %%). vs the fallbackReport template: %s %%." % (
          out["discordance_cheap_vs_full_pct"], out["discordance_label_only_cheap_vs_full_pct"], out["discordance_severity_only_cheap_vs_full_pct"], out["discordance_cheap_x_vs_full_pct"]),
      "- Accuracy vs the injection gold (n = %d):" % len(recs), "", "| arm | label acc % | severity acc % | both % | affected-domain F1 % | missed critical |", "|---|---|---|---|---|---|"]
for arm in ("cheap", "cheap_x", "full"):
    x = a[arm]
    md.append("| %s | %s | %s | %s | %s | %d / %d |" % (arm, x["label_acc"], x["severity_acc"], x["both_acc"], x["domain_f1"], x["missed_critical"], x["n_critical"]))
md += ["", "- Oracle headroom (full right and cheap wrong on label+severity): %s %% of cases; reverse (cheap right, full wrong): %s %%." % (out["oracle_headroom_pct"], out["reverse_headroom_pct"]), "",
       "## By stratum", "", "| N domains | n | discordance % | full label | cheap label | full sev | cheap sev |", "|---|---|---|---|---|---|---|"]
for st, x in out["by_stratum"].items():
    md.append("| %s | %d | %s | %s | %s | %s | %s |" % (st, x["n"], x["discordance_pct"], x["full_label"], x["cheap_label"], x["full_sev"], x["cheap_sev"]))
rt = out["runtime"]; h = out["health"]
md += ["", "## Runtime (host, laptop GPU, Q4_0; ONE model at a time)", "",
       "- Reasoner phase wall per case: mean %s s, median %s s, max %s s (prefill %s tokens, decode %s tokens, think adaptive)." % (rt["reasoner_wall_s_mean"], rt["reasoner_wall_s_median"], rt["reasoner_wall_s_max"], rt["prefill_tokens_mean"], rt["decode_tokens_mean"]),
       "- Agent phase: %s agent calls per case, %s s wall in total for the whole batch (np=%s parallel slots) = %s s per case amortised." % (rt["agent_calls_per_case"], rt["agent_phase_wall_s"], rt["agent_np"], rt["agent_phase_per_case_s"]),
       "- Total about %s s per case (agents amortised + reasoner). Board latency is a separate measurement (RQ1 cost needs the board)." % rt["per_case_total_s"], "",
       "## Health and trigger inputs on the 30", "",
       "- Reasoner output valid (JSON, label and severity enums): %s %%; fallback template fired %d times; think on in %s %% of cases; %d tool calls (empty frozen corpus)." % (h["reasoner_valid_pct"], h["fallback_fired"], h["think_on_pct"], h["tool_calls"]),
       "- Domain agent outputs rejected by the enum gate: %d." % h["agents_invalid"],
       "- Trigger inputs: rules-vs-agent disagreement in %s %% of cases; any critical %s %%; agent confidence < 0.6 in %s %%; flagged sensors site-linked %s %%; the app's own rule (>= 2 domains) would escalate %s %%." % (
           h["rule_agent_disagree_pct"], h["any_critical_pct"], h["agent_low_conf_pct"], h["site_linked_pct"], h["app_would_escalate_pct"]), "",
       "## Label confusion (gold -> full / cheap), counts", ""]
for (g, f_, c_), n in conf.most_common():
    md.append("- %s -> full %s / cheap %s: %d" % (g, f_, c_, n))
md += ["", "## Caveats (read before using any number)", "",
       "- Gold comes from the injection (injected cases only; real windows are baselines). n = %d, so 95%% intervals are about +-18 points; this pilot only sizes the effect." % len(recs),
       "- The cheap arm is a port of Go `isolatedReport` (unit-tested byte-exact against the Go report in proofs/2026-10-16_hw_grid/workload_INC-0407.json, the only Go-produced isolated report stored). It was designed for ONE domain: at N >= 2 it reports the lead sensor only (affected_domains = [lead role]), so low domain F1 at N >= 2 is by construction. `cheap_x` (fallbackReport port) is the natural cross-domain template; both are shown.",
       "- Cheap-arm severity is not a field of Go's isolatedReport; it is derived as the lead finding's status (the app derives severity elsewhere).",
       "- Rule view (rule-vs-agent disagreement, context agents) is the Python mirror of the Mode 1 rules (training/generate_dataset.py + features.py), not rules.go with per-node card thresholds; disagreement rates are therefore approximate.",
       "- Reasoner tools answer from an empty frozen corpus (retrieval off, see LEAKAGE.md). Host Q4_0 timings are not board timings."]
open(D.PAPER + "/PILOT.md" if tag == "pilot" else RUN + "/SCORES.md", "w", newline="\n").write("\n".join(md) + "\n")
print(json.dumps(out, indent=1)[:3000])
