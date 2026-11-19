#!/usr/bin/env bash
# dry run of select_v2.sh: stub export + stub eval, fake GPU lock, fake snapshots; nothing real touched
TK=$(dirname "$(dirname "$(readlink -f "$0")")")
export DRY=$HOME/dry_sel_v2; mkdir -p $DRY/run/snap_0100 $DRY/run/snap_0200 $DRY/run/snap_0050
export TOPUP_K=$DRY/k; mkdir -p $TOPUP_K; cp -r $HOME/smartcity_runs/agt_topup_k2/dry_run/local $TOPUP_K/local; ln -sfn $DRY/run $TOPUP_K/run
export STATUS=$DRY/STATUS.md STOPF=$DRY/STOP GPU_LOCK=$DRY/GPU_LOCK_FAKE GPU_ASSUME_FREE=1 FINAL_K2=$DRY/FINAL_K2 OLD_POST=$DRY/no_old G0=$DRY/agt3_s0300_q4_0.gguf MIN_FREE_MB=1000 SKIP_BELOW=100
echo fake > $G0
export EXPORT_CMD=$TK/stubs/export_stub.sh EVAL_CMD="python3 $TK/stubs/eval_stub_v2.py" EVAL_TOOL_CMD="python3 $TK/stubs/eval_stub_v2.py"
bash $TK/select_v2.sh; echo "select rc=$?"; cat $FINAL_K2 2>/dev/null; tail -4 $TOPUP_K/post/pick.log
