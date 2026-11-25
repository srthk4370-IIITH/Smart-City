#!/usr/bin/env bash
# run_big.sh: THE launcher of the reasoner big top-up. Waits (polls every 10 min, touches nothing of the agent-rows process or the GPU) until the 4500 agent
# rows exist, builds block D + assembles + tokens + plan + audit, and only when the audit says PASS runs launch_big.sh auto (Kaggle sessions 1-2, resume).
#   detached:  bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh rsn_big_run /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big/run_big.sh
# Stop: touch proofs/2026-11-20_rsn_big/STOP (no new stage starts; a running Kaggle session is never killed).
BIG=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-20_rsn_big; RSN=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-13_v3_data/rsn; D=$BIG/data/final_big
STATUS=$BIG/STATUS.md; REG=/mnt/c/Users/hp/Desktop/qidk/proofs/AGENT_REGISTRY.md; N_ROWS=${N_ROWS:-4500}; MIN_ROWS=${MIN_ROWS:-4300}
status() { echo "- $(date '+%F %T') [run_big] $*" >> $STATUS; echo "$*"; }
reg() { echo "- rsn-big: $* ($(date '+%F %H:%M'))" >> $REG; }
cd $BIG || exit 1
while true; do
  [ -e $BIG/STOP ] && { status "STOP file: not continuing"; exit 3; }
  n=$(wc -l < agent_rows/agent_out.jsonl 2>/dev/null || echo 0); run=$(pgrep -f v2_agent_run_gpu.py > /dev/null && echo 1 || echo 0)
  [ "$n" -ge "$N_ROWS" ] && break
  [ "$run" = 0 ] && [ "$n" -ge "$MIN_ROWS" ] && { status "agent process ended with $n rows (>= $MIN_ROWS): continuing"; break; }
  [ "$run" = 0 ] && { status "agent process ended with only $n rows: waiting (poll 10 min)"; }
  status "agent rows $n/$N_ROWS (running=$run)"; sleep 600
done
reg "agent rows in ($n): building block D + final data"
export CUDA_VISIBLE_DEVICES=
nice -n 15 python3 build/build_big.py --stage D > logs/build_D.log 2>&1 || { status "FAIL stage D"; exit 1; }
nice -n 15 python3 build/build_big.py --stage assemble > logs/build_assemble.log 2>&1 || { status "FAIL assemble"; exit 1; }
nice -n 15 ~/venvs/rsn/bin/python $RSN/tok_v4.py $D > logs/tokens.log 2>&1 || { status "FAIL tokens"; exit 1; }
nice -n 15 python3 build/check_big.py $D > logs/check.log 2>&1; rc=$?
status "data check rc $rc: $(tail -n 3 $D/CHECK.md | tr '\n' ' ' | cut -c1-200)"
[ $rc = 0 ] || { reg "data audit FAILED (see data/final_big/CHECK.md): fix the generator, no launch"; exit 2; }
python3 build/plan_big.py $D > logs/plan.log 2>&1 || { status "FAIL plan"; exit 1; }
status "plan: $(tail -n 1 logs/plan.log | cut -c1-300)"
reg "data audit PASS; launching Kaggle (rsn-big-train)"
exec bash $BIG/launch_big.sh auto
