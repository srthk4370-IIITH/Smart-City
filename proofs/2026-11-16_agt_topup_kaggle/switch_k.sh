# owner 2026-11-16: board agent -> Kaggle top-up winner s0300 (real val .808); campus_url failover kept
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
AG=$HOME/smartcity_runs/agt_topup_k/post/s0300/agt3_s0300_q4_0.gguf; RG=/data/local/tmp/gpu
st "switch_agt3: stop app"; stop_app | tail -1
sh_ "cp $W/htpd_profile $W/htpd_profile.before_agt3"
push_md5 $AG $RG agt3_k_q4_0.gguf || { st "ABORT: agent model push failed"; start_app; exit 1; }
sh_ "sed -e 's#^model=.*#model=$RG/agt3_k_q4_0.gguf#' -e 's#^agents=.*#agents=agt_v3#' -e 's#HTPD_AGENT_MAX_NEW=160#HTPD_AGENT_MAX_NEW=240#' $W/htpd_profile > $W/htpd_profile.part && (grep -q '^agent_ctx=' $W/htpd_profile.part || echo agent_ctx=1280 >> $W/htpd_profile.part) && mv $W/htpd_profile.part $W/htpd_profile"
sh_ "grep -E '^(model|agents|campus_url|agent_ctx)=|AGENT_MAX_NEW' $W/htpd_profile | cut -c1-90"
st "switch_agt3: start app"
if ! start_app; then st "ROLLBACK: htpd not ready with agt_v3"; stop_app >/dev/null; sh_ "cp $W/htpd_profile.before_agt3 $W/htpd_profile"; sh_ "sed -i 's#^campus_url=.*#campus_url=http://10.2.203.214:9999,http://127.0.0.1:9999#' $W/htpd_profile"; start_app; exit 2; fi
sleep 240
st "switch_agt3: status $(sh_ "curl -s -m 20 http://127.0.0.1:18000/api/prod/status" | head -c 400)"
st "switch_agt3: htpd errors: $(sh_ "grep -ciE 'error|failed|abort' $W/state/htpd.log")  $(tele)"
echo SWITCH_DONE
