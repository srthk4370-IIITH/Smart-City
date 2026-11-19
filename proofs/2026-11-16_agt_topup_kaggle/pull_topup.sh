#!/usr/bin/env bash
# pull_topup.sh [--once]: pull.sh of agt_v3 with the top-up conf (separate run area / STATE / slugs)
TK=$(dirname "$(readlink -f "$0")")
export AGT_CONF=$TK/agt_topup.conf
exec bash "${AGT_DIR:-/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_train/agt}/pull.sh" "$@"
