# diagnosis: does the fastrpc_mmap crash follow the s0300 GGUF? temporary model=s0075, then report
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
st "try: files $(sh_ 'ls -la /data/local/tmp/gpu/ | grep -E "agt3|rsn" | tr -s " " | cut -d" " -f5,8 | tr "\n" ";"')"
stop_app | tail -1
sh_ "cp $W/htpd_profile $W/htpd_profile.s0300 && sed -i 's#^model=.*#model=/data/local/tmp/gpu/agt3_s0075_q4_0.gguf#' $W/htpd_profile && grep ^model= $W/htpd_profile"
start_app && st "try: app up (s0075)"
sleep 600
st "try: $(sh_ "grep -E 'htpd: (started|ready)|NPU crashed|agent done' $W/state/agent.log | tail -5 | cut -c1-110 | tr '\n' '|'")"
st "try: mmap fails: $(sh_ "grep -c 'mmap failed' $W/state/htpd.log")"
echo TRY_DONE
