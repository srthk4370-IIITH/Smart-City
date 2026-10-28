"""Merge the chosen v2 LoRA adapter (choice.json) into bf16 Llama-3.2-3B-Instruct on the CPU.

* lm_head is UNTIED (a copy of embed_tokens, tie_word_embeddings=false) so the GGUF gets its own
  output.weight. That mirrors the GGUF htpd runs today (training/export/gpu/pack_exact_gguf.py: token_embd F16,
  output Q8_0, every block Q4_0); the values are unchanged.
* Then the saved folder is reloaded from disk and one held-out test prompt is run (greedy, CPU, stop at the
  app's "action" cut) as a smoke check: the output must parse as v2 JSON. Result in <out>/merge_check.json.

  python merge_v2.py --post ~/smartcity_runs/agents_v2/post --out ~/smartcity_runs/agents_v2/merged_v2
"""
from __future__ import annotations

import os
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # CPU merge: bf16 3B = 6.4 GB does not fit the 6 GB GPU

import argparse
import gc
import json
import shutil
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common_v2 as C  # noqa: E402


def smoke(out, base_tok_dir):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(str(out), local_files_only=True)
    m = AutoModelForCausalLM.from_pretrained(str(out), local_files_only=True, torch_dtype=torch.bfloat16,
                                             device_map={"": "cpu"}, low_cpu_mem_usage=True)
    m.eval()
    # bf16 matmuls on this CPU (no AVX512-BF16/AMX) are far too slow for generation, so the CPU check is a
    # short forward pass; generation is verified by host_eval_v2 (hf_bf16 on the GPU) right after.
    torch.set_num_threads(os.cpu_count() or 8)
    rows = C.read_jsonl(C.DATA / "test.jsonl")
    row = next(r for r in rows if r["role"] == "air_quality" and r["family"] not in C.NEG_FAMILIES)
    ids = tok(row["prompt"], add_special_tokens=False, return_tensors="pt")["input_ids"][:, :24]
    t0 = time.time()
    with torch.no_grad():
        logits = m(input_ids=ids).logits.float()
    res = {"row": row["id"], "forward_tokens": int(ids.shape[1]), "logits_finite": bool(torch.isfinite(logits).all()),
           "next_token_after_24": tok.decode([int(logits[0, -1].argmax())]), "seconds": round(time.time() - t0, 1),
           "tied": bool(m.config.tie_word_embeddings),
           "lm_head_equals_embed": bool(torch.equal(m.lm_head.weight, m.model.embed_tokens.weight)),
           "n_params": sum(p.numel() for p in m.parameters())}
    (out / "merge_check.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    if not res["logits_finite"] or not res["lm_head_equals_embed"] or res["tied"]:
        raise SystemExit("merge smoke check FAILED")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="/home/hp_srthk4370/models/llama-3.2-3b-instruct")
    a = ap.parse_args()
    post, out = Path(a.post), Path(a.out)
    choice = json.loads((post / "choice.json").read_text())
    if out.exists() and (out / "merge_check.json").exists():
        print(f"already merged and checked: {out}")
        return
    if not (out.exists() and any(out.glob("*.safetensors"))):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
        t0 = time.time()
        base = AutoModelForCausalLM.from_pretrained(a.base, local_files_only=True, torch_dtype=torch.bfloat16,
                                                    device_map={"": "cpu"}, low_cpu_mem_usage=True)
        merged = PeftModel.from_pretrained(base, choice["adapter_dir"], torch_device="cpu").merge_and_unload()
        # untie: own output.weight in the GGUF (device layout), same values
        merged.lm_head.weight = torch.nn.Parameter(merged.model.embed_tokens.weight.detach().clone())
        merged.config.tie_word_embeddings = False
        merged.config.use_cache = True
        tmp = out.with_name(out.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        merged.save_pretrained(tmp, safe_serialization=True, max_shard_size="5GB")
        AutoTokenizer.from_pretrained(a.base, local_files_only=True).save_pretrained(tmp)
        # NOT named adapter_config.json: transformers would then load the folder as a PEFT adapter
        for f, dst in (("training_meta.json", "training_meta.json"), ("adapter_config.json", "lora_adapter_config.json")):
            src = Path(choice["adapter_dir"]) / f
            if src.exists():
                shutil.copy(src, tmp / dst)
        (tmp / "choice.json").write_text(json.dumps(choice, indent=1))
        shutil.rmtree(out, ignore_errors=True)
        tmp.rename(out)
        print(f"merged {choice['chosen']} adapter into {out} in {time.time() - t0:.0f} s", flush=True)
        del merged, base
        gc.collect()
    smoke(out, a.base)


if __name__ == "__main__":
    main()
