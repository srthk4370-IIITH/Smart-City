#!/usr/bin/env bash
# paths_r4.sh (source it): resolve the r4 data files (another agent writes proofs/2026-11-12_topup_r4/data/final/). An env var
# that is already set wins (run_r4.env). Otherwise one file per pattern; none or several = unresolved (left empty; the caller
# decides whether that is fatal). r3 fallbacks: tools_r3.json for TOOLS4, the r3 gen slices for the r3 eval (always).
D4=${D4:-/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-12_topup_r4/data/final}
D3=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-06_4b_local/data/final
_pick() {   # _pick VAR pattern...: first pattern with exactly one match
  local v=$1; shift
  [ -n "${!v:-}" ] && return 0
  local p m
  for p in "$@"; do
    m=$(ls -1 $D4/$p 2>/dev/null | grep -v '\.part$')
    if [ "$(echo "$m" | grep -c .)" = 1 ]; then printf -v "$v" '%s' "$m"; return 0; fi
  done
}
_pick NEW "train_new*.jsonl" "*train*new*.jsonl"
_pick REPLAY "replay*.jsonl" "*replay*.jsonl"
_pick DEV4_INC "dev*inc*.jsonl" "dev_r4_inc*.jsonl"
_pick DEV4_CHAT "dev*chat*.jsonl"
_pick TEST4_INC "test*inc*.jsonl" "incidents_test*.jsonl"
_pick TEST4_CHAT "test*chat*.jsonl" "chat_test*.jsonl"
_pick TOOLS4 "tools*.json"
TOOLS4=${TOOLS4:-$D3/tools_r3.json}
GEN_INC3=${GEN_INC3:-/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-02_2b_r2/data/final/gen_inc_r2.jsonl}   # = the r3 run's GEN_INC
GEN_CHAT3=${GEN_CHAT3:-$D3/gen_chat_r3.jsonl}
export NEW REPLAY DEV4_INC DEV4_CHAT TEST4_INC TEST4_CHAT TOOLS4 GEN_INC3 GEN_CHAT3
paths_show() { echo "NEW=${NEW:-?} REPLAY=${REPLAY:-?} DEV4_INC=${DEV4_INC:-?} DEV4_CHAT=${DEV4_CHAT:-?} TEST4_INC=${TEST4_INC:-?} TEST4_CHAT=${TEST4_CHAT:-?} TOOLS4=$TOOLS4"; }
