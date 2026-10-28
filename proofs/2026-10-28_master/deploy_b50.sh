#!/usr/bin/env bash
# Deploy B50 as the agents' model (owner 2026-10-28: best blend now). Safe pattern: app stopped, .part + md5 + mv, never reboot.
# Rollback: sed model= back to /data/local/tmp/gpu/ft_mixA50_q4_0.gguf + clean restart.
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; G=/data/local/tmp/gpu/ft_B50_q4_0.gguf
SRC='C:\Users\hp\Desktop\qidk\Code\models_stage\ft_B50_q4_0.gguf'; MD5=bfdca67bd2cc582577c48e6728d9fc76
L=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/deploy_b50.log; log(){ echo "$(date +%T) $*" | tee -a $L; }
stop(){ $A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do ps -A -o NAME= | grep -qE "^htpd" || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; sleep 30; ps -A -o NAME= | grep -E "^(htpd|edge)" || echo STOPPED'; }
log "stop"; stop | tee -a $L
log "push"; $A push "$SRC" $G.part >> $L 2>&1 || { log "push failed"; exit 1; }
R=$($A shell "md5sum $G.part" | cut -c1-32); [ "$R" = "$MD5" ] || { log "md5 mismatch $R"; exit 1; }
$A shell "mv -f $G.part $G && echo $MD5 > $G.md5"
$A shell "cp $W/htpd_profile $W/htpd_profile.bak_preB50; sed -i 's|^model=.*|model=$G|' $W/htpd_profile; grep -q '^model=' $W/htpd_profile || echo model=$G >> $W/htpd_profile; grep model= $W/htpd_profile" | tee -a $L
log "start app"; $A shell 'monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1'
for i in $(seq 1 30); do sleep 5; $A shell 'cat /proc/$(pidof htpd_v8x2 htpd_v8r 2>/dev/null | cut -d" " -f1)/cmdline 2>/dev/null | tr "\0" " "' | grep -q B50 && break; done
$A shell 'for p in $(pidof htpd_v8x2 htpd_v8r); do cat /proc/$p/cmdline | tr "\0" " " | cut -c1-120; echo; done' | tee -a $L
log "done"
