#!/bin/bash
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1q.log; echo "- go_1q $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1q"; r=$(TAG=phase1q nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 profile"; stop_app >/dev/null; P=/data/local/tmp/smart_city_edge/htpd_profile
sh_ "grep -v '^qr_viewer=\|^app_version=' $P > $P.part; echo qr_viewer=https://smart-city-esw.pages.dev/report/ >> $P.part; echo app_version=phase1q >> $P.part; mv $P.part $P" >/dev/null
st "3 APK phase1q"; bash $Q/2026-11-16_phase1/deploy_1q.sh >> $L/deploy_1q.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1Q_DONE|ABORT|NOT up' $L/deploy_1q.log | tail -1)"
st "DONE"
