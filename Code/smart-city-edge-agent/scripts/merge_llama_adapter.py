"""Merge the validated shared LoRA adapter into local Llama weights for export."""
from __future__ import annotations
import argparse
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("models/base/llama-3.2-3b-instruct"))
    parser.add_argument("--adapter", type=Path, default=Path("models/llama-lora/agent-orchestrator-3b"))
    parser.add_argument("--output", type=Path, default=Path("models/merged/llama-3.2-3b-agent-orchestrator"))
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()): raise SystemExit(f"Refusing to overwrite {args.output}")
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc: raise SystemExit("Install requirements-training.txt first.") from exc
    model = AutoModelForCausalLM.from_pretrained(args.base, local_files_only=True, torch_dtype=torch.float16, device_map="cpu")
    merged = PeftModel.from_pretrained(model, args.adapter).merge_and_unload()
    args.output.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(args.output, safe_serialization=True)
    AutoTokenizer.from_pretrained(args.base, local_files_only=True).save_pretrained(args.output)
    print(f"Merged model written to {args.output}. Export this directory with the Qualcomm-compatible workflow.")
