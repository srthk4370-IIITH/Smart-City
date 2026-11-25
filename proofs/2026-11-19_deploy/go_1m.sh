#!/bin/bash
# owner 2026-11-20: polish pass -> APK phase1m + voice files (whisper tiny.en) on the board
source <(sed -n '11,36p' /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-16_phase1/deploy_phase1.sh)
L=~/detached; Q=/mnt/c/Users/hp/Desktop/qidk/proofs; st(){ echo "$(date -Is) $*" >> $L/go_1m.log; echo "- go_1m $* $(date -Is)" >> $Q/AGENT_REGISTRY.md; }
st "1 build phase1m"; r=$(TAG=phase1m nice -n 15 bash $Q/2026-11-16_phase1/build_phase1.sh | tail -1); st "$r"; echo "$r" | grep -q "done ok" || { st "build FAILED"; exit 1; }
st "2 voice files"; stop_app >/dev/null; V=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage/voice; D=/data/local/tmp/smart_city_edge/voice
sh_ "mkdir -p $D"
for f in whisper-cli ggml-tiny.en.bin; do w=$(md5sum $V/$f | cut -d' ' -f1); "$A" push "$(wslpath -w $V/$f)" $D/$f.part >/dev/null; g=$(sh_ "md5sum $D/$f.part" | tr -d '\r' | cut -d' ' -f1); [ "$w" = "$g" ] && sh_ "mv $D/$f.part $D/$f" || { st "voice md5 mismatch $f"; }; done
sh_ "chmod 755 $D/whisper-cli; ls -la $D" >> $L/go_1m.log
st "3 APK phase1m"; bash $Q/2026-11-16_phase1/deploy_1m.sh >> $L/deploy_1m.log 2>&1; st "apk rc=$? $(grep -E 'DEPLOY1M_DONE|ABORT|NOT up' $L/deploy_1m.log | tail -1)"
st "DONE"
