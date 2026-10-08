"""Step 0 diagnostic: does the DEVICE's weight quantisation alone explain the accuracy drop?

The device runs w4a16: per-output-channel symmetric int4 weights + quantised activations, using
activation ranges calibrated on the BASE model. The host run that scored 94 % used bitsandbytes NF4
(block-64, non-uniform) with bf16 activations - a much finer scheme - so the two were never comparable.

This script reproduces ONLY the device's weight scheme on the host and leaves activations in bf16:

    scale[c] = alpha_c * max(w_max[c]/7, -w_min[c]/8)      (alpha_c chosen per channel to minimise MSE,
    w_q      = clip(round(w/scale), -8, 7) * scale          exactly as refresh_param_scales.py does)

Reading the result:
  * stays near the bf16 control  -> weights are fine, the stale ACTIVATION encodings are the cause
                                    -> fix by exporting at precision w4 (fp16 activations)
  * collapses to ~device level   -> the 4-bit WEIGHTS are the cause
                                    -> fix needs real AIMET recalibration (and w4 alone will not save it)

Usage:
  python fakequant_eval.py --merged <dir> --mode bf16|int4 [--per-role 10] [--max-new 200]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training"))
import features as F  # noqa: E402

PREFILL = '{"pattern": "'
import os
# FQ_MINMAX=1 -> plain per-channel min-max (no clipping), which matches the first device export (v1);
# default MSE-optimal clipping matches the second export (v2).
ALPHAS = torch.tensor([1.0]) if os.environ.get("FQ_MINMAX") == "1" else torch.arange(0.45, 1.001, 0.05)


@torch.no_grad()
def fake_quant_(w: torch.Tensor, bits: int = 4) -> float:
    """In-place per-output-channel symmetric int4 fake quantisation with MSE-optimal clipping.
    Returns the relative RMS error introduced. Channel axis is 0 (output features), matching the
    per-channel grouping the Qualcomm graph uses after it splits attention into per-head convs."""
    orig = w.float()
    flat = orig.reshape(orig.shape[0], -1)
    q = 2 ** (bits - 1)
    base = torch.maximum(flat.max(dim=1).values / (q - 1), -flat.min(dim=1).values / q).clamp_min(1e-12)
    best_s = base.clone()
    best_e = None
    for a in ALPHAS:
        s = (base * a).clamp_min(1e-12).unsqueeze(1)
        deq = (flat / s).round().clamp(-q, q - 1) * s
        e = ((flat - deq) ** 2).mean(dim=1)
        if best_e is None:
            best_e = e
        else:
            take = e < best_e
            best_s[take] = s[take, 0]
            best_e[take] = e[take]
    s = best_s.unsqueeze(1)
    deq = ((flat / s).round().clamp(-q, q - 1) * s).reshape(orig.shape)
    err = float(((orig - deq) ** 2).mean().sqrt() / (orig.pow(2).mean().sqrt() + 1e-12))
    w.copy_(deq.to(w.dtype))
    return err


def prep_int4(src: str, dst: str):
    """Write a copy of the merged checkpoint whose q/k/v/o/gate/up/down weights are fake-quantised
    (device scheme). Done shard by shard on disk so offloading never touches meta tensors."""
    import shutil
    from safetensors import safe_open
    from safetensors.torch import save_file
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file() and f.suffix != ".safetensors":
            shutil.copy(f, dst / f.name)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    errs = []
    for shard in sorted(src.glob("*.safetensors")):
        out = {}
        with safe_open(str(shard), framework="pt") as fh:
            meta = fh.metadata()
            for k in fh.keys():
                t = fh.get_tensor(k)
                if k.endswith("_proj.weight") and t.ndim == 2:
                    g = t.to(dev)
                    errs.append(fake_quant_(g, 4))
                    t = g.cpu()
                    del g
                out[k] = t.contiguous()
        save_file(out, str(dst / shard.name), metadata=meta)
        print(f"  {shard.name}: done", flush=True)
        del out
    print(f"fake-quantised {len(errs)} projection weights; relative RMS error "
          f"mean {sum(errs) / len(errs):.4f} max {max(errs):.4f}", flush=True)


def first_json(text):
    s = text.find("{")
    if s < 0:
        return None
    d = 0
    for i in range(s, len(text)):
        if text[i] == "{":
            d += 1
        elif text[i] == "}":
            d -= 1
            if d == 0:
                try:
                    return json.loads(text[s:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", required=True)
    ap.add_argument("--mode", choices=["bf16", "int4"], default="bf16")
    ap.add_argument("--prep-int4", metavar="OUT_DIR", help="write a fake-quantised copy and exit")
    ap.add_argument("--per-role", type=int, default=10)
    ap.add_argument("--max-new", type=int, default=200)
    a = ap.parse_args()
    if a.prep_int4:
        prep_int4(a.merged, a.prep_int4)
        return

    tok = AutoTokenizer.from_pretrained(a.merged, local_files_only=True)
    tok.pad_token = "<|finetune_right_pad_id|>"
    print(f"loading merged model ({a.mode}) ...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        a.merged, local_files_only=True, torch_dtype=torch.bfloat16,
        device_map="auto", max_memory={0: "4800MiB", "cpu": "7GiB"}, low_cpu_mem_usage=True)
    model.eval()

    rows = [json.loads(l) for l in open(ROOT / "data" / "sft" / "test.jsonl", encoding="utf-8")]
    pick, seen = [], defaultdict(int)
    for r in rows:
        if seen[r["role"]] < a.per_role and not any(
                x["role"] == r["role"] and x["pattern"] == r["pattern"] for x in pick):
            pick.append(r)
            seen[r["role"]] += 1
    print(f"evaluating {len(pick)} held-out examples", flush=True)

    agg = defaultdict(float)
    t0 = time.time()
    for i, r in enumerate(pick, 1):
        gold = json.loads(r["completion"].replace("<|eot_id|>", ""))
        enc = tok(r["prompt"] + PREFILL, add_special_tokens=False, return_tensors="pt").to(model.device)
        out = model.generate(**enc, max_new_tokens=a.max_new, do_sample=False,
                             eos_token_id=[128001, 128008, 128009], pad_token_id=tok.pad_token_id)
        gen = tok.decode(out[0, enc["input_ids"].shape[1]:], skip_special_tokens=True)
        pred = first_json(PREFILL + gen)
        agg["n"] += 1
        if pred is not None:
            agg["json"] += 1
            for k in ("pattern", "status", "likely_cause", "action"):
                agg[k] += float(pred.get(k) == gold.get(k))
        if i % 10 == 0:
            print(f"  [{i}/{len(pick)}] pattern acc so far {agg['pattern'] / agg['n']:.3f} "
                  f"({(time.time() - t0) / i:.1f}s/ex)", flush=True)

    n = agg["n"]
    res = {"mode": a.mode, "ckpt": Path(a.merged).name, "n": int(n), **{k: round(agg[k] / n, 3) for k in
                                           ("json", "pattern", "status", "likely_cause", "action")}}
    print("RESULT", json.dumps(res), flush=True)
    out_dir = ROOT / "training" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "fakequant_step0.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main()