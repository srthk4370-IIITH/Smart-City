"""Kaggle-side generation shim: runs pipeline/paraphrase_chat.py and replay_general.py UNCHANGED, but answers their
OpenAI-style HTTP calls in-process with the base Qwen3.5-4B (transformers, one replica per GPU, micro-batched).
  python kaggle_gen.py --base /tmp/base --pipeline <r2>/proofs/2026-10-25_reasoner_final/pipeline --what chat|replay"""
import argparse, concurrent.futures as cf, io, json, os, queue, sys, threading, time, urllib.request
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True); ap.add_argument("--pipeline", required=True); ap.add_argument("--what", required=True)
ap.add_argument("--batch", type=int, default=16)
A, rest = ap.parse_known_args()
os.environ["HEAT_HI"] = "999"                       # laptop heat guard not needed on Kaggle
cap = torch.cuda.get_device_capability(0)
DT = torch.bfloat16 if cap[0] >= 8 else torch.float16
tok = AutoTokenizer.from_pretrained(A.base); tok.padding_side = "left"
NG = torch.cuda.device_count()
models = [AutoModelForCausalLM.from_pretrained(A.base, dtype=DT, device_map={"": i}).eval() for i in range(NG)]
print("gen: %d GPU replica(s), dtype %s" % (NG, DT), flush=True)
Q = queue.Queue()


def worker(m):
    dev = m.device
    while True:
        first = Q.get()
        key = (first[0]["temperature"], first[0].get("top_p", 1.0), first[0]["max_tokens"])
        batch, held, t = [first], [], time.time()
        while len(batch) < A.batch and time.time() - t < 0.3:
            try:
                x = Q.get(timeout=0.05)
            except queue.Empty:
                continue
            (batch if (x[0]["temperature"], x[0].get("top_p", 1.0), x[0]["max_tokens"]) == key else held).append(x)
        for h in held:
            Q.put(h)
        texts = [tok.apply_chat_template(b[0]["messages"], add_generation_prompt=True, tokenize=False, enable_thinking=False) for b in batch]
        enc = tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(dev)
        try:
            with torch.no_grad():
                out = m.generate(**enc, max_new_tokens=key[2], do_sample=True, temperature=key[0], top_p=key[1], pad_token_id=tok.pad_token_id or tok.eos_token_id)
            res = [tok.decode(o[enc["input_ids"].shape[1]:], skip_special_tokens=True).strip() for o in out]
        except Exception as e:
            print("gen error:", str(e)[:120], flush=True); res = [""] * len(batch)
        for b, r in zip(batch, res):
            b[1].put(r)


for m in models:
    threading.Thread(target=worker, args=(m,), daemon=True).start()


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=None):
    body = json.loads(req.data.decode())
    box = queue.Queue(); Q.put((body, box)); r = box.get()
    return _Resp(json.dumps({"choices": [{"message": {"content": r}}]}).encode())


urllib.request.urlopen = fake_urlopen
_TPE = cf.ThreadPoolExecutor
cf.ThreadPoolExecutor = lambda *a, **k: _TPE(max_workers=A.batch * NG * 2)   # keep every replica's batch full
sys.path.insert(0, A.pipeline); os.chdir(A.pipeline)
if A.what == "chat":
    import paraphrase_chat as PC
    sys.argv = ["paraphrase_chat.py"] + rest; PC.main()
else:
    import replay_general as RG
    RG.answer("http://in-process")
