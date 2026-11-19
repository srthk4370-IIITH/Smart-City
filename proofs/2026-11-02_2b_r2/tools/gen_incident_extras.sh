#!/usr/bin/env bash
# r2 incident extras: targeted contrastive pairs + a second, larger heatwave set (new seed). CPU, ~1 min.
set -euo pipefail
D=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_r2/data
mkdir -p "$D"
python3 -B /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_r2/tools/gen_r2_targeted.py --out "$D/targeted" --pairs 2000 --test-pairs 220
python3 -B /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_rsn_v3/pipeline/gen_heat_r2.py --out "$D/heat_r2b" --pairs 600 --seed 2711 --dev-frac 0.2 | tail -2
