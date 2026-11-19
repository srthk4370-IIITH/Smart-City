# owner 2026-11-17 night: htpd fastrpc_mmap crash cascade -> stop app, NPU idle 5 min, start, check first agent batch
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
pkill -f run_waves.sh
st "npu_rest: stop app"; stop_app | tail -1
st "npu_rest: htpd procs after stop: $(sh_ 'ps -A | grep -c htpd')"; sleep 300
start_app && st "npu_rest: app up" || st "npu_rest: app NOT up"
sleep 600
st "npu_rest: $(sh_ "grep -E 'htpd: (started|ready)|NPU crashed' $W/state/agent.log | tail -4 | tr '\n' '|'")"
st "npu_rest: mmap fails in current htpd.log: $(sh_ "grep -c 'mmap failed' $W/state/htpd.log")"
echo NPU_REST_DONE
