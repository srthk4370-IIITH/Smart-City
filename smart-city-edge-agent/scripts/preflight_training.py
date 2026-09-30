"""Fail fast before spending bandwidth or GPU time on model training."""
from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--data-dir", type=Path, required=True); parser.add_argument("--labels", type=Path, default=Path("data/labels/incidents.jsonl")); args = parser.parse_args()
    checks = []
    checks.append(("python", sys.version_info[:2] in {(3,10),(3,11),(3,12)}, f"{sys.version.split()[0]} (need 3.10-3.12)"))
    checks.append(("dataset", args.data_dir.is_dir(), str(args.data_dir)))
    checks.append(("labels", args.labels.is_file(), f"{args.labels} (required for Llama SFT)"))
    free = shutil.disk_usage(Path.cwd()).free / 2**30
    checks.append(("host free storage", free >= 14, f"{free:.1f} GiB (need >=14 GiB for source download; QIDK export needs much more)"))
    try:
        import torch
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CUDA unavailable"
        checks.append(("CUDA", torch.cuda.is_available(), gpu))
    except ImportError: checks.append(("CUDA", False, "PyTorch unavailable"))
    for name, passed, detail in checks: print(f"{'PASS' if passed else 'BLOCK'} {name}: {detail}")
    return 0 if all(item[1] for item in checks) else 2
if __name__ == "__main__": raise SystemExit(main())
