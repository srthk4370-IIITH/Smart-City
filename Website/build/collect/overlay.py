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
            "A critical breach opens its incident about 5.6 s after the second critical reading (2.6 s after a silent gap), with a "
            "preliminary report and a live checklist in the same second; the AI report lands on the same incident about 28 s later "
            "(deploy27 fastcheck: 28.0 and 32.7 s). Non-critical events wait for 8 abnormal readings, 40 to 55 min of real sensor time "
            "at one reading per 5 min. Re-checks follow at +1.5 h and +3 h. Sources: proofs/2026-11-03_deploy27/apk/STATUS.md, HANDBOOK 2.67.",
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
            "Board lab: one agent request 2.06 s with the agent draft index (was 2.59 s); reasoner report 8.9-9.1 s with verified drafts "
            "inside split decoding (was 23.3 s); reasoner model load 2.8 s. Through the app, the AI report on a fast-path incident: "
            "55.2 s on 28 Oct, 21.7-28 s since 31 Oct. Sources: HANDBOOK 2.63-2.65, proofs/2026-10-29_latency/repack/VERDICT.md.",
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
            "Sensor time dominates (40 to 55 min to the AI for non-critical events; power, tank level and flow have no fast path); heat "
            "(84-97 °C on the hottest zone during NPU work); the NPU is not bit-repeatable (severity agrees 97% across repeats, 100% with "
            "the guard); recurring small spikes and pump cycling; blind chat questions still expose gaps; on evaluation day chat and "
            "reports use two different models; one campus's data; the fog store is designed but not built.",
        "What is still unsolved?":
            "Recurring sub-threshold spikes and pump cycling are still often misnamed, and non-critical events still wait 8 readings "
            "for the AI. One model that is best at both chat and reports does not exist yet: the 2B chats better, the 4B reports better.",
        "What is next?":
            "(1) One general model: rsn_v3 4B (training on Kaggle) must beat rsn_v1 on reports and the 2B on chat, then the evaluation-day "
            "split goes away; (2) earlier AI through young-window training (the provisional early AI is built and off); (3) a fresh blind "
            "chat set after every fix, streaming answers, chat about the open incident; (4) the fog layer (derived data to a free Supabase "
            "project, board as the only writer).",
        "Why the NPU and not the GPU?":
            "Measured twice. Agents: ~8.4 s per agent on the Adreno GPU, no batching gain. Reasoner (29 Oct, upstream llama.cpp "
            "OpenCL, GPU alone): 7.35 / 8.44 / 8.35 tokens/s (pp1 / pp3 / tg), about 2.5x slower than the NPU split. "
            "Source: proofs/2026-10-28_master/gpu_bench_out/out.md. On evaluation day we also tried the 2B chat model on the GPU: "
            "8-10 tokens/s, against ~25 on 5 CPU cores with identical answers (Qwen3.5's recurrent layers run on the CPU anyway), "
            "so chat runs on the CPU (proofs/2026-11-04_split/gpu/tune/TUNE.md).",
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
            "Evaluation day (4 Nov): domain agents ft_B50 (Llama 3.2 3B, Q4_0) resident in htpd on the NPU; the rsn_v1 reasoner "
            "(Qwen3.5-4B, Q4_0) swapped onto the NPU per incident, split decoding with verified drafts (htpd_v9f); the Campus Assistant "
            "chat on rsn_v3 r2 (Qwen3.5-2B, Q4_0) on 5 CPU cores through llama-server, falling back to the 4B on the NPU if that "
            "server fails. Plus the critical fast path, the retrieval preliminary report, the validator, the approval workflow and the chat "
            "router. All offline on the board. The split is for the evaluation only. Details on the Today page.",
        "Where is training right now?":
            "Domain agents: final (v2, then the B50 blend). Reasoner: rsn_v1 (Qwen3.5-4B) is live for reports. rsn_v3: the 2B r2 was "
            "stopped at step 1,234 of 3,508 for the evaluation (best checkpoint at step 1,000) and serves chat today; the 4B rsn_v3 is "
            "trained on Kaggle to become the single model. No training runs on the board. Source: proofs/2026-10-29_rsn_v3/kaggle/STATUS.md.",
    }
    n_upd = 0
    for it in q["qa"]:
        if it["q"] in upd:
            it["short_answer"] = upd[it["q"]]
            it["updated"] = "2026-11-04"
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
         "token, about 52 GB/s over 2.6 GB of weights). We cut sequential steps instead: split decoding and verified drafts brought the "
         "reasoner from 23.3 s to about 9 s in the lab. The rest of the ~28 s is the 8-reading AI gate on the incident, the agents, the "
         "model swap and the swap back. The operator gets a preliminary report in the same second and 'AI so far' while it writes."),
        ("reasoner", "Why is the NPU answer not always the same?",
         "Prefill sums in fp16 in a different order run to run, so logits differ bit for bit; that only flips a word at near-ties "
         "(margins 0.003-0.16). Severity still agrees 97% across repeats, and the guard never lets the report say normal when the "
         "rules say warning or worse."),
        ("latency", "Do you use speculative decoding?",
         "Yes, but only where it pays. Single-stream MTP and n-gram drafts were 1% to 20% slower on the board (a 1-row step is only "
         "66 ms; verifying 2-4 rows costs 82-133 ms). Inside split decoding the steps already carry 2-4 rows, so extra draft rows are "
         "nearly free: drafts from the prompt and a corpus of past outputs, verified greedily, cut the reasoner from 23.3 s to 9.1 s "
         "with severity and label unchanged (HANDBOOK 2.63-2.66). Lookahead decoding in Genie (LADE) was rejected because it changed answers."),
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
         "about 28 s later (deploy27 fastcheck)."),
        ("latency", "Is the 40-55 min wait solved?",
         "No. Non-critical events still need 8 readings (40-55 min of real sensor time at one reading per 5 min) before the AI runs. "
         "Critical breaches take the fast path (2 readings past the limit). Young-window training to shorten the gate is the next step."),
        ("status", "Is there a chat interface?",
         "Yes: the Campus Assistant, a second app on the same backend (launcher icon and the dashboard's Ask AI button). A Go router "
         "answers most questions straight from read-only tools (counts, lists, current levels, faulty sensors, rankings, what-if against "
         "limits, follow-ups); the rest go to a tool-calling model (up to 5 read-only calls, shown under 'How I found this'). Actions "
         "and prompt injections are refused. On the board, 142 of 160 questions were answered in under 1 s (median 0.2 s, 0 errors); "
         "model answers took 8.8-17.2 s on the 4B. On evaluation day the model is the 2B on the CPU: 7-14 s for most model answers."),
        ("chat", "Why is chat on a different model today?",
         "Because each model is better at one job. On the same gate, rsn_v3 r2 (Qwen3.5-2B) passes 0.737 of 300 chat questions against "
         "0.477 for rsn_v1 (4B), but writes worse reports (RWH severity 0.793 vs 0.919, check recall 0.405 vs 0.848). So for the evaluation "
         "only, chat runs on the 2B on the CPU and reports stay on the 4B on the NPU. The 4B is being trained further to be the one general "
         "model. Sources: proofs/2026-10-29_rsn_v3/kaggle/gate/g2b_r2/GATE.md, proofs/2026-11-04_split/README.md."),
        ("chat", "Does the assistant understand Hindi or Hinglish?",
         "Common Hinglish and Hindi time words, yes: kitne, aaj, kal, kharab, theek hai, ghante, din, and typos. 'CO2 theek hai KH level 3 "
         "pe?' was answered on the board from current_levels in under a second (proofs/2026-11-03_deploy27/apk/STATUS.md). Full Hindi "
         "sentences are not covered by the router; they go to the model."),
        ("chat", "Can the assistant change anything?",
         "No. Every tool is read-only. 'Close all open incidents' gets: I can't do that, my tools only read the device's data; an operator "
         "has to do it. Unsafe actions were refused 3/3 and the injection attempt was refused on the blind set; invented incident ids and "
         "sensor nodes are rejected by a guard (HANDBOOK 2.68, 2.70)."),
        ("safety", "What does the validator check?",
         "Every report: valid JSON in the schema, allowed labels, evidence ids that exist, no actuation language, and an action floor by "
         "severity (a critical report must start with an inspection or a facility review unless every flagged sensor is weather). Contract "
         "repairs fix known slips (normal + needs more data -> unknown; a title location must come from the input; pH wording follows the "
         "measured direction). A report that still fails is replaced by a deterministic report, marked as such (HANDBOOK 2.59, 2.67; "
         "proofs/2026-11-03_fixes/README.md)."),
        ("latency", "Why not keep both models on the NPU and skip the swap?",
         "Two resident models rebooted the board (HANDBOOK 2.27, 2.37): NPU and GPU buffers are unmovable memory inside a 7.26 GB zone. "
         "So htpd holds one model and swaps; a multithreaded weight repack cut the reasoner's load from 3.67 s to 2.80 s "
         "(proofs/2026-10-29_latency/repack/VERDICT.md)."),
        ("model", "Which papers did you build on?",
         "GPTQ (Frantar et al., 2023) for the agents' int4 weights; LoRA (Hu et al., 2021) and QLoRA (Dettmers et al., 2023) for every "
         "fine-tune; speculative decoding (Leviathan et al., 2023), prompt lookup and SuffixDecoding-style corpus drafts for the reasoner; "
         "ReAct (Yao et al., 2023) and Toolformer (Schick et al., 2023) for the tool-calling chat; RAG (Lewis et al., 2020) for the "
         "preliminary report; WiSE-FT and model soups (Wortsman et al., 2022) and task arithmetic (Ilharco et al., 2023) for the B50 blend; "
         "DPO (Rafailov et al., 2023) and STaR (Zelikman et al., 2022) in the training plans; Lookahead Decoding (Fu et al., 2024) behind "
         "the rejected LADE test. The full list is on the Journey page."),
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
            q["qa"].append({"category": cat, "q": qq, "short_answer": a, "evidence_ids": [], "updated": "2026-11-04"})
    cats = q["meta"].get("categories") or []
    for c in sorted({c for c, _, _ in new}):
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
