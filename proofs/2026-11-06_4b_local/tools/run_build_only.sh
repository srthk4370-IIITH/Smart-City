#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 build_r3.py
python3 check_schema_r3.py
bash finalize_r3.sh
echo R3B_DONE
