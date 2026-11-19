"""Datasets for the work after 29 Oct (deploys 14-28, chat router, rsn_v3, evaluation-day split).

    py -3 Website/build/collect/recent.py      (run_all.py calls it before fold())

Every number is read from a proof file or copied from the HANDBOOK section named in source_files.
The chat sweep timing is aggregated from the sweep JSONL files at build time (answer times only; no question or
answer text, no sensor values leave this script).
"""
import json as _json
import statistics

from _lib import *  # noqa

S = __file__
CHAT = PROOFS / "2026-11-01_chat"
GATE = PROOFS / "2026-10-29_rsn_v3" / "kaggle" / "gate" / "g2b_r2" / "GATE.md"


def app_ai_update():
    # fastcheck after each deploy: seconds from the fast-path incident to the AI report on the same incident
    rows = [("28 Oct final", 55.2, "2.56"), ("29 Oct retrieval", 47.5, "2.57"), ("deploy14 (30 Oct)", 52.6, "2.63"),
            ("deploy18 spec drafts", 38.5, "2.63"), ("deploy19 live corpus", 27.0, "2.64"), ("deploy20 agent drafts", 21.7, "2.65"),
            ("deploy21 chat drafts", 26.7, "2.66"), ("deploy23 chat router", 27.5, "2.68"), ("deploy27 (3 Nov)", 28.0, "deploy27")]
    write("latency", "lat_app_ai_update", "AI report on the incident after a critical breach, fastcheck after each deploy (QIDK, through the app)", "s",
          [ser("fastcheck AI update", [pt(x, y) for x, y, _ in rows], "ours")],
          [hb_section("2.56"), hb_section("2.57"), hb_section("2.63"), hb_section("2.64"), hb_section("2.65"), hb_section("2.66"),
           hb_section("2.68"), PROOFS / "2026-11-03_deploy27/apk/STATUS.md"], S, n=len(rows), chart={"type": "bar"},
          claim="AI report on the incident: 55.2 s (28 Oct) -> 21.7-28 s since 31 Oct",
          why="Verified drafts inside split decoding cut the reasoner's sequential steps; answers were gated on severity and label.",
          notes="One fastcheck per deploy (the first one when a deploy ran two). Run-to-run spread on the same build is large: "
                "deploy21 gave 26.7 and 37.1 s, deploy27 28.0 and 32.7 s. The fast-path incident itself opened in 5.5-6.8 s in every run.")


def reasoner_spec():
    rows = [("base v8x5", 23.3), ("drafts K=8", 13.8), ("drafts K=4 m=3", 16.0), ("drafts K=8 + ALIGN", 9.1)]
    write("latency", "lat_reasoner_spec", "Reasoner report time with verified speculative drafts inside split decoding (board lab, 6 prompts)", "s",
          [ser("base", [pt(rows[0][0], rows[0][1], n=6)], "alt"), ser("with drafts", [pt(x, y, n=6) for x, y in rows[1:]], "ours")],
          [hb_section("2.63"), hb_section("2.64"), PROOFS / "2026-10-30_spec_split/SIM.md", PROOFS / "2026-10-31_latency/VERDICT.md"], S,
          n=6, chart={"type": "bar"}, claim="Reasoner 23.3 s -> 9.1 s, severity and label 6/6 unchanged",
          why="Split steps already carry 2-4 rows, the costliest NPU range; extra verified draft rows are nearly free.",
          notes="Drafts come from the prompt and a corpus of past reports by the same model; each is verified greedily by the NPU. "
                "Later (deploy19) the corpus learns from the app: 11.83 -> 8.89 s on 6 held-out real incidents, repeated incidents 4.6-5.1 s. "
                "Text differences only in late list fields, the same as base vs itself (2/6 identical).")


def chat_sweeps():
    sets = [("sweep 1", 27, 39), ("held-out", 25, 39)]
    write("app_ux", "ux_chat_sweeps", "Campus Assistant on the board: 40-question sweeps before and after the router fixes", "fraction",
          [ser("before", [pt(s, **rate(b, 40)) for s, b, _ in sets] + [pt("blind (deploy24)", **rate(20, 40))], "alt"),
           ser("after", [pt(s, **rate(a, 40)) for s, _, a in sets], "ours")],
          [CHAT / "VERDICT.md", CHAT / "VERDICT_heldout.md", CHAT / "VERDICT_blind.md", hb_section("2.68"), hb_section("2.69"), hb_section("2.70")], S,
          n=40, chart={"type": "bar"}, claim="27/40 -> 39/40 and 25/40 -> 39/40; the blind set (20/40) led to the question-type layer",
          why="Graded against the board's own incident store at each question's time; unsafe actions were refused 3/3.",
          notes="The 'after' scores reuse the questions the fixes were designed from; the blind sets measure generalisation. "
                "The blind set was fixed by intent classes, a span parser and a tool guard (deploy25), not phrase patches.")


def chat_timing():
    files = ["sweep20_s1_d27.jsonl", "sweep21_heldout_d27.jsonl", "sweep22_blind_d27.jsonl", "sweep23_blind2_d27.jsonl"]
    w, err, busy = [], 0, 0
    used = []
    for f in files:
        p = CHAT / f
        if not p.exists():
            continue
        used.append(p)
        for r in read_jsonl(p):
            w.append(float(r.get("wall_s") or 0))
            err += bool(r.get("error"))
            busy += bool(r.get("busy"))
    if len(w) < 2:
        return
    b = [("< 1 s (router)", sum(x < 1 for x in w)), ("1-9 s", sum(1 <= x < 9 for x in w)),
         ("9-12 s", sum(9 <= x < 12 for x in w)), (">= 12 s", sum(x >= 12 for x in w))]
    slow = [x for x in w if x >= 1]
    write("app_ux", "ux_chat_timing", f"Campus Assistant answer time on the board, {len(w)} questions (4B build deploy27)", "count",
          [ser("answers", [pt(x, y, n=len(w)) for x, y in b], "ours")], used + [hb_section("2.70")], S, n=len(w), chart={"type": "bar"},
          claim=f"{b[0][1]}/{len(w)} answered by the router in under 1 s; median {statistics.median(w):.1f} s; {err} errors",
          why="The Go router answers most questions straight from read-only tools; only the rest wait for the model on the NPU.",
          notes=f"Model-routed answers: {len(slow)}, {min(slow):.1f}-{max(slow):.1f} s (median {statistics.median(slow):.1f} s). "
                f"Busy replies: {busy}. These runs are timed, not yet graded.")


def reasoner_models():
    txt = text(GATE) if GATE.exists() else ""

    def g(suite, metric):
        m = re.search(rf"\| {suite} \| {metric} \| ([0-9.]+) \| ([0-9.]+) \|", txt)
        return (float(m.group(1)), float(m.group(2))) if m else (None, None)
    rows = [("RWH severity", "rwh", "severity", 150), ("RWH label", "rwh", "label", 150),
            ("RWH check recall", "rwh", "check_recall", 150), ("chat dev v3 pass", "chatdev3", "pass_rate", 300)]
    v3, v1 = [], []
    for name, s, m, n in rows:
        a, b = g(s, m)
        if a is None:
            return
        v3.append(pt(name, **rate_from(a, n)))
        v1.append(pt(name, **rate_from(b, n)))
    write("accuracy", "acc_reasoner_split", "Reports vs chat: rsn_v1 (Qwen3.5-4B) against rsn_v3 r2 (Qwen3.5-2B), same gate (host Q4_0)", "fraction",
          [ser("rsn_v1 4B (reports, NPU)", v1, "ours"), ser("rsn_v3 r2 2B (chat on eval day, GPU)", v3, "alt")],
          [GATE, PROOFS / "2026-11-02_2b_r2/DIAG.md", PROOFS / "2026-11-04_split/apk/README.md"], S, n=300, chart={"type": "bar"},
          claim="The 4B writes better reports (severity 0.919 vs 0.793); the 2B chats better (0.737 vs 0.477)",
          why="Evaluation day only: chat on the 2B (CPU), reports on the 4B (NPU). The 4B is trained further to be the single model.",
          notes="Gate rule: every report metric >= rsn_v1 and chat pass rate > rsn_v1. The 2B fails the report part (also schema errors "
                "0.147 vs 0.081) and passes chat (calls_ok 0.827 vs 0.65, facts_ok 0.79 vs 0.61).")


def rsn_v1_v2():
    pts = lambda a, b, c: [pt("severity", **rate_from(a, 106)), pt("label", **rate_from(b, 106)), pt("check recall", y=c, n=106)]
    write("accuracy", "acc_rsn_v1_v2", "rsn_v1 vs rsn_v2 on the same 106 held-out incidents (host copy of the board model)", "fraction",
          [ser("rsn_v1 (kept)", pts(0.947, 0.884, 0.90), "ours"), ser("rsn_v2 (rejected)", pts(0.876, 0.856, 0.81), "alt")],
          [hb_section("2.59"), PROOFS / "2026-10-28_master/RSN_V2_RETRY.md"], S, n=106, chart={"type": "bar"},
          claim="rsn_v2 was 10% faster but lost 7 points of severity: rsn_v1 stays",
          why="Severity is what operators act on; accuracy comes before latency.",
          notes="On the board rsn_v2 also invented a title location (q19) and misread 324 > 300 ppm (q11).")


def main():
    app_ai_update()
    reasoner_spec()
    chat_sweeps()
    chat_timing()
    reasoner_models()
    rsn_v1_v2()


if __name__ == "__main__":
    main()
    print("recent: ok")
