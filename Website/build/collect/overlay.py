"""Bring data/qa.json up to date after the 20 Oct collectors (run after qa.py and today.py).

    py -3 Website/build/collect/overlay.py

- Stale answers (written while v2 was training) are replaced. Closed numbers come from HANDBOOK 2.40-2.55 and the
  proof folders named in each answer; anything about tonight is read from data/today.json, never typed in.
- New questions about the reasoner, latency work and the final build are added.
Idempotent: always starts from the qa.py output kept in data/qa.base.json.
"""
from _lib import *  # noqa

S = __file__


def tonight():
    try:
        return read_json(DATA / "today.json")
    except Exception:  # noqa: BLE001
        return {}


def state(t):
    f = t.get("final") or {}
    d = t.get("decisions") or {}
    rag = t.get("rag") or {}
    retry = t.get("rsn_v2_retry") or {}
    live = bool(f.get("present") and f.get("passed"))
    prof = f.get("board_state") if live else d.get("known_good_profile")

    def p(k):
        for l in prof or []:
            if l.startswith(k + "="):
                return l.split("=", 1)[1].split("/")[-1]
        return None
    reasoner = p("reasoner_model") or "qwen35_reasoner_q4_0.gguf"
    rname = "rsn_v2" if "rsn_v2" in reasoner else "rsn_v1"
    if retry.get("live") and "rsn_v1" not in str(retry.get("result") or ""):   # the retry shipped htpd_v8x3 with rsn_v1 kept
        rname = "rsn_v2"
    split = (d.get("split_post_result") or p("reasoner_split") or d.get("split") or "3").split()[0]
    ch = (t.get("chaos_tonight") or {}).get("summary") or {}
    ml = (t.get("morning") or {}).get("live") or {}   # evaluation-morning deploy (improve*/STATUS.md) wins when present
    return dict(final=("pending" if not f.get("present") else "passed" if live else "rolled back"), live=live, rname=rname,
                split=ml.get("split") or split, rag=bool(rag.get("live")), ch=ch, bin=ml.get("bin") or p("bin") or "htpd_v8x2",
                result=f.get("result"), ea=ml.get("edge_agent"), apk=ml.get("apk"), fc=ml.get("fastcheck") or {})


def timing(s):
    ch = s["ch"]
    if ch.get("n") and ch.get("done_min"):
        pr, ti = ch.get("prelim_range") or ["?", "?"], ch.get("title_range") or ["?", "?"]
        return (f"through the app tonight ({ch['n']} scenarios): preliminary report {pr[0]}-{pr[1]} s after the event passes the gate, "
                f"the reasoner's title and severity {ti[0]}-{ti[1]} s, the full report {ch['done_min']}-{ch['done_max']} s")
    return ("through the app (fast4 build, 28 Oct): preliminary report 1-7 s after the event passes the gate, the reasoner's title and "
            "severity 9-17 s, the full report 28-39 s")


def main():
    base = Path(__file__).resolve().parent / "__pycache__" / "qa.base.json"   # qa.py's own output (not deployed, not committed)
    base.parent.mkdir(exist_ok=True)
    cur = read_json(DATA / "qa.json")
    if cur.get("meta", {}).get("overlay") is None:
        base.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    q = read_json(base)
    t = tonight()
    s = state(t)
    fast = ("Critical breaches skip the wait: 2 readings past a critical limit open the incident at once with a rules-only report, "
            "and the AI updates the same incident.") if s["live"] else ""
    upd = {
        "How quickly does an operator get an explanation?":
            f"In seconds once the AI starts: {timing(s)}. Before that, an event needs 8 abnormal readings, which is 40 to 55 min of real "
            f"sensor time at one reading per 5 min. {fast} Re-checks follow at +1.5 h and +3 h.",
        "Walk me through one incident.":
            "Crowded room (28 Oct, through the app): CO2 and power abnormal for 8 readings; 2 domain agents run in one NPU batch; the "
            "preliminary report shows after 7 s; the reasoner (Qwen3.5-4B) puts up its title and severity at 17 s and the full cross-domain "
            "report at 39.2 s; then the operator decides. Source: proofs/2026-10-27_reasoner_fast/RESULTS.md §6.",
        "What happens when several systems fail together?":
            "All flagged sensors get a domain agent in one NPU batch (10 agents about 11.0 s warm, B50), then the reasoner writes one "
            "report that names a single root cause across domains (22.5 s mean on 30 held-out incidents, split-3).",
        "What happens when the AC runs in an empty room?":
            "The v2 HVAC agent can recommend switch_off_ac, always as a recommendation the operator must approve. On the board (25 Oct) "
            "an AC-on room warming 1.4 °C/h above its band was raised as no_cooling_effect / critical by the HVAC rule (INC-0334).",
        "When is the AI called?":
            "After a warning, critical or fault status lasts 8 readings: about 16 s in the demo (one reading every 2 s), 40 to 55 min "
            f"of real sensor time (one reading per 5 min). 2,000 calm readings produced 0 incidents. {fast}",
        "How will v2 reduce false alarms?":
            "It did: trained on routines labelled normal, v2 cut false alarms on calm windows from 31% to 18% (deployed 21 Oct). "
            "mixA50, B50's parent, measured 18% against v2's 22% on a fresh seed (25 Oct).",
        "How fast is an incident now?":
            f"With the cross-domain reasoner: {timing(s)}. The agents alone: 10 in one batch about 11.0 s, 4 about 3.3-3.7 s (warm).",
        "Will v2 be slower?":
            "At first yes: 13-14-agent chaos incidents took 26-33 s (two batches, longer prompts). Profile work brought a 10-agent B50 "
            "batch to about 11.0 s warm. The bigger cost today is the reasoner's longer report, which is why a preliminary report "
            "comes first.",
        "How is v2 trained?":
            "QLoRA on Llama 3.2 3B, r=32, 2 epochs = 4,494 steps on the laptop GPU in resumable sessions; finished 20 Oct and deployed 21 Oct.",
        "Is it overfitting?":
            "No: dev loss fell 0.131 → 0.054 (best checkpoint, step 4,200) and train loss per token tracked it; the best checkpoint was kept.",
        "What if the synthesizer's answer fails policy?":
            "The reasoner replaced the synthesizer. If its report fails the gate, the deterministic report (rules plus validated agent "
            "findings) is used and marked; over-long lists are trimmed with a note instead of rejecting the whole report.",
        "What are the honest limits?":
            "Sensor time dominates (40 to 55 min to the AI for non-critical events); heat at chaos peaks (90-94 °C); the NPU is not "
            "bit-repeatable (severity agrees 97% across repeats, 100% with the guard); recurring small spikes; one campus's data; power "
            "not measured in joules. The Today page keeps this list current.",
        "What is still unsolved?":
            "Recurring sub-threshold spikes and pump cycling are still often misnamed, and non-critical events still wait 8 readings "
            "for the AI. The gate study (agents on 3-7 readings) is the next step for the latter.",
        "What is next?":
            "After the evaluation: (1) the conversational interface (endpoint, chat tools over the incident store, chat panel, board "
            "test); (2) reasoner speed by forcing fully determined text in the htpd forcer; (3) young-window training to shorten the "
            "8-reading gate; (4) the GPU for bursts (a second incident's agents while the NPU reasoner writes), after a memory-safety "
            "check; (5) rsn_v3, fixing rsn_v2's severity regressions first.",
        "Why the NPU and not the GPU?":
            "Measured twice. Agents: ~8.4 s per agent on the Adreno GPU, no batching gain. Reasoner (29 Oct, upstream llama.cpp "
            "OpenCL, GPU alone): 7.35 / 8.44 / 8.35 tokens/s (pp1 / pp3 / tg), about 2.5x slower than the NPU split. "
            "Source: proofs/2026-10-28_master/gpu_bench_out/out.md.",
        "What happens after training finishes?":
            "Done: v2 was merged, exported to GGUF Q4_0 for htpd and deployed on 21 Oct; the agents later moved to mixA50 (25 Oct) "
            "and B50 (28 Oct), each only after a paired test on the board or its host copy.",
        "How will you know v2 is better than v1?":
            "Measured on the QIDK, test months, paired against v1: at 40 min 73.8% vs 42% (pass); false alarms 18% vs 31% (pass); at 3 h "
            "82.5% vs 88% (miss, p ≈ 0.09).",
        "What if v2 fails the acceptance test?":
            "It missed the 3 h bar. The owner shipped it for the early-alert and false-alarm gains, and choosing the re-check window by "
            "the event's shape lifted 3 h to 86.3% on a fresh seed (182 events). v1 stayed available as the revert.",
        "What runs on the QIDK today?":
            f"Domain agents B50 (Llama 3.2 3B, Q4_0) and the {s['rname']} reasoner (Qwen3.5-4B, Q4_0) on one NPU through {s['bin']}, "
            f"split decoding with {s['split']} groups, a preliminary report"
            + (" with retrieval of similar past incidents" if s["rag"] else " from rules and agents")
            + (", 254 seed reference reports, a checklist that starts from the preliminary report and merges with the AI report"
               if s.get("ea") else "")
            + ", policy gate, native app, all offline on the board."
            + (f" Live build: edge-agent {s['ea']} (APK {s['apk']}), deployed the morning of 29 Oct and checked through the app "
               f"(fast path {s['fc'].get('fast_s')} s, AI report on the same incident {s['fc'].get('ai_update_s')} s)."
               if s.get("ea") else f" Final deploy: {s['final']}.") + " Details on the Today page.",
        "Where is training right now?":
            "Finished. v2 completed 4,494 steps (best dev loss 0.054) and shipped 21 Oct; the reasoner (Qwen3.5-4B, QLoRA r32, about 21 h) "
            "was trained next. No training runs on the board.",
    }
    n_upd = 0
    for it in q["qa"]:
        if it["q"] in upd:
            it["short_answer"] = upd[it["q"]]
            it["updated"] = "2026-10-29"
            n_upd += 1
    new = [
        ("reasoner", "What is the cross-domain reasoner?",
         "Qwen3.5-4B fine-tuned with QLoRA (rank 32). It reads every domain agent's finding and writes the title, severity, root "
         "cause, evidence, checklist and explanation. It shares the NPU with the agents' model; htpd swaps between them."),
        ("reasoner", "How accurate is the reasoner?",
         "rsn_v1 on 150 held-out incidents (laptop): severity 91.9%, root-cause label 87.8%, valid output 98.7%. On the board, the "
         "same prompt 5 times gives the same severity 97% of the time, 100% with the light guard."),
        ("reasoner", "Why does a full report take about 30 s when an incident used to take 4 s?",
         "The reasoner writes a full report of several hundred tokens and decoding is bound by memory bandwidth (about 60 ms per "
         "token). So the operator gets a preliminary report within seconds and the reasoner's title and severity before the rest."),
        ("reasoner", "Why is the NPU answer not always the same?",
         "Prefill sums in fp16 in a different order run to run, so logits differ bit for bit; that only flips a word at near-ties "
         "(margins 0.003-0.16). Severity still agrees 97% across repeats, and the guard never lets the report say normal when the "
         "rules say warning or worse."),
        ("latency", "Why not speculative decoding?",
         "Measured on the board: MTP and n-gram drafts were 1% to 20% slower, because verifying 2-4 tokens costs 82-133 ms against "
         "66 ms for one, and rollback snapshots doubled prefill."),
        ("latency", "Why not run the reasoner on the GPU?",
         "Measured on 29 Oct: Adreno 750, upstream llama.cpp OpenCL, GPU alone: 7.35 / 8.44 / 8.35 tokens/s (pp1 / pp3 / tg), about "
         "2.5x slower than the NPU split. It is not a latency path; it may help bursts later (a second incident's agents on the GPU "
         "while the NPU reasoner writes) after a memory-safety check."),
        ("reasoner", "Why did you reject rsn_v2?",
         "On the same 106 held-out incidents (host copy of the board model): severity 94.7% for rsn_v1 vs 87.6% for rsn_v2, label 88.4% "
         "vs 85.6%, checklist recall 0.90 vs 0.81. On the board rsn_v2 also invented a title location and misread 324 > 300 ppm. "
         "Severity is what operators act on, so rsn_v1 stays."),
        ("reasoner", "What are the contract repairs?",
         "Rule-based checks after the reasoner: severity normal with needs_more_data gets the label unknown (gold rule 151/151), and a "
         "title location not in the input is replaced by one from the input (5,761/5,761). Replayed on 386 board answers: label "
         "83.2% -> 87.6%, 0 new errors. Deployed 29 Oct."),
        ("latency", "What does the operator see in the first seconds?",
         "A preliminary report in the same second the incident opens: a rules report from the live values in the wording of the most "
         "similar past report (hybrid retrieval: structured vector 0.7 + TF-IDF 0.3; 254 seed reports plus every live AI report). "
         "Severity is the higher of rules and retrieval, so it never under-alerts. Its checklist is live, and the AI report merges in "
         "about 40 s later."),
        ("latency", "Is the 40-55 min wait solved?",
         "No. Non-critical events still need 8 readings (40-55 min of real sensor time at one reading per 5 min) before the AI runs. "
         "Critical breaches take the fast path (2 readings past the limit). Young-window training to shorten the gate is the next step."),
        ("status", "Is there a chat interface?",
         "Not yet in the app. rsn_v1 was trained with about 2,000 chat tool traces and scores 100% answered, 100% first tool right, "
         "90% numbers exact, 0% ungrounded on 100 dev questions (laptop). Missing: an /api/chat endpoint, the chat tools over the "
         "incident store, a chat panel and NPU scheduling. It is the first item after the evaluation."),
        ("latency", "Did split 3r or more split groups help?",
         "No. Split 4: +1%; split 6 does not fit the NPU session; split 3r (fork after the label) 22.2 vs 22.2 s on 10 incidents. "
         "Split 3 stays."),
        ("latency", "What is the critical fast path?",
         "2 readings in a row past a sensor's critical limit open the incident at once with a rules-only report; the agents and "
         "reasoner still run at 8 readings and update the same incident. Power, tank level and flow have no fixed limits, so no fast path."
         + (" It is in the running build." if s["live"] else " It is in the final build; see Today for whether it is live.")),
        ("model", "What is B50?",
         "The agents' model: mixA50 with half of a further LoRA top-up blended in. Against mixA50 on paired rows: overall +1, "
         "severity-weighted +61, story suite +4 (wins minus losses). The next candidate, T30, lost to it head to head."),
        ("status", "What happened in the final deploy?",
         ("Pending: the final deploy has not written its status yet (see Today)." if s["final"] == "pending" else
          f"{s['final'].capitalize()}: " + str(s["result"] or "").split(": {")[0])),
    ]
    have = {it["q"] for it in q["qa"]}
    for cat, qq, a in new:
        if qq not in have:
            q["qa"].append({"category": cat, "q": qq, "short_answer": a, "evidence_ids": [], "updated": "2026-10-29"})
    cats = q["meta"].get("categories") or []
    for c in ("reasoner",):
        if c not in cats:
            cats.append(c)
    q["meta"].update(categories=sorted(cats), n=len(q["qa"]), overlay=rel(S), overlay_at=NOW,
                     overlay_note=f"{n_upd} answers updated, {len(new)} questions added after 20 Oct")
    bad = check_no_raw(q)
    assert not bad, bad[:5]
    (DATA / "qa.json").write_text(json.dumps(q, indent=1, ensure_ascii=False), encoding="utf-8")
    return n_upd


if __name__ == "__main__":
    print("updated", main())
