#!/usr/bin/env bash
# tokens per epoch (Qwen3.5-4B tokenizer, CPU) + MD5SUMS of data/final. Run after run_r3.sh.
set -euo pipefail
cd "$(dirname "$0")"
~/venvs/rsn/bin/python tok_estimate.py 2>&1 | grep -v -i warn
cd ../data/final && md5sum *.jsonl *.json > MD5SUMS && cat MD5SUMS
