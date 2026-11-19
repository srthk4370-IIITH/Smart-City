"""fixed GEN-eval slices for the r2 trainer (from the r2 TEST set, owner decision 2026-11-02): 40 incident rows stratified by
slice (no tool rounds, app system prompt via build_mix.fix) and 40 chat test records (15-tool header; hard and Hinglish kept).
Also re-checks every chat training row with round-1 verify.check_chat and that every call name is in the 15-tool set."""
import collections, json, os, random, sys
Q = "/mnt/c/Users/hp/Desktop/qidk"
sys.path.insert(0, Q + "/proofs/2026-10-25_reasoner_final/pipeline")
import verify as V  # noqa
from build_mix import fix  # noqa
F = Q + "/proofs/2026-11-02_2b_r2/data/final/"
R = random.Random(2020)
te = [json.loads(l) for l in open(F + "incidents_test_r2.jsonl")]
want = {"gen_heldout": 14, "targeted": 10, "targeted_novel_names": 8, "heat": 8}
out = []
for s, n in want.items():
    rs = [r for r in te if r["slice"] == s and not any(m["role"] == "tool" for m in r["messages"])]
    R.shuffle(rs)
    for r in rs[:n]:
        f = fix(dict(r))
        f["slice"] = s
        assert not V.check_incident(dict(f, meta=r.get("meta", {})))
        out.append(f)
open(F + "gen_inc_r2.jsonl", "w").writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
ct = [json.loads(l) for l in open(F + "chat_test_r2.jsonl")]
R.shuffle(ct)
hi = [r for r in ct if r["hinglish"]][:6]
rest = [r for r in ct if not r["hinglish"]][:34]
open(F + "gen_chat_r2.jsonl", "w").writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in hi + rest)
tools = json.load(open(F + "tools_r2.json"))
names = {t["function"]["name"] for t in tools["chat"]}
bad = collections.Counter()
n = 0
for l in open(F + "chat_train.jsonl"):
    r = json.loads(l)
    n += 1
    if r["tools"] not in ("chat", "none"):
        bad["tools:" + r["tools"]] += 1
    for m in r["messages"]:
        for tc in m.get("tool_calls") or []:
            if tc["function"]["name"] not in names:
                bad["unknown_tool"] += 1
    if r["tools"] == "chat":
        e = V.check_chat(dict(r, tool_names=sorted(names)))
        for x in e:
            bad["check_chat:" + x.split(":")[0]] += 1
print("gen slices: inc %d (%s), chat %d (hinglish %d, hard %d); chat train rows %d, problems %s" % (
    len(out), dict(collections.Counter(r["slice"] for r in out)), len(hi + rest), len(hi), sum(bool(r["hard"]) for r in hi + rest), n, dict(bad)))
