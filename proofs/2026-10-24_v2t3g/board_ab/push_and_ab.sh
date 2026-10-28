#!/usr/bin/env bash
# push mixA50 (.part + md5 + mv, app stopped, one NPU client), then app A/B v2 vs mixA50 (both post_rules=all)
set -uo pipefail
export MSYS_NO_PATHCONV=1
A=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; G=/data/local/tmp/gpu/ft_mixA50_q4_0.gguf
echo "=== $(date '+%T') stop app + htpd"
$A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; for i in $(seq 1 80); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; sleep 10; true'
echo "=== $(date '+%T') push"
$A push C:/Users/hp/Desktop/qidk/Code/models_stage/ft_mixA50_q4_0.gguf $G.part | tail -1
R=$($A shell "md5sum $G.part" | cut -c1-32)
[ "$R" = "8397bb0e8a58005cf339999fa6634ad3" ] || { echo "MD5 MISMATCH $R"; $A shell "rm -f $G.part"; exit 1; }
$A shell "mv -f $G.part $G && echo 8397bb0e8a58005cf339999fa6634ad3 > $G.md5 && ls -la $G"
echo "=== $(date '+%T') A/B"
bash app_ab.sh
