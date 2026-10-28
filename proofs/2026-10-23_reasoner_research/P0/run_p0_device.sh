#!/usr/bin/env bash
# P0 device spike: htpd v8 with a LoRA adapter on the synthesizer context only (QIDK, Hexagon backend).
# NOT RUN YET (written 2026-10-22 while the board was busy). Run from Git Bash on the laptop, board on USB:
#   bash proofs/2026-10-23_reasoner_research/P0/run_p0_device.sh          # full run (~25-35 min incl. cooling)
#   bash .../run_p0_device.sh push                                         # only stop app + push + verify files
#   bash .../run_p0_device.sh restore                                      # only stop daemons + relaunch the app
#
# Safety (HANDBOOK 2.37/2.43, memory "QIDK safety"):
#  - the app is force-stopped first; EVERY htpd* / genied / edge-agent is stopped and waited for (SIGTERM, then
#    SIGKILL after 20 s), then +10 s for the DSP to release the session, before any daemon starts;
#  - exactly ONE NPU client at a time: v7 baseline, stop+wait, then v8; never two daemons;
#  - pushes go to *.part, md5 checked on the board (small files only: 2 MB binary, 49 MB adapter), then mv;
#    the 2.8 GB model is NOT touched (only its presence is checked; no on-board md5 of big files);
#  - the device binary is named htpd_v8lora, NOT htpd_v8 (that name belongs to the latency-ladder patch,
#    proofs/2026-10-21_latency_ladder/patches/htpd_v8.patch, and run_ladder.sh pkills it); the app's
#    htpd_profile is never edited; htpd_v7 is never overwritten;
#  - NSP must be < 50 C before each phase; a phase aborts above 90 C;
#  - on exit (also on error / Ctrl-C) all test daemons are stopped and waited for, then the app is relaunched on
#    its normal profile and watched until its own htpd_v7 is up.
set -uo pipefail
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
HERE=$(cd "$(dirname "$0")" && pwd)
ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
PKG=com.iiith.smartcityedge
D=/data/local/tmp/llama.cpp
MODEL=/data/local/tmp/gpu/ft_v2_q4_0.gguf
BIN_LOCAL=/c/Users/hp/gpu_work/htpd_v8/bin/htpd
BIN_DEV=$D/bin/htpd_v8lora
LORA_LOCAL=/c/Users/hp/gpu_work/htpd_v8/adapters/lora_delta3d50_r16_f16.gguf
LORA_DEV=/data/local/tmp/gpu/lora_delta3d50_r16_f16.gguf
LOGD=/data/local/tmp/p0_lora
RES=$HERE/results/$(date +%Y%m%d_%H%M%S)
OUT=$RES/device.jsonl
# the app's htpd environment (htpdclient.go) + the live profile env (HANDBOOK 2.43: L7)
BASEENV="GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 HTPD_LEGACY_PREFILL=1 GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_DRAFT=1 HTPD_DRAFT_K=8 HTPD_PREFIX_CACHE=1"
PROFENV="HTPD_AGENT_MAX_NEW=160 HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1"
ARGS="-m $MODEL --agents 10 --agent-ctx 1280 --synth-ctx 4096 --ubatch 512 --ubatch-synth 512 --port 8091"
PY="py -3"

a() { "$ADB" "$@"; }
sh_() { "$ADB" shell "$@" | tr -d '\r'; }
log() { echo "=== $(date +%T) $*" | tee -a "$RES/run.log"; }
nsp() { sh_ 'for z in /sys/class/thermal/thermal_zone*; do case $(cat $z/type 2>/dev/null) in nsp*) cat $z/temp;; esac; done' | sort -n | tail -1; }
state() {  # board snapshot into run.log
  { echo "--- $1 $(date +%T)"; sh_ "cat /proc/uptime; grep -E 'MemAvailable|MemFree' /proc/meminfo; pidof edge-agent htpd htpd_v7 htpd_v8 htpd_v8lora genied; echo nsp=\$(for z in /sys/class/thermal/thermal_zone*; do case \$(cat \$z/type 2>/dev/null) in nsp*) cat \$z/temp;; esac; done | sort -n | tail -1)"; } >> "$RES/run.log" 2>&1
}
cool() {
  for i in $(seq 1 90); do
    t=$(nsp)
    if [ -z "$t" ] || [ "$t" -lt 15000 ]; then log "NSP read failed ('$t'): fixed 180 s wait"; sleep 180; return; fi
    [ "$t" -lt 50000 ] && { log "nsp $t"; return; }
    sleep 10
  done
  log "still hot ($t) after 15 min - continuing is NOT advised"; return 1
}
# stop every NPU client and wait until they are gone, +10 s (same as htpdKill in the backend)
stop_all() {
  sh_ "am force-stop $PKG; pkill -x edge-agent; pkill -x genied; for p in htpd htpd_v7 htpd_v8 htpd_v8lora; do pkill -TERM -x \$p; done; true"
  for i in $(seq 1 80); do
    left=$(sh_ 'pidof htpd htpd_v7 htpd_v8 htpd_v8lora genied edge-agent')
    [ -z "$left" ] && break; sleep 0.25
  done
  if [ -n "$(sh_ 'pidof htpd htpd_v7 htpd_v8 htpd_v8lora genied')" ]; then
    log "SIGKILL after 20 s: $(sh_ 'pidof htpd htpd_v7 htpd_v8 htpd_v8lora genied')"
    sh_ 'for p in htpd htpd_v7 htpd_v8 htpd_v8lora genied; do pkill -KILL -x $p; done; true'
    for i in $(seq 1 160); do [ -z "$(sh_ 'pidof htpd htpd_v7 htpd_v8 htpd_v8lora genied')" ] && break; sleep 0.25; done
  fi
  left=$(sh_ 'pidof htpd htpd_v7 htpd_v8 htpd_v8lora genied')
  [ -n "$left" ] && { log "ABORT: NPU clients still present: $left"; return 1; }
  a forward --remove tcp:8091 >/dev/null 2>&1
  sleep 10
  log "all NPU clients stopped (+10 s)"
}
# start ONE daemon: start_daemon TAG BIN "EXTRA ARGS"
start_daemon() {
  local tag=$1 bin=$2 extra=$3
  [ -n "$(sh_ 'pidof htpd htpd_v7 htpd_v8 htpd_v8lora genied')" ] && { log "ABORT: an NPU client is running"; return 1; }
  cool || return 1
  sh_ "mkdir -p $LOGD; date +'%m-%d %H:%M:%S.000' > $LOGD/t0_$tag"
  log "start $tag: $bin $extra"
  sh_ "cd $D; (LD_LIBRARY_PATH=./lib ADSP_LIBRARY_PATH=./lib $BASEENV $PROFENV setsid nohup $bin $ARGS $extra > $LOGD/htpd_$tag.log 2>&1 < /dev/null &); for i in \$(seq 1 150); do grep -q 'htpd: ready' $LOGD/htpd_$tag.log && break; pidof $(basename $bin) >/dev/null || break; sleep 2; done; tail -3 $LOGD/htpd_$tag.log"
  if ! sh_ "grep -q 'htpd: ready' $LOGD/htpd_$tag.log"; then log "ABORT: $tag did not come up"; a pull $LOGD/htpd_$tag.log "$RES/" >/dev/null 2>&1; return 1; fi
  a forward tcp:8091 tcp:8091 >/dev/null
  mem "$tag" ready
}
mem() {  # resident memory of the daemon + MemAvailable
  local pid; pid=$(sh_ "pidof htpd_v7 htpd_v8lora | cut -d' ' -f1")
  echo "{\"tag\":\"$1\",\"when\":\"$2\",\"status\":\"$(sh_ "grep -E 'VmRSS|VmHWM' /proc/$pid/status | tr -s ' \t' ' ' | tr '\n' ';'")\",\"meminfo\":\"$(sh_ "grep -E 'MemAvailable' /proc/meminfo | tr -s ' '")\",\"nsp\":\"$(nsp)\"}" >> "$RES/mem.jsonl"
}
req() {  # req TAG name,name,...   (aborts the phase if the daemon dies or NSP > 90 C)
  local tag=$1
  for n in $(echo "$2" | tr ',' ' '); do
    t=$(nsp); if [ -n "$t" ] && [ "$t" -gt 90000 ]; then log "NSP $t > 90 C: phase $tag stopped"; return 1; fi
    $PY "$HERE/p0_client.py" --tag "$tag" --names "$n" --out "$OUT" | tee -a "$RES/run.log" || return 1
  done
}
evidence() {  # log lines that decide the spike: adapter load, LoRA buffers, buft fallback, graph splits, fastrpc
  local tag=$1
  a pull $LOGD/htpd_$tag.log "$RES/" >/dev/null 2>&1
  { echo "--- evidence $tag"
    grep -E "v8 LoRA|LoRA buffer|lora_adapter|cannot use buft|fallback to CPU|graph splits|splits =|fastrpc|remote_handle|error|failed|ready in|v7 flags" "$RES/htpd_$tag.log" | grep -v llama_graph_n_input | sort | uniq -c | head -40
    t0=$(sh_ "cat $LOGD/t0_$tag")
    echo "--- logcat since $t0 (fastrpc / adsprpc / cdsp / ssr)"
    sh_ "logcat -d -T '$t0' 2>/dev/null" | grep -iE "fastrpc|adsprpc|cdsp|subsys|ssr|remoteproc" | tail -40
  } >> "$RES/evidence_$tag.txt" 2>&1
  grep -ciE "fastrpc.*(err|fail)|remote_handle.*fail" "$RES/htpd_$tag.log" | xargs -I{} log "$tag: fastrpc error lines in htpd log: {}"
}

restore() {
  log "restore: stop test daemons, relaunch the app on its normal profile"
  stop_all
  sh_ "cat /data/local/tmp/smart_city_edge/htpd_profile 2>/dev/null" >> "$RES/run.log"
  sh_ "monkey -p $PKG -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; true"
  for k in $(seq 1 20); do
    sleep 15
    p=$(sh_ 'pidof edge-agent htpd_v7 htpd')
    echo "$(date +%T) $p nsp=$(nsp)" >> "$RES/run.log"
    sh_ 'pidof htpd_v7 htpd' | grep -q . && { log "app htpd up: $(sh_ 'cat /proc/$(pidof htpd_v7 htpd | cut -d" " -f1)/cmdline | tr "\0" " " | cut -c1-140')"; break; }
  done
  state after_restore
}

push_verify() {  # push_verify LOCAL DEV   (.part + md5 on board + mv; skipped when already in place)
  local l=$1 d=$2 m
  m=$(md5sum "$l" | cut -d' ' -f1)
  if [ "$(sh_ "md5sum $d 2>/dev/null | cut -d' ' -f1")" = "$m" ]; then log "already on board: $d ($m)"; return 0; fi
  a push "$l" "$d.part" >/dev/null || { log "push failed: $l"; return 1; }
  if [ "$(sh_ "md5sum $d.part | cut -d' ' -f1")" != "$m" ]; then log "md5 mismatch on board for $d.part"; sh_ "rm -f $d.part"; return 1; fi
  sh_ "mv -f $d.part $d; chmod 755 $d 2>/dev/null; true"
  log "pushed $d ($m)"
}
preflight() {
  mkdir -p "$RES"
  [ "$(a get-state 2>/dev/null)" = device ] || { echo "QIDK not connected"; exit 1; }
  log "P0 LoRA spike, results in $RES"
  md5sum "$BIN_LOCAL" "$LORA_LOCAL" | tee -a "$RES/run.log"
  state before
  # v8 links against the same libllama/libggml* as v7 (build_htpd.sh copies build-snapdragon/bin): check the board has them
  for l in libllama.so libggml-hexagon.so libggml-base.so libggml-cpu.so libggml.so; do
    want=$(md5sum "/c/Users/hp/gpu_work/htpd_v8/bin/$l" | cut -d' ' -f1); have=$(sh_ "md5sum $D/lib/$l | cut -d' ' -f1")
    [ "$want" = "$have" ] || { log "ABORT: board $D/lib/$l md5 $have != build $want"; exit 1; }
  done
  sh_ "ls -l $MODEL $D/bin/htpd_v7" >> "$RES/run.log" || { log "ABORT: model or htpd_v7 missing"; exit 1; }
}

STOPPED=0
on_exit() { [ "$STOPPED" = 1 ] && restore; }
trap on_exit EXIT

case "${1:-run}" in
restore) mkdir -p "$RES"; restore; exit 0 ;;
push)
  preflight; STOPPED=1; stop_all || exit 1
  push_verify "$BIN_LOCAL" "$BIN_DEV" && push_verify "$LORA_LOCAL" "$LORA_DEV"; exit $? ;;
run) ;;
*) sed -n 2,6p "$0"; exit 1 ;;
esac

preflight
STOPPED=1
stop_all || exit 1
push_verify "$BIN_LOCAL" "$BIN_DEV" || exit 1
push_verify "$LORA_LOCAL" "$LORA_DEV" || exit 1
AG=agents0,agents1,agents2,agents10

# ---- phase 1: v7 baseline (the live binary, unchanged), twice for the run-to-run floor
if start_daemon v7 ./bin/htpd_v7 ""; then
  req v7_r1 "$AG,synth0,synth1,synth2" && req v7_r2 "$AG,synth0"
  mem v7 after; evidence v7
fi
stop_all || exit 1

# ---- phase 2: v8 + adapter on the synth context (one daemon). Order: agents first (adapter loaded, never attached),
# then off/on pairs (same process, interleaved), then agents again after adapter use, then a streamed synth.
if start_daemon v8lora ./bin/htpd_v8lora "--lora-synth $LORA_DEV"; then
  req v8lora "$AG" &&
  req v8lora "synth0_off,synth0_on,synth1_on,synth1_off,synth2_off,synth2_on,synth0_on" &&
  req v8lora "agents0" &&
  req v8lora "synth0_off,synth0_stream_on"
  mem v8lora after; evidence v8lora
fi
stop_all || exit 1
state after_tests

$PY "$HERE/compare_p0.py" --dir "$RES" | tee "$RES/summary.txt"
# trap: restore() relaunches the app on its normal profile (htpd_v7, untouched)
