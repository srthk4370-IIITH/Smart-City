"""Verify that the Qualcomm QIDK checkout required for Genie export is real."""
from __future__ import annotations
import argparse
from pathlib import Path

REQUIRED = ("GenAI-Solutions/AI-Assistant", "GenAI-Solutions/ASR-LLM-TTS", "Tools/qairt_docker")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--qidk-root", type=Path, required=True); args = parser.parse_args()
    missing = [item for item in REQUIRED if not (args.qidk_root / item).is_dir()]
    if missing:
        raise SystemExit("Invalid/incomplete QIDK checkout; missing: " + ", ".join(missing))
    print(f"Verified QIDK checkout: {args.qidk_root.resolve()}")
