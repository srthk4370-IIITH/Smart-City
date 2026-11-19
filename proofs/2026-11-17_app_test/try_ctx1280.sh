# diagnosis 2: s0300 + agent_ctx 1280 (agt_v2 default) - does the fastrpc_mmap crash go?
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
st "try: files $(sh_ 'ls -la /data/local/tmp/gpu/ | grep -E "agt3|rsn" | tr -s " " | cut -d" " -f5,8 | tr "\n" ";"')"
stop_app | tail -1
sh_ "cp $W/htpd_profile.s0300 $W/htpd_profile && sed -i 's#^agent_ctx=.*#agent_ctx=1280#' $W/htpd_profile && grep -E '^(model|agent_ctx)=' $W/htpd_profile"
start_app && st "try: app up (s0300 ctx1280)"
sleep 600
st "try: $(sh_ "grep -E 'htpd: (started|ready)|NPU crashed|agent done' $W/state/agent.log | tail -5 | cut -c1-110 | tr '\n' '|'")"
st "try: mmap fails: $(sh_ "grep -c 'mmap failed' $W/state/htpd.log")"
echo TRY_DONE
