#!/bin/bash
# owner 2026-11-20: phase1n = phase1m + fog sync; profile gets supabase_url/key (publishable key, never printed)
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1n.log; echo "- go_1n $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1n"; r=$(TAG=phase1n nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 profile fog keys"; stop_app >/dev/null; . $Q/secrets/supabase.env
P=/data/local/tmp/smart_city_edge/htpd_profile
sh_ "cp $P $P.bak_1n; grep -v '^supabase_\|^app_version=' $P > $P.part; echo supabase_url=$SUPABASE_URL >> $P.part; echo supabase_key=$SUPABASE_ANON_KEY >> $P.part; echo app_version=phase1n >> $P.part; mv $P.part $P" >/dev/null
st "profile keys: $(sh_ "grep -c '^supabase_' $P" | tr -d '\r')"
st "3 APK phase1n"; bash $Q/2026-11-16_phase1/deploy_1n.sh >> $L/deploy_1n.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1N_DONE|ABORT|NOT up' $L/deploy_1n.log | tail -1)"
st "DONE"
