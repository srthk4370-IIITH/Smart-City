#!/usr/bin/env bash
# q2b job (2026-10-30): does Qwen3.5-2B (BASE, Q4_0) run on the QIDK NPU through htpd_v8x5, and how fast vs the 4B reasoner?
# Speed + execution correctness only; accuracy is NOT measured. Never deploys, never touches live libs, never uses the laptop GPU.
# Launch (PowerShell): wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh q2b /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/q2b/q2b_job.sh
# Log ~/detached/q2b.log; progress -> q2b/STATUS.md; result -> q2b/VERDICT.md. Stop: touch q2b/STOP
# Steps (markers ~/q2bjob/done.<step>; re-running resumes):
#  1 download Qwen/Qwen3.5-2B to ~/models/qwen3.5-2b (same path laptop_chain.sh uses) -> bf16 GGUF (CPU) -> Q4_0 (merge_q4.sh flags, no imatrix) + md5
#  2 board: wait until free (app up, no BOARD_LOCK < 3 h, no DEMO_NOW, no deploy/lab/ndk29 job), take BOARD_LOCK q2b, stop the app,
#    push /data/local/tmp/gpu/q2b_base_q4_0.gguf (.part + md5 + mv; board free >= 3 GB)
#  3 ONE lab window q2b_ab (lab_run.sh via Git Bash): 4b = htpd_v8x5 + qwen35_reasoner_q4_0.gguf, 2b = htpd_v8x5 + q2b_base_q4_0.gguf, REQS 10 10 11 12 13 14 15
#  4 VERDICT.md; release BOARD_LOCK; app running at the end (am start if not)
set -u
export CUDA_VISIBLE_DEVICES=""
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; J=$P/q2b; ST=$J/STATUS.md; STOP=$J/STOP
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; K=$M/BOARD_LOCK
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; GB="/mnt/c/Program Files/Git/bin/bash.exe"
LC=$HOME/gpu_work/llama.cpp; M2=$HOME/models/qwen3.5-2b; E=$HOME/q2bjob/gguf; S=$HOME/q2bjob; mkdir -p $S $E $J
MS=/mnt/c/Users/hp/Desktop/qidk/Code/models_stage; NAME=q2b_base_q4_0.gguf; BG=/data/local/tmp/gpu; WIN=q2b_ab; W=/data/local/tmp/smart_city_edge

log() { echo "$(date '+%F %T') $*"; }
st() { log "STATUS: $*"; echo "- $(date '+%m-%d %H:%M') q2b: $*" >> $ST; }
HAVE_LOCK=0
unlock() { if [ $HAVE_LOCK = 1 ] && [ "$(cat $K 2>/dev/null)" = q2b ]; then rm -f $K; HAVE_LOCK=0; log "BOARD_LOCK released"; fi; true; }
sh_() { "$A" shell "$@" | tr -d '\r'; }
app_up() { local ps; ps=$(sh_ "ps -A -o NAME="); echo "$ps" | grep -q "^edge-agent" && echo "$ps" | grep -q "^htpd"; }
ensure_app() {  # app must be running whenever this job leaves the board
  [ $HAVE_LOCK = 1 ] || return 0
  app_up && return 0
  sh_ "ps -A -o NAME=,ARGS=" | grep -q "lab_ab.sh" && return 0  # board lab script restarts the app itself
  log "app not running: am start"; sh_ "am start -n com.iiith.smartcityedge/.MainActivity" > /dev/null
  for i in $(seq 1 24); do sleep 5; app_up && { log "app back"; return 0; }; done; log "WARNING: app still not up after am start"
}
die() { st "STOPPED: $*"; ensure_app; unlock; exit 1; }
trap 'ensure_app; unlock' EXIT
stopchk() { [ -e $STOP ] && die "STOP file present"; true; }
freeram_mb() { powershell.exe -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" < /dev/null 2>/dev/null | tr -d '\r '; }
ramguard() {  # Windows free RAM >= 1.0 GB (waits up to 2 h)
  local i=0 r
  while :; do stopchk; r=$(freeram_mb); [ -n "$r" ] && [ "$r" -ge 1024 ] && return 0
    [ $i -eq 0 ] && st "waiting: Windows free RAM ${r:-?} MB < 1024"; i=$((i+1)); [ $i -gt 120 ] && die "Windows RAM low for 2 h"; sleep 60; done
}
diskguard() { local f; f=$(df -Pm $HOME | awk 'NR==2 {print $4}'); [ "$f" -ge ${1:-15000} ] || die "WSL disk free ${f} MB < ${1:-15000} MB"
  f=$(df -Pm /mnt/c | awk 'NR==2 {print $4}'); [ "$f" -ge 1024 ] || die "C: free ${f} MB < 1 GB"; }
done_() { touch $S/done.$1; }
isdone() { [ -e $S/done.$1 ]; }

st "job start (pid $$, log ~/detached/q2b.log)"
stopchk

# ---------- 1. download + convert + quantize (CPU only) ----------
if ! isdone dl; then
  if [ ! -s $M2/config.json ]; then
    # laptop_chain.sh downloads to the same $M2.part: if it is being written right now, wait for it instead of racing
    for i in $(seq 1 120); do [ -d $M2.part ] && [ -n "$(find $M2.part -newermt '-5 minutes' -print -quit 2>/dev/null)" ] || break
      [ $i = 1 ] && st "another download is writing $M2.part: waiting"; [ -s $M2/config.json ] && break; sleep 60; done
  fi
  if [ ! -s $M2/config.json ]; then
    diskguard 15000; ramguard; st "step 1: downloading Qwen/Qwen3.5-2B -> $M2"
    nice -n 15 ~/venvs/rsn/bin/python -c "from huggingface_hub import snapshot_download as s; s('Qwen/Qwen3.5-2B', local_dir='$M2.part')" \
      > $S/download.log 2>&1 && [ -s $M2.part/config.json ] && mv $M2.part $M2 || die "download failed (see ~/q2bjob/download.log; re-run resumes)"
    (cd $M2 && sha256sum *.safetensors *.json *.jinja > SHA256SUMS 2>/dev/null)
  fi
  st "2B weights at $M2 ($(du -sh $M2 | cut -f1))"
  done_ dl
fi
if ! isdone q4; then
  stopchk; diskguard 12000; ramguard
  if [ ! -s $E/bf16.gguf ]; then
    st "step 1: convert to bf16 GGUF (CPU)"
    PYTHONPATH=$LC/gguf-py OMP_NUM_THREADS=4 nice -n 15 ~/venvs/train/bin/python $LC/convert_hf_to_gguf.py $M2 --outtype bf16 --outfile $E/bf16.gguf.part \
      > $E/convert.log 2>&1 || die "convert failed: $(tail -2 $E/convert.log | tr '\n' ' ')"
    mv $E/bf16.gguf.part $E/bf16.gguf
  fi
  stopchk; ramguard; st "step 1: quantize Q4_0 (llama-quantize ... Q4_0 4, no imatrix)"
  nice -n 15 $LC/build-host/bin/llama-quantize $E/bf16.gguf $E/$NAME.part Q4_0 4 > $E/quant.log 2>&1 || die "quantize failed: $(tail -2 $E/quant.log | tr '\n' ' ')"
  mv $E/$NAME.part $E/$NAME; rm -f $E/bf16.gguf
  (cd $E && md5sum $NAME > $NAME.md5); cp $E/$NAME.md5 $E/convert.log $E/quant.log $J/ 2>/dev/null
  st "Q4_0 ready: $(ls -la $E/$NAME | awk '{print $5}') bytes, md5 $(cut -c1-32 $E/$NAME.md5)"
  done_ q4
fi
MD5=$(cut -c1-32 $E/$NAME.md5)
if [ "$(md5sum $MS/$NAME 2>/dev/null | cut -c1-32)" != "$MD5" ]; then  # adb.exe pushes from C:, not from the WSL disk
  mkdir -p $MS; cp $E/$NAME $MS/$NAME.part && mv $MS/$NAME.part $MS/$NAME && cp $E/$NAME.md5 $MS/ || die "models_stage copy failed"
  [ "$(md5sum $MS/$NAME | cut -c1-32)" = "$MD5" ] || die "models_stage md5 mismatch"
fi

# ---------- 2. wait for the board, lock, push ----------
board_free() {
  [ -e $P/DEMO_NOW ] && { echo "DEMO_NOW"; return 1; }
  if [ -e $K ] && [ "$(cat $K 2>/dev/null)" != q2b ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; then echo "BOARD_LOCK ($(cat $K))"; return 1; fi
  local wp; wp=$(powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | % { \$_.CommandLine } | Select-String -Pattern 'deplo[y][0-9a-z_]*\.sh|la[b]_run\.sh|la[b]_ab\.sh|ndk2[9]' | Measure-Object | % Count" < /dev/null 2>/dev/null | tr -d '\r ')
  [ "${wp:-0}" != 0 ] && { echo "laptop deploy/lab script running"; return 1; }
  pgrep -f 'deploy[0-9a-z_]*\.sh|lab_run\.sh|ndk29_job' > /dev/null && { echo "WSL deploy/lab/ndk29 job running"; return 1; }
  local f p; for f in ~/detached/*.pid; do n=$(basename $f .pid); case $n in deploy*|*lab*|ndk29|*_deploy) p=$(cat $f); kill -0 $p 2>/dev/null && ps -o args= -p $p | grep -q bash && { echo "detached job $n running"; return 1; };; esac; done
  local ps; ps=$(sh_ "ps -A -o NAME=,ARGS=")
  echo "$ps" | grep -q "lab_ab.sh" && { echo "board lab_ab.sh running"; return 1; }
  echo "$ps" | grep -q "^edge-agent" && echo "$ps" | grep -q "^htpd" || { echo "app not running"; return 1; }
  return 0
}
if ! isdone window; then
  stopchk
  i=0; while :; do stopchk; why=$(board_free) && break
    [ $((i % 15)) -eq 0 ] && st "waiting for the board: $why"; i=$((i+1)); [ $i -gt 720 ] && die "board not free for 12 h"; sleep 60; done
  ramguard
  echo q2b > $K; HAVE_LOCK=1; ( while [ -e $K ] && [ "$(cat $K 2>/dev/null)" = q2b ]; do touch $K; sleep 600; done ) &
  st "BOARD_LOCK q2b taken"
  if [ "$(sh_ "md5sum $BG/$NAME 2>/dev/null" | cut -c1-32)" != "$MD5" ]; then
    fr=$(sh_ "df -k $BG | tail -1" | awk '{print int($4/1024)}')
    [ "${fr:-0}" -ge 3072 ] || die "board free ${fr:-?} MB < 3 GB in $BG"
    st "step 2: stopping the app for the push (board free ${fr} MB)"
    sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v8x5p htpd_v8x5 htpd_v8x4 htpd_v8x3 htpd); do kill -TERM $p; done
      i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done' > /dev/null
    sleep 10
    "$A" push "$(wslpath -w $MS/$NAME)" $BG/$NAME.part > $S/push.log 2>&1 || die "push failed ($(tail -1 $S/push.log))"
    [ "$(sh_ "md5sum $BG/$NAME.part" | cut -c1-32)" = "$MD5" ] || { sh_ "rm -f $BG/$NAME.part"; die "board md5 mismatch after push"; }
    sh_ "mv $BG/$NAME.part $BG/$NAME"
    st "pushed $BG/$NAME md5 $MD5 ok"
  else st "model already on the board (md5 ok)"; fi
  stopchk; [ -e $P/DEMO_NOW ] && die "DEMO_NOW appeared"
  # ---------- 3. one lab window ----------
  st "step 3: lab window $WIN (4b then 2b, REQS 10 10 11 12 13 14 15; app stopped ~20-30 min)"
  "$GB" -c "cd /c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency && WINDOW_MAX=2700 REQS='10 10 11 12 13 14 15' bash lab_run.sh $WIN \
    '4b,htpd_v8x5,qwen35_reasoner_q4_0.gguf,X=0' \
    '2b,htpd_v8x5,$NAME,X=0'" > $J/lab_run_out.txt 2>&1
  last=$(tail -1 $P/$WIN/ab.log 2>/dev/null)
  st "lab window ended: $last"
  echo "$last" | grep -qE "lab ab done \((ok|dead)\)" || die "window did not complete ($last); re-running the job retries it"
  ensure_app; unlock
  done_ window
fi

# ---------- 4. verdict ----------
X=$J/.extra.md
{ echo "## Provenance"
  echo "- model: Qwen/Qwen3.5-2B (HF, base) -> convert_hf_to_gguf.py --outtype bf16 (CPU) -> llama-quantize Q4_0 4 (no imatrix); md5 $MD5; board $BG/$NAME"
  echo "- window: proofs/2026-10-29_latency/$WIN (ab.log, htpd_4b.log, htpd_2b.log, telemetry.log, raw responses); job log ~/detached/q2b.log"
  echo "- live libs, live profile and the deployed reasoner were not changed; nothing deployed"; } > $X
python3 -I $J/q2b_verdict.py $P/$WIN $J/VERDICT.md $X > $S/verdict.out 2>&1 || die "verdict script failed: $(tail -3 $S/verdict.out | tr '\n' ' ')"
rm -f $X
st "step 4: $(grep -m1 'run on the NPU' $J/VERDICT.md | sed 's/^- //') | $(grep -m1 'Decode ms/step' $J/VERDICT.md | sed 's/^- //' | cut -c1-160)"
st "app now: $(sh_ 'ps -A -o NAME= | grep -E "^(edge-agent|htpd)" | tr "\n" " "')"
st "job done -> q2b/VERDICT.md"
