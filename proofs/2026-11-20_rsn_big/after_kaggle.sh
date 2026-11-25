#!/bin/bash
# owner 2026-11-20: when the Kaggle big run is done -> gate (gate_big.sh) automatically; NO automatic deploy:
# the owner sees gate/GATE.md and decides.
BIG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big; S=$BIG/STATUS.md; Q=/mnt/c/Users/hp/Desktop/qidk/proofs
st(){ echo "- $(date '+%F %T') [after_kaggle] $*" >> $S; echo "- after_kaggle $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
N0=$(wc -l < $S)  # only lines written after this start count
until tail -n +$N0 $S | grep -q "done=1"; do
  tail -n +$N0 $S | grep -q "\[launch_big\] FAIL" && { st "launch FAIL seen, no gate (see STATUS.md)"; exit 1; }
  sleep 600
done
A=""
[ -s $BIG/best/best.json ] && A=$(python3 -c "import json;b=json.load(open('$BIG/best/best.json'));print('$BIG/best/ckpt_best_%04d'%int(b['top'][0][1]))" 2>/dev/null)
[ -d "$A" ] || A=$(ls -d $BIG/best/ckpt_best_* 2>/dev/null | sort | tail -1)
[ -d "$A" ] || { st "FAIL: no best adapter in $BIG/best"; exit 1; }
st "gate start with $A"
bash $BIG/gate/gate_big.sh "$A" >> $BIG/logs/gate_big.log 2>&1 || { st "FAIL: gate script (logs/gate_big.log)"; exit 1; }
st "RESULT: gate done -> scores in gate/GATE.md; NO deploy (owner decides)"
