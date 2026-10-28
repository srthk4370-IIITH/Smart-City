#!/usr/bin/env bash
# QIDK side of the v2 device eval (Git Bash on Windows; QIDK on USB). Same launch pattern as
# proofs/2026-10-16_htpd_ab/ab.sh and the app's htpdclient.go env, with the v2 GGUF.
#   bash htpd_v2.sh push  [local.gguf]   # -> /data/local/tmp/gpu/ft_v2_q4_0.gguf.part, md5 checked, then mv (no /sdcard: FUSE copies rebooted the board)
#   bash htpd_v2.sh start [model] [agents] [agent_ctx]   # stops the app + NPU daemons, starts htpd v2, forwards 8091
#   bash htpd_v2.sh stop                 # stops htpd, relaunches the app (it restarts its own backend/model)
# One model on the NPU at a time (two rebooted the board, HANDBOOK 2.27/2.37). v2 prompts are longer (12 h HVAC
# ~1.2k tokens + answer): agent streams get 1408 tokens (app today 768); batch 8 keeps KV memory about the same
# as 13 x 768. The v1 model file /data/local/tmp/gpu/ft_device_q4exact.gguf is never touched.
set -euo pipefail
export MSYS_NO_PATHCONV=1
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
DEV=/data/local/tmp/gpu/ft_v2_q4_0.gguf
cmd="${1:-status}"
[ "$("$ADB" get-state 2>/dev/null)" = device ] || { echo "QIDK not connected"; exit 1; }

case "$cmd" in
push)
  SRC="${2:-//wsl.localhost/Ubuntu/home/hp_srthk4370/smartcity_runs/agents_v2/post/gguf/ft_v2_q4_0.gguf}"
  L=$(md5sum "$SRC" | cut -d' ' -f1)
  R=$("$ADB" shell "md5sum $DEV 2>/dev/null" | cut -d' ' -f1 || true)
  if [ "$L" = "$R" ]; then echo "already on device ($L)"; exit 0; fi
  # no /sdcard staging (multi-GB FUSE copies stalled system_server -> watchdog reboot, 2026-10-22);
  # the .part name keeps a failed push from touching the target
  "$ADB" shell 'am force-stop com.iiith.smartcityedge; pkill -x htpd; pkill -x htpd_v7; pkill -x edge-agent; true'
  "$ADB" push "$SRC" "$DEV.part" || exit 1
  [ "$("$ADB" shell md5sum "$DEV.part" | cut -d' ' -f1)" = "$L" ] || { echo "md5 mismatch on $DEV.part"; exit 1; }
  "$ADB" shell "mv -f $DEV.part $DEV" || exit 1
  echo "pushed, md5 $L"
  ;;
start)
  M="${2:-$DEV}"; A="${3:-8}"; C="${4:-1408}"
  "$ADB" shell am force-stop com.iiith.smartcityedge
  # stop EVERY NPU client (htpd, htpd_v7, ..., genied) and wait until they have exited + 10 s for the DSP to
  # release the session: a second NPU client while one is still alive/shutting down reboots the board
  "$ADB" shell 'pkill -x edge-agent; pkill -TERM -f "[b]in/htpd"; pkill -x genied; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || pgrep -x genied >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; for i in $(seq 1 80); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; sleep 10; pgrep -fl htpd; true'
  "$ADB" shell "cd /data/local/tmp/llama.cpp; (LD_LIBRARY_PATH=./lib ADSP_LIBRARY_PATH=./lib GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 HTPD_LEGACY_PREFILL=1 GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_DRAFT=1 HTPD_DRAFT_K=${DRAFT_K:-4} HTPD_PREFIX_CACHE=1 setsid nohup ./bin/htpd -m $M --agents $A --agent-ctx $C --synth-ctx 2048 --ubatch 512 --ubatch-synth 512 --port 8091 > /data/local/tmp/htpd_v2.log 2>&1 < /dev/null &); for i in \$(seq 1 90); do grep -q 'htpd: ready' /data/local/tmp/htpd_v2.log && break; sleep 2; done; p=\$(pidof htpd); echo 1000 > /proc/\$p/oom_score_adj 2>/dev/null; echo htpd pid \$p; tail -3 /data/local/tmp/htpd_v2.log"
  "$ADB" forward tcp:8091 tcp:8091 >/dev/null
  ;;
stop)
  "$ADB" shell 'pkill -TERM -f "[b]in/htpd"; for i in $(seq 1 120); do pgrep -f "[b]in/htpd" >/dev/null || break; sleep 0.5; done; pkill -KILL -f "[b]in/htpd"; sleep 10; true'
  "$ADB" forward --remove tcp:8091 2>/dev/null || true
  "$ADB" shell 'monkey -p com.iiith.smartcityedge -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; true'
  echo "htpd v2 stopped; app relaunched"
  ;;
*)
  "$ADB" shell 'pidof htpd edge-agent genied; ls -la /data/local/tmp/gpu/; tail -3 /data/local/tmp/htpd_v2.log 2>/dev/null; true'
  ;;
esac
