#!/bin/bash
# owner 2026-11-20: fog path order: Wi-Fi internet (supabase_url) -> laptop relay (supabase_relay) -> on-disk queue
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1o.log; echo "- go_1o $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1o"; r=$(TAG=phase1o nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 profile"; stop_app >/dev/null; . $Q/secrets/supabase.env
P=/data/local/tmp/smart_city_edge/htpd_profile
sh_ "grep -v '^supabase_url=\|^supabase_relay=\|^app_version=' $P > $P.part; echo supabase_url=$SUPABASE_URL >> $P.part; echo supabase_relay=http://127.0.0.1:8095 >> $P.part; echo app_version=phase1o >> $P.part; mv $P.part $P" >/dev/null
st "3 APK phase1o"; bash $Q/2026-11-16_phase1/deploy_1o.sh >> $L/deploy_1o.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1O_DONE|ABORT|NOT up' $L/deploy_1o.log | tail -1)"
st "DONE"
