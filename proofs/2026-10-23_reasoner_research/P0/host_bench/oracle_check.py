"""Scorer self-test: write results for an 'oracle' (gold answers) and a 'null' model (always 'unknown' / 'I don't know'),
score them, and check oracle ~ 1 and null low. Results go to results/_oracle and results/_null (not real models)."""
import json
import os
import re
import shutil

from common import HERE
import scenarios as SC
import questions as QS
from tools_impl import Executor
import score

RES = os.path.join(HERE, "results")


def sample_word(rx):
    for alt in re.split(r"\|", rx):
        w = re.sub(r"\\b|\(|\)|\?|\[.*?\]|\\s|\*|\+|\.|\^|\$", "", alt).strip()
        w = w.replace("\\", "")
        if w and re.search(rx, w, re.I):
            return w
    return ""


def oracle_report(s):
    g = s["gt"]
    lab = max(g["labels"], key=g["labels"].get)
    sev = max(g["severities"], key=g["severities"].get)
    kw = " ".join(sample_word(k) for k in g["keywords"])
    acts = [grp[0] for grp in g["required"]] or ["monitor"]
    rep = {"root_cause": "Cause found from the related sensors: %s" % kw, "label": lab, "causal_chain": "cause -> mechanism -> evidence",
           "affected_domains": g.get("domains_allowed") or ["water"] if g.get("domains_allowed") else [],
           "suspect_sensors": g["suspects"], "severity": sev, "evidence": s["ids"][:2], "confidence": 0.9,
           "checklist": [{"action": a, "target": "S1", "why": "needed for this case"} for a in acts],
           "monitor_next": "watch the next re-check", "needs_more_data": False,
           "explanation": "The related sensors explain the event in plain words for the operator here."}
    return rep


def main():
    for d in ("_oracle", "_null"):
        shutil.rmtree(os.path.join(RES, d), ignore_errors=True)
        os.makedirs(os.path.join(RES, d))
    ex = Executor()
    for s in SC.all_scenarios():
        calls = []
        if s["gt"]["needs_fetch"]:
            ex2 = Executor(scenario=s)
            calls = [{"name": "related_context", "args": {"ref": "S1"}, "result": ex2.run("related_context", {"ref": "S1"})}]
        rec = {"id": s["id"], "family": s["family"], "variant": 0, "wall_s": 1.0, "calls": calls,
               "final": {"content": json.dumps(oracle_report(s))}, "turns": [{"prompt_n": 500, "predicted_n": 200}], "user": s["prompt"]}
        open(os.path.join(RES, "_oracle", "reasoning.jsonl"), "a").write(json.dumps(rec) + "\n")
        if s["id"] in SC.CONSISTENCY_IDS:
            for tag in ("#rerun2", "#rerun3", "#para1", "#para2"):
                r2 = dict(rec, id=s["id"] + tag)
                open(os.path.join(RES, "_oracle", "consistency.jsonl"), "a").write(json.dumps(r2) + "\n")
        nul = dict(rec, calls=[], final={"content": json.dumps({"root_cause": "unknown", "label": "unknown", "severity": "warning",
                                                                  "evidence": [], "confidence": 0.5, "checklist": [{"action": "monitor", "why": "unknown"}]})})
        open(os.path.join(RES, "_null", "reasoning.jsonl"), "a").write(json.dumps(nul) + "\n")
    for part, items in (("chat", QS.build(ex)), ("reading", QS.reading_items(ex))):
        for it in items:
            a = it["answer"]
            bits = list(a.get("all", [])) + list(a.get("any", [])[:1])
            if a.get("numbers_any"):
                bits += [str(x) for x in a["numbers_any"][0]]
            for rx in a.get("regex_all", []) + a.get("regex_any", [])[:1]:
                bits.append(sample_word(rx))
            calls = [] if part == "reading" else [{"name": t, "args": ar, "result": r} for (t, ar), r in zip(it["gold"], it["gold_results"])]
            rec = {"id": it["id"], "cat": it["cat"], "q": it["q"], "wall_s": 1.0, "calls": calls,
                   "final": {"content": "Answer: " + ", ".join(bits) + "."}, "turns": [{"prompt_n": 100, "predicted_n": 40}]}
            open(os.path.join(RES, "_oracle", part + ".jsonl"), "a").write(json.dumps(rec) + "\n")
            nul = dict(rec, calls=[], final={"content": "I don't know."})
            open(os.path.join(RES, "_null", part + ".jsonl"), "a").write(json.dumps(nul) + "\n")
    s = score.main(["_oracle", "_null"], {"_oracle": 1.92, "_null": 1.92}, {"_oracle": {"deployable": "yes"}, "_null": {"deployable": "yes"}})
    for m in ("_oracle", "_null"):
        v = s[m]
        print(m, "R", round(v["reasoning"]["score"][0], 3), v["reasoning"]["components"], "T", round(v["tools"]["score"], 3),
              "U", round(v["understanding"]["score"], 3), "S", round(v["secondary"]["score"], 3), "total", round(v["weighted_total"], 3),
              "CI", [round(x, 3) for x in v["weighted_total_ci"]], "G1", v["G1"]["checks"])
    # list oracle items that do not score full marks (scorer bugs or unsatisfiable GT)
    import csv
    for row in csv.DictReader(open(os.path.join(RES, "per_item__oracle.csv"))):
        if row["part"] == "reasoning" and float(row["score"]) < 0.999:
            print("oracle reasoning <1:", row["id"], row["score"], row.get("keywords"), row.get("checklist"), row.get("evidence"))
        if row["part"] in ("chat", "reading") and row["answer_ok"] != "1":
            print("oracle answer fail:", row["id"], row["text"][:150])


if __name__ == "__main__":
    main()
