"""Verify the teacher samples (verify_chat.py, executor = ToolsV3 store) and pick the training targets.
Per question: keep up to --keep passing, distinct samples (distinct = different final text or different calls);
think rule for hard records: passing samples with think <= 80 tokens are preferred (non-empty think first); a sample that
fails ONLY on think_too_long is kept only when no short passing sample exists (then 1, counted as long_kept), else it
is dropped (long_dropped). Non-hard records must have an empty think (think_not_empty fails). Questions with no passing
sample get the templated reference answer (gold calls + gold results + reference_answer, empty think).
Questions never sampled (time-limited run) are listed as unsampled and get no row unless --fallback-unsampled.
  python select_distill.py --records chat3_train.jsonl --raw raw_0.jsonl raw_1.jsonl --out chat3_distilled.jsonl --report r.json"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chatloop as CL  # noqa: E402
import verify_chat as VC  # noqa: E402
from tools_v3_impl import ToolsV3  # noqa: E402


def sig(v):
    return (v["final"].strip().lower(), json.dumps([(c["name"], c["args"]) for c in v["calls"]], sort_keys=True, default=str))


def row(rec, new, source, j):
    msgs = CL.prompt_messages(rec) + new
    return {"id": "%s-%s%d" % (rec["id"], source[0], j), "family": "chat3:" + rec["kind"], "tools": "chat", "think": True,
            "hard": bool(rec.get("hard")), "source": source, "messages": msgs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    ap.add_argument("--raw", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--keep", type=int, default=2)
    ap.add_argument("--fallback-unsampled", action="store_true")
    a = ap.parse_args()
    recs = {json.loads(l)["id"]: json.loads(l) for l in open(a.records, encoding="utf-8")}
    raw = {}
    for p in a.raw:
        if os.path.exists(p):
            for l in open(p, encoding="utf-8"):
                o = json.loads(l)
                raw[o["id"]] = o
    ex = ToolsV3()
    K = collections.defaultdict(collections.Counter)
    reasons = collections.Counter()
    think_kept = []
    out = []
    for rid, rec in recs.items():
        kind = rec["kind"]
        st = K[kind]
        st["records"] += 1
        if rid not in raw:
            st["unsampled"] += 1
            if a.fallback_unsampled:
                out.append(row(rec, CL.gold_messages(rec)[len(CL.prompt_messages(rec)):], "reference", 0))
                st["fallback"] += 1
            continue
        short, long_ = [], []
        for s in raw[rid]["samples"]:
            st["samples"] += 1
            if not s["new"] or s["status"] != "final":
                st["s_" + (s["status"] or "empty")] += 1
                reasons["status:" + (s["status"] or "empty")] += 1
                continue
            ex.qid = 0
            v = VC.verify(rec, CL.candidate(s), executor=ex)
            rs = [x.split(":")[0] for x in v["reasons"]]
            for x in rs:
                reasons[x] += 1
            tt = max(v["think_tokens"] or [0])
            if v["pass"]:
                st["pass"] += 1
                short.append((s, v, tt))
            elif rs == ["think_too_long"]:
                st["pass_long"] += 1
                long_.append((s, v, tt))
        # distinct, hard records: non-empty think first, then shorter
        short.sort(key=lambda x: (0 if (not rec.get("hard") or x[2] > 0) else 1, x[2]))
        kept, seen = [], set()
        for s, v, tt in short:
            if sig(v) in seen:
                st["dup"] += 1
                continue
            seen.add(sig(v))
            kept.append((s, tt))
            if len(kept) >= a.keep:
                break
        if kept:
            st["q_pass"] += 1
            st["long_dropped"] += len(long_)
            for j, (s, tt) in enumerate(kept):
                out.append(row(rec, s["new"], "distill", j))
                think_kept.append((rec.get("hard"), tt))
            st["kept"] += len(kept)
        elif long_:
            long_.sort(key=lambda x: x[2])
            s, v, tt = long_[0]
            out.append(row(rec, s["new"], "distill_long", 0))
            think_kept.append((rec.get("hard"), tt))
            st["long_kept"] += 1
            st["kept"] += 1
            st["q_pass"] += 1
        else:
            ref = CL.gold_messages(rec)[len(CL.prompt_messages(rec)):]
            out.append(row(rec, ref, "reference", 0))
            st["fallback"] += 1
    with open(a.out, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    per_kind = {}
    for k, st in sorted(K.items()):
        sampled = st["records"] - st["unsampled"]
        per_kind[k] = dict(st, hard=bool(next(r for r in recs.values() if r["kind"] == k).get("hard")),
                           sample_pass_rate=round(st["pass"] / max(1, st["samples"]), 3),
                           question_pass_rate=round(st["q_pass"] / max(1, sampled), 3))
    tot = collections.Counter()
    for st in K.values():
        tot.update(st)
    hard_t = sorted(t for h, t in think_kept if h)
    rep = {"records": len(recs), "sampled": len(raw), "rows_out": len(out),
           "by_source": dict(collections.Counter(r["source"] for r in out)),
           "sample_pass_rate": round(tot["pass"] / max(1, tot["samples"]), 3),
           "question_pass_rate": round(tot["q_pass"] / max(1, len(raw)), 3),
           "long_kept": tot["long_kept"], "long_dropped": tot["long_dropped"], "fallback": tot["fallback"], "unsampled": tot["unsampled"],
           "hard_think_tokens_kept": {"n": len(hard_t), "zero": sum(1 for t in hard_t if t == 0),
                                      "p50": hard_t[len(hard_t) // 2] if hard_t else None, "max": hard_t[-1] if hard_t else None},
           "fail_reasons": dict(reasons.most_common(30)), "per_kind": per_kind}
    json.dump(rep, open(a.report, "w"), indent=1)
    print("select: %d rows (%s); sample pass %.3f, question pass %.3f, long kept %d / dropped %d, fallback %d, unsampled %d" % (
        len(out), rep["by_source"], rep["sample_pass_rate"], rep["question_pass_rate"], rep["long_kept"], rep["long_dropped"],
        rep["fallback"], rep["unsampled"]))


if __name__ == "__main__":
    main()
