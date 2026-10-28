"""Low-memory LoRA merge (for an 8 GB WSL): the same result as post/merge_v2.py, one tensor at a time.

W' = bf16(W + (B @ A) * (alpha / r)) with the sum in float32 (what PEFT's
merge_and_unload does on the CPU). lm_head is untied: lm_head.weight = a copy of embed_tokens, tie_word_embeddings
false (as merge_v2.py). Output: small shards (one per decoder layer) + index, config, tokenizer, choice.json,
merge_check.json. Peak RAM is about one layer, not the whole 6.4 GB model.

  python merge_lowmem.py --post <run>/post --out <run>/merged_xxx [--compare <a merge_v2 output dir>]
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import defaultdict
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import save_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="/home/hp_srthk4370/models/llama-3.2-3b-instruct")
    ap.add_argument("--compare", default=None, help="merge_v2 output to compare a few tensors with (exactness check)")
    a = ap.parse_args()
    post, out, base = Path(a.post), Path(a.out), Path(a.base)
    choice = json.loads((post / "choice.json").read_text())
    if (out / "merge_check.json").exists():
        print("already merged:", out)
        return
    t0 = time.time()
    adir = Path(choice["adapter_dir"])
    acfg = json.loads((adir / "adapter_config.json").read_text())
    scale = acfg["lora_alpha"] / acfg["r"]
    lora = {}
    with safe_open(str(adir / "adapter_model.safetensors"), "pt") as f:
        for k in f.keys():
            lora[k] = f.get_tensor(k)
    idx = json.loads((base / "model.safetensors.index.json").read_text())["weight_map"]
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    group_keys = defaultdict(list)
    for k in idx:
        parts = k.split(".")
        group_keys[f"layer{int(parts[2]):02d}" if parts[1] == "layers" else "other"].append(k)
    names = sorted(group_keys) + ["lmhead"]
    handles = {fn: safe_open(str(base / fn), "pt") for fn in set(idx.values())}
    wmap, merged_n, total, finite = {}, 0, 0, True
    keep = {}  # tensors needed for the final checks / compare
    watch = {"model.layers.0.self_attn.q_proj.weight", "model.layers.13.mlp.down_proj.weight", "model.layers.27.mlp.up_proj.weight",
             "model.norm.weight", "model.embed_tokens.weight"}
    for i, g in enumerate(names):
        tensors = {}
        if g == "lmhead":
            tensors["lm_head.weight"] = keep["model.embed_tokens.weight"].clone()
        for k in group_keys.get(g, []):
            w = handles[idx[k]].get_tensor(k)
            mod = k[: -len(".weight")] if k.endswith(".weight") else None
            la, lb = (f"base_model.model.{mod}.lora_A.weight", f"base_model.model.{mod}.lora_B.weight") if mod else (None, None)
            if la in lora:
                delta = (lora[lb].float() @ lora[la].float()) * scale
                w = (w.float() + delta).to(w.dtype).contiguous()  # PEFT: fp32 delta added in place to the bf16 weight
                merged_n += 1
            tensors[k] = w
        name = f"model-{i + 1:05d}-of-{len(names):05d}.safetensors"
        save_file(tensors, str(tmp / name), metadata={"format": "pt"})
        for k, t in tensors.items():
            wmap[k] = name
            total += t.numel() * t.element_size()
            finite = finite and bool(torch.isfinite(t).all())
            if k in watch or k == "lm_head.weight":
                keep[k] = t
        del tensors
    assert merged_n == len([k for k in lora if k.endswith("lora_A.weight")]), (merged_n, len(lora))
    (tmp / "model.safetensors.index.json").write_text(json.dumps({"metadata": {"total_size": total}, "weight_map": wmap}, indent=2))
    cfg = json.loads((base / "config.json").read_text())
    cfg["tie_word_embeddings"] = False
    cfg["use_cache"] = True
    cfg["torch_dtype"] = "bfloat16"
    (tmp / "config.json").write_text(json.dumps(cfg, indent=2))
    for f in ("generation_config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json"):
        shutil.copy(base / f, tmp / f)
    shutil.copy(adir / "adapter_config.json", tmp / "lora_adapter_config.json")
    (tmp / "choice.json").write_text(json.dumps(choice, indent=1))
    emb, lm = keep["model.embed_tokens.weight"], keep["lm_head.weight"]
    check = {"method": "merge_lowmem (tensor-wise, PEFT arithmetic)", "lora_modules_merged": merged_n, "scale": scale,
             "all_finite": finite,
             "lm_head_equals_embed": bool(torch.equal(emb, lm)), "tied": False, "seconds": round(time.time() - t0, 1)}
    if a.compare:
        ref = Path(a.compare)
        rmap = json.loads((ref / "model.safetensors.index.json").read_text())["weight_map"]
        diffs = {}
        for k in ("model.layers.0.self_attn.q_proj.weight", "model.layers.13.mlp.down_proj.weight", "model.layers.27.mlp.up_proj.weight",
                  "lm_head.weight", "model.norm.weight"):
            with safe_open(str(ref / rmap[k]), "pt") as f:
                r = f.get_tensor(k)
            mine = keep[k]
            diffs[k] = {"equal": bool(torch.equal(r, mine)), "max_abs_diff": float((r.float() - mine.float()).abs().max())}
        check["compare_with_merge_v2"] = {"ref": str(ref), "tensors": diffs}
    (tmp / "merge_check.json").write_text(json.dumps(check, indent=1))
    if not (check["all_finite"] and check["lm_head_equals_embed"]):
        raise SystemExit(f"merge check failed: {check}")
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    print(json.dumps(check, indent=1))


if __name__ == "__main__":
    main()
