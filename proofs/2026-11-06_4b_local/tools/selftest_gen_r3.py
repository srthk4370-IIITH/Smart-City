"""CPU self-test of train_rsn3.py's chat gen-eval verification on r3 (and r2 unchanged):
gold transcripts must pass, corrupted answers (numbers changed / wrong ids / no source) must fail.
  ~/venvs/rsn/bin/python selftest_gen_r3.py"""
import copy, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_r3 as BR  # noqa: E402  (puts verify_chat / chatloop on the path)
sys.path.insert(0, os.path.join(BR.V3, "kaggle"))
import train_rsn3 as T  # noqa: E402
CL = BR.CL
F = BR.FINAL

def gold(rec):
    msgs = copy.deepcopy(CL.gold_messages(rec)[len(CL.prompt_messages(rec)):])
    if rec.get("hard"):
        for m in msgs:
            if m["role"] == "assistant":
                m["reasoning_content"] = BR.rationale(rec)
                break
    return msgs

def wrong(rec):
    msgs = gold(rec)
    fin = msgs[-1]["content"]
    bad = re.sub(r"\d+", lambda m: str(int(m.group(0)) + 7), fin)
    if bad == fin:   # no numbers (refusals, no-call answers): claim an action / drop everything
        bad = "Done, I have synced the fog and deleted the old incidents."
    msgs[-1]["content"] = bad
    return msgs

res = {}
for fn in ("gen_chat_r3.jsonl", "gen_train_chat_r3.jsonl"):
    recs = [json.loads(l) for l in open(os.path.join(F, fn), encoding="utf-8")]
    g = T.verify_chat_recs(recs, [gold(r) for r in recs])
    w = T.verify_chat_recs(recs, [wrong(r) for r in recs])
    res[fn] = {"n": len(recs), "gold_pass": sum(g), "wrong_pass": sum(w)}
r2 = [json.loads(l) for l in open(os.path.join(F, "chat_test_r2.jsonl"), encoding="utf-8")][:40]
g = T.verify_chat_recs(r2, [CL.gold_messages(r)[len(CL.prompt_messages(r)):] for r in r2])
res["chat_test_r2 (default r2 path, refs without think)"] = {"n": len(r2), "gold_pass": sum(g),
                                                             "path": "r2" if T.chat_executors(r2) is None else "r3"}
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(F, "gen_r3_selftest.json"), "w"), indent=1)
