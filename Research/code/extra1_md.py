import json
P = "/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-26_paper" if __import__("os").name != "nt" else "C:/Users/hp/Desktop/qidk/proofs/2026-11-26_paper"
o = json.load(open(P + "/results/extra1.json"))
N = {"cheap": "cheap", "cheap_x": "cheap_x", "full": "full", "m2": "Mode 2-fair"}
L = ["", "## Extra metrics from existing records (item 1; extra1.py, results/extra1.json)", "",
     "Universe: gold-labelled B + D + F-injected (n=248; Mode 2-fair only on B+D, n=218). Bootstrap 1000 resamples.", "",
     "### Severity macro-F1 (classes normal / warning / critical / sensor_fault)", "", "| arm | n | macro-F1 [95% CI] | F1 normal | F1 warning | F1 critical | F1 sensor_fault |", "|---|---|---|---|---|---|---|"]
for a, v in o["severity"].items():
    pc = v["per_class"]; L.append("| %s | %d | %.3f [%.3f, %.3f] | %.3f | %.3f | %.3f | %.3f |" % (N[a], v["n"], v["macro_f1"], v["ci"][0], v["ci"][1], pc["normal"], pc["warning"], pc["critical"], pc["sensor_fault"]))
L += ["", "Confusion matrices (rows = gold, columns = predicted; order normal, warning, critical, sensor_fault):", ""]
for a, v in o["severity"].items():
    L.append("- %s: %s" % (N[a], "; ".join("[" + ",".join(map(str, row)) + "]" for row in v["cm"])))
L += ["", "### Affected-domain set F1 (B + F-injected, D excluded; gold = injected domain set incl. context domains)", "", "| arm | n | mean per-case F1 | micro F1 | micro P | micro R |", "|---|---|---|---|---|---|"]
for a, v in o["domains"].items():
    L.append("| %s | %d | %.3f | %.3f | %.3f | %.3f |" % (N[a], v["n"], v["mean_case_f1"], v["micro_f1"], v["micro_p"], v["micro_r"]))
L += ["", "### Grounding (all non-A cases that have a prompt; validity checked against the FULL reasoner prompt, the Mode 2-fair prompt text was not logged)", "",
      "| arm | cases | evidence ids | id validity | flagged-sensor coverage | numbers in text | ungrounded-number rate |", "|---|---|---|---|---|---|---|"]
for a, v in o["grounding"].items():
    L.append("| %s | %d | %d | %.2f %% | %.1f %% | %d | %.2f %% |" % (N[a], v["cases"], v["evidence_ids"], 100 * v["id_validity"], 100 * v["flagged_sensor_coverage"], v["numbers"], 100 * v["ungrounded_number_rate"]))
L += ["", "id validity = cited evidence id (Sx.Ey) occurs in the prompt. Coverage = share of [FLAGGED] sensors with at least one cited evidence id. Ungrounded number = a number in title/root_cause/causal_chain/explanation/observation text that appears nowhere in the prompt (heuristic string match; derived values such as a sum or a rounding count as ungrounded, so it is an upper bound). cheap/cheap_x numbers come from templates.", "",
      "### Latency, paired Wilcoxon signed-rank (B+D, n=218; per-case host seconds, cheap = agents only, full = agents + reasoner, Mode 2-fair = reasoner only)", "", "| pair | median A s | median B s | median diff s | W | p |", "|---|---|---|---|---|---|"]
for k, v in o["latency"].items():
    a, b = k.split("_vs_"); L.append("| %s vs %s | %.2f | %.2f | %.2f | %.0f | %.2g |" % (N[a], N[b], v["median_a"], v["median_b"], v["median_diff"], v["W"], v["p"]))
r = o["retrieval"]
L += ["", "### Retrieval-hit rate", "", "Logged per case (`retrieval_hits`) but the paper runs used an EMPTY frozen corpus (see LEAKAGE.md): hits > 0 in %d of %d cases; the reasoner made a tool call in %d cases. Retrieval therefore had no chance to help or hurt in the main arms; the retrieval ablation (item 4) is correspondingly a no-op unless a populated corpus is used." % (r["hits_nonzero"], r["n"], r["tool_calls_cases"]), ""]
open(P + "/RESULTS.md", "a", newline="\n").write("\n".join(L))
