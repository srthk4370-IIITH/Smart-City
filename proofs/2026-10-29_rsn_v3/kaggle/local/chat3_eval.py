"""Chat dev v3 on a served GGUF (llama-server raw /completion, greedy): the record's history + last question rendered with the
model's chat template and the tools_v4 chat header, tools executed on the training store (ToolsV3), output verified with
verify_chat.py. --think 1 = adaptive thinking (rsn_v3: open <think>, capped at --think-budget tokens like htpd);
--think 0 = empty think block (rsn_v1's trained mode). Resumable (skips ids already in --out).
  ~/venvs/rsn/bin/python chat3_eval.py --port 18097 --think 1 --out results.jsonl [--records chat3_dev.jsonl] [--limit N]"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import chatloop as CL  # noqa: E402
import verify_chat as VC  # noqa: E402
from tools_v3_impl import ToolsV3  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--think", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--records", default=os.path.join(CL.V3, "data", "chat3_dev.jsonl"))
    ap.add_argument("--tokenizer", default=os.path.expanduser("~/models/qwen3.5-4b"))
    ap.add_argument("--think-budget", type=int, default=128)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    tools = CL.load_tools()["chat"]
    recs = [json.loads(l) for l in open(a.records, encoding="utf-8")]
    if a.limit:
        recs = recs[:a.limit]
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out, encoding="utf-8")}
    be = CL.LlamaServerBackend(a.port, think_budget=a.think_budget)
    ex = ToolsV3()
    n = 0
    for rec in recs:
        if rec["id"] in done:
            continue
        s = CL.Sample(rec, 0, a.think)
        t0, k0 = time.time(), be.tokens
        CL.run_samples(be, tok, tools, [s], ToolsV3, VC.parse_turn)
        ex.qid = 0
        v = VC.verify(rec, CL.candidate(s), executor=ex)
        o = {"id": rec["id"], "kind": rec["kind"], "hard": bool(rec.get("hard")), "must_refuse": bool(rec.get("must_refuse")),
             "pass": v["pass"], "reasons": v["reasons"], "warnings": v["warnings"], "think_tokens": v["think_tokens"], "status": s.status,
             "forced": s.forced, "wall_s": round(time.time() - t0, 2), "gen_tokens": be.tokens - k0, "final": v["final"], "new": s.new}
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        n += 1
        if n % 25 == 0:
            print("chatdev3 %d done" % n, flush=True)
    print("chatdev3: %d new items -> %s" % (n, a.out))


if __name__ == "__main__":
    main()
