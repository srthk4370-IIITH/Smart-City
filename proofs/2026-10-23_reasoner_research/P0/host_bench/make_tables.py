"""Tables (markdown) and a bar chart (SVG, no dependencies) from results/summary.json -> results/tables.md, results/scores.svg"""
import json
import os

from common import HERE

RES = os.path.join(HERE, "results")


def f(x, d=2):
    return "-" if x is None else ("%.*f" % (d, x))


def ci(t):
    return "%s [%s, %s]" % (f(t[0]), f(t[1]), f(t[2])) if t and t[0] is not None else "-"


def main():
    S = json.load(open(os.path.join(RES, "summary.json")))
    pairs = S.pop("_paired_differences", {})
    ms = list(S)
    L = []
    L.append("### Gates\n")
    L.append("| model | G1 groundedness & safety | ungrounded-number answers | invented ids | actuation | injection followed (of 3) | 'not available' correct | refusals correct | G2 deployability | est. NPU report p50 / p90 (s) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for m in ms:
        g1, g2 = S[m]["G1"], S[m]["G2"]
        L.append("| %s | **%s** | %s%% | %s%% | %d | %d | %s%% | %s%% | **%s** | %s / %s |" % (
            m, "PASS" if g1["pass"] else "FAIL", f(100 * g1["ungrounded_number_response_rate"], 1), f(100 * g1["invented_id_rate"], 1),
            g1["actuation"], g1["injection_followed"], f(100 * g1["insufficient_data_correct"], 0), f(100 * g1["refusal_correct"], 0),
            g2["verdict"], f(g2["npu_est_report_p50_s"], 1), f(g2["npu_est_report_p90_s"], 1)))
    L.append("\n### Weighted score (45 reasoning / 25 tools / 20 data / 10 secondary), 95% bootstrap CI\n")
    L.append("| model | 1. cross-domain reasoning (45%) | 2. tools (25%) | 3. understanding data (20%) | 4. secondary (10%) | **weighted total** |")
    L.append("|---|---|---|---|---|---|")
    for m in sorted(ms, key=lambda m: -(S[m]["weighted_total"] or 0)):
        v = S[m]
        L.append("| %s | %s | %s | %s | %s | **%s** |" % (m, ci(v["reasoning"]["score"]), ci(v["tools"]["ci"]), ci(v["understanding"]["ci"]),
                                                      ci(v["secondary"]["ci"]), ci(v["weighted_total_ci"])))
    L.append("\n### 1. Cross-domain reasoning: components and families\n")
    comps = ["label", "keywords", "suspects", "severity", "checklist", "evidence"]
    L.append("| model | report parsed | label acc. | " + " | ".join(comps) + " | checklist recall | forbidden-action reports |")
    L.append("|---|" + "---|" * (len(comps) + 5))
    for m in ms:
        r = S[m]["reasoning"]
        L.append("| %s | %s | %s | %s | %s | %s |" % (m, f(r["parsed_rate"]), f(r["label_accuracy"]), " | ".join(f(r["components"][c]) for c in comps),
                                                 f(r["checklist_recall"]), f(r["forbidden_action_rate"])))
    fams = sorted({k for m in ms for k in S[m]["reasoning"]["by_family"]})
    L.append("\n| family | " + " | ".join(ms) + " |")
    L.append("|---|" + "---|" * len(ms))
    for fa in fams:
        L.append("| %s | %s |" % (fa, " | ".join(f(S[m]["reasoning"]["by_family"].get(fa)) for m in ms)))
    L.append("\n### 2. Tools\n")
    L.append("| model | first-call selection | argument exec-match | fetched when needed (9 cases) | no call when not needed (118) | tool-error rate | mean calls / report |")
    L.append("|---|---|---|---|---|---|---|")
    for m in ms:
        t = S[m]["tools"]
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (m, f(t["selection"]), f(t["args_exec_match"]), f(t["fetch_when_needed"]),
                                                       f(t["no_call_when_not_needed"]), f(t["tool_error_rate"]), f(S[m]["latency"]["tool_calls_mean_reasoning"], 1)))
    cats = sorted({k for m in ms for k in S[m]["tools"]["by_cat_args"]})
    L.append("\n| argument exec-match by category | " + " | ".join(ms) + " |")
    L.append("|---|" + "---|" * len(ms))
    for c in cats:
        L.append("| %s | %s |" % (c, " | ".join(f(S[m]["tools"]["by_cat_args"].get(c)) for m in ms)))
    L.append("\n### 3. Understanding the data\n")
    L.append("| model | chat final answer exact | data-reading exact (15) | ungrounded-number answers |")
    L.append("|---|---|---|---|")
    for m in ms:
        u = S[m]["understanding"]
        L.append("| %s | %s | %s | %s |" % (m, f(u["chat_answer_exact"]), f(u["reading_exact"]), f(u["ungrounded_number_rate_chat"])))
    cats = sorted({k for m in ms for k in S[m]["understanding"]["by_cat_answer"]})
    L.append("\n| answer exact by category | " + " | ".join(ms) + " |")
    L.append("|---|" + "---|" * len(ms))
    for c in cats:
        L.append("| %s | %s |" % (c, " | ".join(f(S[m]["understanding"]["by_cat_answer"].get(c)) for m in ms)))
    L.append("\n### 4. Secondary\n")
    L.append("| model | 1 - Brier | ECE | mean confidence | consistent (3 reruns + 2 paraphrases) | reruns only | paraphrases only | communication rubric |")
    L.append("|---|---|---|---|---|---|---|---|")
    for m in ms:
        s = S[m]["secondary"]
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (m, f(s["calibration_1_minus_brier"]), f(s["ece"]), f(s["mean_confidence"]),
                                                            f(s["consistency_all5"]), f(s["consistency_reruns"]), f(s["consistency_paraphrase"]), f(s["communication"])))
    L.append("\n### Latency and tokens (host RTX 4050, llama.cpp b11815 CUDA; NPU = estimate)\n")
    L.append("| model | Q4 file GB | host report p50 (s) | prefill tokens / report (after prefix cache) | decode tokens / report | est. NPU report p50 (s) | chat host p50 (s) | chat decode tokens |")
    L.append("|---|---|---|---|---|---|---|---|")
    for m in ms:
        la, g2 = S[m]["latency"], S[m]["G2"]
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (m, f(g2["q4_0_gb"]), f(la["host_report_p50_s"], 1), f(la["prefill_tokens_mean"], 0),
                                                             f(la["decode_tokens_mean"], 0), f(g2["npu_est_report_p50_s"], 1), f(la["chat_host_p50_s"], 1), f(la["chat_decode_tokens_mean"], 0)))
    if pairs:
        L.append("\n### Paired differences (same items resampled; 1000 bootstraps)\n")
        L.append("| A - B | reasoning diff [95% CI] | P(diff <= 0) | weighted total diff [95% CI] | P(diff <= 0) |")
        L.append("|---|---|---|---|---|")
        for k, v in pairs.items():
            r, w = v["reasoning"], v["weighted_total"]
            L.append("| %s | %s [%s, %s] | %s | %s [%s, %s] | %s |" % (k, f(r["diff"], 3), f(r["ci95"][0], 3), f(r["ci95"][1], 3), f(r["p_le_0"], 3),
                                                                  f(w["diff"], 3), f(w["ci95"][0], 3), f(w["ci95"][1], 3), f(w["p_le_0"], 3)))
    open(os.path.join(RES, "tables.md"), "w").write("\n".join(L) + "\n")
    # SVG: grouped bars per category
    cats = [("reasoning", lambda v: v["reasoning"]["score"][0]), ("tools", lambda v: v["tools"]["score"]),
            ("data", lambda v: v["understanding"]["score"]), ("secondary", lambda v: v["secondary"]["score"]), ("TOTAL", lambda v: v["weighted_total"])]
    cols = ["#4C78A8", "#F58518", "#54A24B", "#B279A2", "#9D755D", "#E45756"]
    Wd, H, pad = 760, 320, 40
    gw = (Wd - 2 * pad) / len(cats)
    bw = gw / (len(ms) + 1)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" font-family="sans-serif" font-size="11">' % (Wd, H + 60),
           '<rect width="100%" height="100%" fill="white"/>']
    for k in range(0, 11, 2):
        y = pad + H - 40 - (H - 40 - pad) * k / 10
        svg.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#ddd"/><text x="5" y="%.1f">%.1f</text>' % (pad, Wd - pad, y, y, y + 4, k / 10))
    for ci_, (cn, fn) in enumerate(cats):
        for mi, m in enumerate(ms):
            v = fn(S[m]) or 0
            x = pad + ci_ * gw + (mi + 0.5) * bw
            h = (H - 40 - pad) * v
            svg.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"><title>%s %s %.3f</title></rect>' % (x, pad + H - 40 - h, bw * 0.9, h, cols[mi % 6], m, cn, v))
        svg.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>' % (pad + ci_ * gw + gw / 2, H - 20, cn))
    for mi, m in enumerate(ms):
        svg.append('<rect x="%d" y="%d" width="10" height="10" fill="%s"/><text x="%d" y="%d">%s</text>' % (pad + mi * 150, H + 10, cols[mi % 6], pad + mi * 150 + 14, H + 19, m))
    svg.append("</svg>")
    open(os.path.join(RES, "scores.svg"), "w").write("\n".join(svg))
    print("\n".join(L))


if __name__ == "__main__":
    main()
