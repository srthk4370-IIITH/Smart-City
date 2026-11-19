"""eval_worker.py (runs on Kaggle, one process per GPU): base Llama-3.2-3B fp16 + each LoRA adapter, greedy, same prompts/prefill as the board
(prefill '{"' for tool turn 1, the row's '{"pattern": "' otherwise; app stop rule at '"action"'). Not Q4_0: HF fp16 proxy.
usage: eval_worker.py --pack DIR --base DIR --out DIR --tags a,b,c --deadline EPOCH --sets t1,t2,hard,val
Per row sample files out/<tag>/<set>.jsonl (same fields as hosteval / hosteval_tool); resumable; a model is only STARTED before the deadline."""
import argparse
import json
import os
import sys
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rows as RW  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--pack", required=True)
ap.add_argument("--base", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--tags", required=True)
ap.add_argument("--deadline", type=float, default=1e18)
ap.add_argument("--sets", default="t1,t2,hard,val")
ap.add_argument("--batch", type=int, default=16)
a = ap.parse_args()
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402
from peft import PeftModel  # noqa: E402

dev = torch.device("cuda", 0)
tok = AutoTokenizer.from_pretrained(a.base)
tok.pad_token_id = 128009
tok.padding_side = "left"
base = AutoModelForCausalLM.from_pretrained(a.base, dtype=torch.float16, attn_implementation="sdpa").to(dev)
base.eval()
def _setp(k):  # Kaggle may unpack sets/ to another depth (zip dir-mode): find <k>.jsonl anywhere under the pack
    import glob
    c = [os.path.join(a.pack, "sets", k + ".jsonl")] + sorted(glob.glob(os.path.join(a.pack, "**", k + ".jsonl"), recursive=True))
    for p in c:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("%s.jsonl not under %s: %s" % (k, a.pack, sorted(glob.glob(os.path.join(a.pack, "**"), recursive=True))[:40]))
SETS = {k: [RW.norm(r) for r in RW.read_jsonl(_setp(k))] for k in a.sets.split(",")}
model = None


def gen(rows, pre_fn, max_new):
    res = {}
    order = sorted(rows, key=lambda r: len(r["prompt"]))
    for s in range(0, len(order), a.batch):
        b = order[s:s + a.batch]
        pres = [pre_fn(r) for r in b]
        enc = tok([r["prompt"] + p for r, p in zip(b, pres)], add_special_tokens=False, return_tensors="pt", padding=True).to(dev)
        kw = dict(max_new_tokens=max_new, do_sample=False, eos_token_id=[128009, 128001], pad_token_id=128009)
        try:
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
                try:
                    g = model.generate(**enc, stop_strings=['"action"'], tokenizer=tok, **kw)
                except (TypeError, ValueError):
                    g = model.generate(**enc, **kw)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            g = None
        for i, r in enumerate(b):
            res[r["id"]] = pres[i] + tok.decode(g[i, enc["input_ids"].shape[1]:], skip_special_tokens=True) if g is not None else pres[i]
    return res


def sample_t1(r, text):
    t = text.replace("<|eot_id|>", "").strip()
    try:
        d = json.loads(t)
    except Exception:  # noqa: BLE001
        d = RW.parse(t)
    isc = isinstance(d, dict) and "tool" in d
    g = r["gold"]
    s = {"json": isinstance(d, dict), "call": isc, "turn": r["raw"].get("turn"), "call_ok": None, "direct_ok": None,
         "status": None, "pattern": None, "cause": None, "dq": None}
    if r["raw"].get("turn") == "call":
        s["call_ok"] = bool(isc and d.get("tool") == g.get("tool") and d.get("args") == g.get("args"))
    else:
        s["direct_ok"] = not isc
        if not isc and isinstance(d, dict):
            f = RW.score(g, text)
            s["status"], s["pattern"] = f["status"], f["pattern"]
    return s


for tag in a.tags.split(","):
    if time.time() > a.deadline:
        print("deadline: skipping", tag, flush=True)
        continue
    t0 = time.time()
    d = os.path.join(a.pack, "adapters", tag)
    if not os.path.exists(os.path.join(d, "adapter_config.json")):  # zip dir-mode may unpack one level deeper
        import glob
        g = sorted(glob.glob(os.path.join(a.pack, "**", tag, "adapter_config.json"), recursive=True))
        d = os.path.dirname(g[0]) if g else d
    if model is None:
        model = PeftModel.from_pretrained(base, d, adapter_name=tag)
    else:
        model.load_adapter(d, adapter_name=tag)
    model.set_adapter(tag)
    model.eval()
    for sname in a.sets.split(","):
        op = os.path.join(a.out, tag, sname + ".jsonl")
        if os.path.exists(op + ".done"):
            continue
        os.makedirs(os.path.dirname(op), exist_ok=True)
        rows = SETS[sname]
        if sname == "t1":
            texts = gen(rows, lambda r: '{"', 240)
        else:
            texts = gen(rows, lambda r: RW.prefill(r["completion"]), 400)
        with open(op, "w") as f:
            for r in rows:
                t = texts[r["id"]]
                s = sample_t1(r, t) if sname == "t1" else RW.score(r["gold"], t)
                s.update(id=r["id"], text=t, role=r["role"], family=r["family"])
                f.write(json.dumps(s, default=str) + "\n")
        open(op + ".done", "w").close()
        print("%s %s n=%d %.0fs" % (tag, sname, len(rows), time.time() - t0), flush=True)
    print("MODEL DONE", tag, round(time.time() - t0), "s", flush=True)
