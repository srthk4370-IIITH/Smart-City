"""Domain calibration for llama-imatrix, ALIGNED to chunks: every chunk of CTX tokens starts at a real agent prompt's
<|begin_of_text|> (system prompt at position 0, as on the device), = that prompt + its target JSON, topped up with the
start of the next prompt. Rows (TRAIN splits only): the 3d top-up train set (90 % v2-train replay + targeted 1.5 h /
3 h / early stage rows, HVAC stages, compound...), stratified over (role, stage, window bucket, event-age bucket).
  python make_calib_domain.py --out DIR --chunks 256 --ctx 1280"""
import argparse, json, random, sys, hashlib
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, "/mnt/c/Users/hp/Desktop/qidk/Code/smart-city-edge-agent/training/v2/post")
import common_v2 as C
from transformers import AutoTokenizer

ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--chunks", type=int, default=256)
ap.add_argument("--ctx", type=int, default=1280); ap.add_argument("--seed", type=int, default=11)
ap.add_argument("--data", default=str(Path.home() / "smartcity_runs/agents_v2_topup3d/data/train.jsonl"))
a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
tok = AutoTokenizer.from_pretrained("/home/hp_srthk4370/models/llama-3.2-3b-instruct", local_files_only=True)
rows = [json.loads(l) for l in open(a.data)]
rng = random.Random(a.seed)
cells = defaultdict(list)
for r in rows:
    st = "compound" if r.get("family") == "compound" else (r.get("stage") or "replay")
    cells[(r["role"], st, C.win_bucket(r), C._age(r.get("d")))].append(r)
keys = sorted(cells); rng.shuffle(keys)
for k in keys: rng.shuffle(cells[k])
# targeted stage rows get 40 % of the chunks (they are the weak slices), replay the rest; round-robin over cells
want_t = int(0.4 * a.chunks)
tk = [k for k in keys if k[1] != "replay"]; rk = [k for k in keys if k[1] == "replay"]  # stage rows + every compound row
def rr(ks, n):
    take, i = [], 0
    while len(take) < n and any(cells[k] for k in ks):
        k = ks[i % len(ks)]
        if cells[k]: take.append(cells[k].pop())
        i += 1
    return take
pick = rr(tk, want_t); pick += rr(rk, a.chunks - len(pick)); rng.shuffle(pick)
fill = rr(rk, 4 * a.chunks)  # filler prompts (further real prompt+target) for chunks shorter than ctx
ids_all = []
for i, r in enumerate(pick):
    t = tok(r["prompt"] + r["completion"], add_special_tokens=False)["input_ids"]
    assert t[0] == tok.bos_token_id, "prompt must start with <|begin_of_text|>"
    while len(t) < a.ctx:
        f = fill.pop(); t += tok(f["prompt"] + f["completion"], add_special_tokens=False)["input_ids"]
    ids_all.append(t[:a.ctx])
text = "".join(tok.decode(t, clean_up_tokenization_spaces=False) for t in ids_all)
re_t = tok(text, add_special_tokens=False)["input_ids"]
aligned = len(re_t) == a.ctx * len(ids_all) and all(re_t[j * a.ctx] == tok.bos_token_id for j in range(len(ids_all)))
(out / "calib_domain.txt").write_text(text, encoding="utf-8")
man = {"chunks": len(ids_all), "ctx": a.ctx, "tokens": len(re_t), "aligned_bos_at_every_chunk": aligned, "seed": a.seed,
       "source": a.data, "sha256_16": hashlib.sha256(text.encode()).hexdigest()[:16],
       "mean_sample_tokens": round(sum(r.get("prompt_tokens", 0) + r.get("completion_tokens", 0) for r in pick) / len(pick), 1),
       "by_role": Counter(r["role"] for r in pick), "by_stage": Counter(r.get("stage") for r in pick),
       "by_family": Counter(r.get("family") for r in pick), "by_window": Counter(C.win_bucket(r) for r in pick),
       "by_age": Counter(C._age(r.get("d")) for r in pick), "ids": [r["id"] for r in pick]}
(out / "calib_domain_manifest.json").write_text(json.dumps(man, indent=1))
print(json.dumps({k: v for k, v in man.items() if k != "ids"}, indent=1))
