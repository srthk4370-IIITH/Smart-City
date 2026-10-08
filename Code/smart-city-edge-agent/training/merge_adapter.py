"""Merge the trained LoRA adapter into full bf16 Llama 3.2 3B weights (CPU), for Qualcomm export."""
from __future__ import annotations

import argparse
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # merge on CPU only (GPU may still be held by eval)
import json
import shutil
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

BASE_ID = "meta-llama/Llama-3.2-3B-Instruct"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    run = Path(a.run)
    out = run / "merged"
    if out.exists() and any(out.glob("*.safetensors")):
        print(f"already merged: {out}")
        raise SystemExit(0)
    base = AutoModelForCausalLM.from_pretrained(BASE_ID, local_files_only=True, torch_dtype=torch.bfloat16,
                                                device_map={"": "cpu"}, low_cpu_mem_usage=True)
    merged = PeftModel.from_pretrained(base, str(run / "adapter"), torch_device="cpu").merge_and_unload()
    merged.config.use_cache = True
    out.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(out, safe_serialization=True, max_shard_size="5GB")
    AutoTokenizer.from_pretrained(BASE_ID, local_files_only=True).save_pretrained(out)
    shutil.copy(run / "adapter" / "training_meta.json", out / "training_meta.json")
    print(json.dumps({"merged": str(out), "files": sorted(p.name for p in out.iterdir())}))
