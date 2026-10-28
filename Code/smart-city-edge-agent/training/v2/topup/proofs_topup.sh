#!/usr/bin/env bash
# Refresh proofs/2026-10-21_v2_topup from the run dir (safe at any time).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$HOME/venvs/train/bin/python" "$HERE/proofs_topup.py" --run "${RUN:-$HOME/smartcity_runs/agents_v2_topup}"
