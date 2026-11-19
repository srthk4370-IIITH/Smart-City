"""Chat eval with the r3 app prompt (chat_think=adaptive + chat_prompt=r3) on a served GGUF (llama-server raw /completion,
greedy). Same loop as rsn_v3 kaggle/local/chat3_eval.py (chatloop.run_samples + verify_chat.verify), but:
  - tools header = tools_r3.json "chat" (21 tools, = backend chat_header_r3.txt, TestChatHeaderR3MatchesTraining);
  - --mode r3test: records of data/final/chat_test_r3.jsonl (system already = the r3 prompt for the record's fog state);
    executor + verifier = tools_r3_impl.ToolsR3(fog=rec.fog, last_sync=rec.last_sync) with the build_r3.py defaults
    (exactly the trainer's --gen-r3 path);
  - --mode dev3: chat dev v3 (rsn_v3 data/chat3_dev.jsonl, the gate set) with its r2 system re-rendered to the r3 one the
    way build_r3.py re-rendered every r2 row (offline fog sentence, last sync seeded per record, full records since
    2026-01-01); executor = ToolsV3 (the rsn_v3 store, their world).
--think 1 = adaptive (prompt opens <think>, capped at --think-budget like htpd/the app), 0 = empty think block (rsn_v1).
Resumable (skips ids already in --out).
  ~/venvs/rsn/bin/python chat_r3_eval.py --port 18098 --mode r3test --think 1 --out OUT.jsonl [--records F] [--limit N]"""
import argparse
import copy
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
H4 = os.path.abspath(os.path.join(HERE, ".."))
QIDK = os.path.abspath(os.path.join(H4, "..", ".."))
KG = os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3", "kaggle")
R3T = os.path.join(H4, "tools")
for p in (KG, R3T):
    if p not in sys.path:
        sys.path.insert(0, p)
import chatloop as CL  # noqa: E402  (puts the rsn_v3 pipeline on sys.path)
import verify_chat as VC  # noqa: E402
from tools_v3_impl import ToolsV3  # noqa: E402

R3_DEFAULTS = {"fog_search_history": {"limit": 5}, "fog_analytics": {"bucket": "month", "group_by": "label"},
               "co_occurring_incidents": {"window_min": 60, "other_domains_only": True},
               "recurring_issues": {"min_count": 3, "by": "sensor"}, "search_knowledge": {"k": 3}}   # = build_r3.py
DEV_SEED = 20261107


def r3_dev_records(recs):
    """chat dev v3 records with the r3 system (build_r3.r3_system_of_r2, one seeded RNG in file order)"""
    import gen_chat_r3 as GR
    R = random.Random(DEV_SEED)
    out = []
    for r in recs:
        r = copy.deepcopy(r)
        m = r["messages"][0]
        assert m["role"] == "system" and m["content"].startswith(GR.HEAD), r["id"]
        ls = GR.last_sync_for(R)
        m["content"] = GR.system_r3("offline", ls, "2026-01-01")
        r["fog"], r["last_sync"], r["since"] = "offline_r2world", ls, "2026-01-01"
        out.append(r)
    return out


class Execs:
    """r3test: one ToolsR3 view per record (stores loaded once per fog state, shared read-only, like train_rsn3.chat_executors)"""
    def __init__(self):
        import tools_r3_impl as TR
        self.TR, self.base = TR, {}

    def of(self, rec):
        s = rec.get("fog", "offline")
        if s not in self.base:
            self.base[s] = self.TR.ToolsR3(fog=s)
        e = copy.copy(self.base[s])
        e.last_sync, e.qid = rec.get("last_sync"), 0
        return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--mode", choices=("r3test", "dev3"), required=True)
    ap.add_argument("--think", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--records", default="")
    ap.add_argument("--tools", default=os.path.join(H4, "data", "final", "tools_r3.json"))
    ap.add_argument("--tokenizer", default=os.path.expanduser("~/models/qwen3.5-4b"))
    ap.add_argument("--think-budget", type=int, default=128)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    VC.DEFAULTS.update(R3_DEFAULTS)
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    tools = json.load(open(a.tools, encoding="utf-8"))["chat"]
    src = a.records or (os.path.join(H4, "data", "final", "chat_test_r3.jsonl") if a.mode == "r3test"
                        else os.path.join(QIDK, "proofs", "2026-10-29_rsn_v3", "data", "chat3_dev.jsonl"))
    recs = [json.loads(l) for l in open(src, encoding="utf-8")]
    if a.mode == "dev3":
        recs = r3_dev_records(recs)
    if a.limit:
        recs = recs[:a.limit]
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out, encoding="utf-8") if l.strip()}
    ex3 = Execs() if a.mode == "r3test" else None
    mk = (lambda rec: ex3.of(rec)) if ex3 else (lambda rec: ToolsV3())
    be = CL.LlamaServerBackend(a.port, think_budget=a.think_budget)
    v3 = ToolsV3() if not ex3 else None
    n = 0
    for rec in recs:
        if rec["id"] in done:
            continue
        s = CL.Sample(rec, 0, a.think)
        t0, k0 = time.time(), be.tokens
        CL.run_samples(be, tok, tools, [s], (lambda r=rec: mk(r)) if ex3 else ToolsV3, VC.parse_turn)
        ver = ex3.of(rec) if ex3 else v3
        ver.qid = 0
        v = VC.verify(rec, CL.candidate(s), executor=ver)
        o = {"id": rec["id"], "kind": rec["kind"], "hard": bool(rec.get("hard")), "must_refuse": bool(rec.get("must_refuse")),
             "fog": rec.get("fog"), "group": rec.get("group"), "hinglish": bool(rec.get("hinglish")), "mode": a.mode, "think": a.think,
             "pass": v["pass"], "reasons": v["reasons"], "warnings": v["warnings"], "think_tokens": v["think_tokens"], "status": s.status,
             "forced": s.forced, "wall_s": round(time.time() - t0, 2), "gen_tokens": be.tokens - k0, "final": v["final"], "new": s.new}
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        n += 1
        if n % 25 == 0:
            print("chat_r3 %s %d done" % (a.mode, n), flush=True)
    print("chat_r3 %s: %d new items -> %s" % (a.mode, n, a.out))


if __name__ == "__main__":
    main()
