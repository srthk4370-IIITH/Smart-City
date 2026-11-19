"""Stage (a) on Kaggle: verified self-distillation of the chat3 train questions with the BASE Qwen3.5-4B.
One process per GPU (--shard i --nshards n); K samples per question (temperature 0.7), thinking on for hard records
(budget-forced at --think-budget tokens, teacher hint appended to the system prompt; the hint is NOT kept in the
training rows), off for the others; tool calls executed on the bundled ToolsV3 store. Resumable: records already in
--out are skipped; stops cleanly at --hours. Verification + selection happen afterwards in select_distill.py.
  python distill.py --base /tmp/base --records chat3_train.jsonl --out raw_0.jsonl --shard 0 --nshards 2 [--mock]"""
import argparse
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chatloop as CL  # noqa: E402
import verify_chat as VC  # noqa: E402  (chatloop put pipeline/ on sys.path)
from tools_v3_impl import ToolsV3  # noqa: E402


def order_records(recs, seed=29):
    """stratified shuffle: round-robin over kinds in shuffled order, so a time-limited run still covers every kind"""
    R = random.Random(seed)
    by = {}
    for r in recs:
        by.setdefault(r["kind"], []).append(r)
    for v in by.values():
        R.shuffle(v)
    kinds = sorted(by)
    R.shuffle(kinds)
    out = []
    while any(by.values()):
        for k in kinds:
            if by[k]:
                out.append(by[k].pop())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    ap.add_argument("--records", required=True)
    ap.add_argument("--tools", default=os.path.join(CL.PIPE, "tools_v4.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--think-budget", type=int, default=128)
    ap.add_argument("--chunk", type=int, default=8, help="records per chunk (x k samples generated together)")
    ap.add_argument("--max-batch", type=int, default=16)
    ap.add_argument("--tok-budget", type=int, default=48000, help="padded tokens per micro-batch")
    ap.add_argument("--hours", type=float, default=99)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mock", action="store_true", help="no model: replay gold calls (dry run of the plumbing)")
    ap.add_argument("--tiny", default="", help="dry run with a small random-init model built from this config dir")
    a = ap.parse_args()
    t0 = time.time()
    recs = [json.loads(l) for l in open(a.records, encoding="utf-8")]
    recs = order_records(recs)[a.shard::a.nshards]
    if a.limit:
        recs = recs[:a.limit]
    done = set()
    if os.path.exists(a.out):
        for l in open(a.out, encoding="utf-8"):
            try:
                done.add(json.loads(l)["id"])
            except Exception:
                pass
    todo = [r for r in recs if r["id"] not in done]
    log = lambda m: print("[%s distill %d/%d] %s" % (time.strftime("%H:%M:%S"), a.shard, a.nshards, m), flush=True)
    log("%d records in shard, %d done, %d to do, k=%d" % (len(recs), len(done), len(todo), a.k))
    tools = CL.load_tools(a.tools)["chat"]
    mk = lambda: ToolsV3()
    backend = tok = None
    if not a.mock:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(a.base)
        if a.tiny:
            from transformers import AutoConfig
            cfg = AutoConfig.from_pretrained(a.tiny)
            torch.manual_seed(0)
            model = AutoModelForCausalLM.from_config(cfg).eval()
        else:
            dt = torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16
            model = AutoModelForCausalLM.from_pretrained(a.base, dtype=dt, device_map={"": 0}).eval()
        backend = CL.HFBackend(model, tok, temperature=a.temperature, think_budget=a.think_budget, max_batch=a.max_batch,
                               tok_budget=a.tok_budget, max_new=60 if a.tiny else 420, log=log)
    else:
        from transformers import AutoTokenizer  # only for rendering checks; fine without a GPU
        tok = AutoTokenizer.from_pretrained(a.base) if a.base else None
    n_chunks = 0
    for c0 in range(0, len(todo), a.chunk):
        if (time.time() - t0) / 3600 > a.hours:
            log("time budget reached (%.2f h): stopping, resumable" % a.hours)
            break
        chunk = todo[c0:c0 + a.chunk]
        samples = [CL.Sample(r, k, r.get("hard")) for r in chunk for k in range(a.k)]
        tc = time.time()
        if a.mock:
            CL.run_mock(samples, mk, VC.parse_turn, VC.render_calls)
            if tok is not None:    # the canonical re-render must accept every produced transcript
                for s in samples:
                    CL.render(tok, CL.prompt_messages(s.rec) + s.new, tools, s.think)
        else:
            CL.run_samples(backend, tok, tools, samples, mk, VC.parse_turn, teacher_hint=True)
        with open(a.out, "a", encoding="utf-8") as f:
            for r in chunk:
                ss = [s.to_json() for s in samples if s.rec is r]
                f.write(json.dumps({"id": r["id"], "kind": r["kind"], "hard": bool(r.get("hard")), "samples": ss}, ensure_ascii=False) + "\n")
        n_chunks += 1
        if n_chunks % 10 == 1 or a.mock:
            el = time.time() - t0
            nd = c0 + len(chunk)
            log("%d/%d records, chunk %.1f s, elapsed %.2f h, ETA shard %.2f h" % (nd, len(todo), time.time() - tc, el / 3600,
                el / nd * (len(todo) - nd) / 3600))
    left = len([r for r in todo]) - min(len(todo), n_chunks * a.chunk)
    json.dump({"shard": a.shard, "records": len(recs), "left": max(0, left), "t": time.time()},
              open(a.out + ".status.json", "w"))
    log("exit: %d left" % max(0, left))


if __name__ == "__main__":
    main()
