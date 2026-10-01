"""Download the licensed Llama source model after a capacity and licence check.

This downloads source weights for LoRA training only.  It does not produce a
QAIRT/Genie bundle; that export must use Qualcomm's matching toolchain.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

MODEL_ID = "meta-llama/Llama-3.2-3B-Instruct"
MIN_FREE_GIB = 14


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default=MODEL_ID)
    parser.add_argument("--output-dir", type=Path, default=Path("models/base/llama-3.2-3b-instruct"))
    parser.add_argument("--token-env", default="HF_TOKEN")
    args = parser.parse_args()
    if sys.version_info[:2] not in {(3, 10), (3, 11), (3, 12)}:
        raise SystemExit("Use Python 3.10-3.12 in WSL; this host's Python version is unsupported for the training stack.")
    token = os.environ.get(args.token_env)
    if not token:
        raise SystemExit(f"{args.token_env} is not set. Accept Meta's Llama 3.2 licence on Hugging Face, then export a read token in this shell.")
    destination = args.output_dir.resolve()
    free_gib = shutil.disk_usage(destination.parent if destination.parent.exists() else Path.cwd()).free / (1024**3)
    if free_gib < MIN_FREE_GIB:
        raise SystemExit(f"Need at least {MIN_FREE_GIB} GiB free for source weights and a resumable download; found {free_gib:.1f} GiB.")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("Install requirements-training.txt first.") from exc
    snapshot_download(repo_id=args.model_id, local_dir=destination, token=token, resume_download=True)
    print(f"Downloaded {args.model_id} to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
