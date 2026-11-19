#!/usr/bin/env bash
# 2026-11-03 deploy27 model step: copy of deploy26_2b.sh for the r2 2B (rsn_v3_2b_r2_q4_0.gguf, gate g2b_r2); status in deploy27/model/STATUS.md. Run after deploy27_apk.sh.
# 2026-11-01 deploy26: rsn_v3 2B reasoner (Qwen3.5-2B fine-tune, Q4_0) replaces rsn_v1 4B in the htpd_v9f reasoner slot.
# APK, htpd binary, NPU libs, agents' model: unchanged. Only htpd_profile changes:
#   reasoner_model=/data/local/tmp/gpu/rsn_v3_2b_q4_0.gguf (NEW path; the 4B file stays for rollback)
#   chat_think=adaptive (rsn_v3 was trained with adaptive thinking; the live APK already reads this key, chat.go)
#   env: HTPD_REASON_CORPUS_LIVE / HTPD_CHAT_CORPUS -> *_2b.jsonl copies (the 4B's live corpora stay clean for rollback)
# Modes:
#   bash deploy26_2b.sh --check      laptop only, no adb: gate, md5, tokenizer check, profile render (dry run)
#   bash deploy26_2b.sh --force-lab  push + board lab (2B on RWH q10-q39) WITHOUT a gate PASS; never promotes
#   bash deploy26_2b.sh              gate PASS required: push + lab (accuracy guard vs 4B) + promote + app check
#   bash deploy26_2b.sh --skip-lab   as default but no lab window (gate PASS still required)
#   bash deploy26_2b.sh --rollback   put the 4B profile back (deploy26/known_good) + clean restart + chaos 1
# Safety: one NPU client (app stopped, pidof + kill -TERM, wait for exit); big file .part + md5 + mv with the app stopped,
# straight to /data/local/tmp (never /sdcard); <= 55-60 C before each lab/check request; never pkill -f; never reboots.
# App check after promotion = chaos 2 + fastcheck x2 + chat check (deploy24 pattern); any chaos/fastcheck failure or a
# reasoner that is not the 2B -> 4B profile restored automatically. Records AI update latency, NSP/max temp, RAM.
# usage (WSL): bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh deploy26 /mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-01_2b/deploy26_2b.sh [mode]
MODE=${1:-deploy}
Q=/mnt/c/Users/hp/Desktop/qidk; P=$Q/proofs/2026-11-01_2b; I=$Q/proofs/2026-11-03_deploy27/model; mkdir -p $I/known_good
RF=$Q/proofs/2026-10-27_reasoner_fast; MM=$Q/proofs/2026-10-28_master; NP=$Q/proofs/2026-10-31_night; LAT=$Q/proofs/2026-10-29_latency
KG=$Q/proofs/2026-10-29_rsn_v3/kaggle; GATE=${GATE:-$KG/gate/g2b_r2/gate.json}
NEWG=${NEWG:-$Q/Code/models_stage/rsn_v3_2b_r2_q4_0.gguf}; REFG=$Q/Code/models_stage/rsn_v1_q4_0.gguf
A=$Q/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; G=/data/local/tmp/gpu; BIN=/data/local/tmp/llama.cpp/bin
R=/data/local/tmp/rfast; NAME=$(basename $NEWG); BG=$G/$NAME; OLD=$G/qwen35_reasoner_q4_0.gguf
LAB=lab27_2b; LAB_TOL=${LAB_TOL:-0}; WINDOW_MAX=${WINDOW_MAX:-3600}
PYG=${PYG:-$HOME/venvs/qaihm/bin/python}
case $MODE in --check|--force-lab|deploy|--skip-lab|--rollback) ;; *) echo "unknown mode $MODE"; exit 2;; esac
[ $MODE = --check ] || exec >> $I/deploy.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
st(){ echo "$*" >> $I/STATUS.md; log "$*"; }
w(){ wslpath -w "$1"; }
sh_(){ $A shell "$@" | tr -d '\r'; }
setp(){ f=$1; k=$2; v=$3; grep -v "^$k=" $f > $f.t; [ -n "$v" ] && echo "$k=$v" >> $f.t; mv $f.t $f; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9f htpd_v9e htpd_v9d htpd_v9c htpd_v9b htpd_v9 htpd_v8x5p htpd_v8x5 htpd_v8x4 htpd_v8x3 htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie|llama)"; then echo STILL $(ps -A -o NAME= | grep -E "^(htpd|edge-agent|genie|llama)") after $i s; else echo STOPPED; fi'; }
start_app(){ l0=$(sh_ "wc -l < $W/state/htpd.log" | tail -1); sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'
  for i in $(seq 1 60); do sleep 5; l=$(sh_ "wc -l < $W/state/htpd.log" | tail -1)
    if [ "${l:-0}" -lt "${l0:-0}" ]; then c=$(sh_ "grep -c 'htpd: ready in' $W/state/htpd.log" | tail -1)
    else c=$(sh_ "tail -n +$(( ${l0:-0} + 1 )) $W/state/htpd.log | grep -c 'htpd: ready in'" | tail -1); fi
    [ "${c:-0}" -ge 1 ] && return 0; done; return 1; }
put_profile(){ $A push "$(w $1)" $W/htpd_profile.part > /dev/null && sh_ "mv -f $W/htpd_profile.part $W/htpd_profile"
  [ "$(sh_ "md5sum $W/htpd_profile" | cut -c1-32)" = "$(md5sum $1 | cut -c1-32)" ]; }
render(){ # $1 = 4B known-good profile -> $2 = 2B profile
  cp $1 $2; sed -i 's/\r$//' $2
  setp $2 reasoner_model $BG; setp $2 chat_think adaptive
  sed -i -e '/^env=/ s#reason_corpus_live\.jsonl#reason_corpus_live_2b.jsonl#' -e '/^env=/ s#chat_corpus\.jsonl#chat_corpus_2b.jsonl#' $2; }

# ---------- 0. laptop preflight (all modes but --rollback) ----------
if [ $MODE != --rollback ]; then
  echo "# Deploy 27 ($MODE): rsn_v3 2B reasoner ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $I/STATUS.md
  gate=$(python3 -c "import json;g=json.load(open('$GATE'));print('PASS' if g.get('pass') is True else 'FAIL')" 2>/dev/null || echo MISSING)
  st "- gate $GATE: $gate"
  # OWNER_GO=1: owner ordered deploy-first, test-after (2026-11-01 ~23:45 IST); app checks + auto-rollback still apply
  [ "${OWNER_GO:-0}" = 1 ] && [ "$gate" != PASS ] && { st "- gate not PASS ($gate) but OWNER_GO=1: owner ordered deploy first, test after"; gate=PASS; }
  if [ "$gate" != PASS ] && [ $MODE != --force-lab ] && [ $MODE != --check ]; then st "- REFUSED: gate not PASS (use --force-lab for a lab-only run, no promotion)"; exit 2; fi
  [ -s $NEWG ] && [ -s $NEWG.md5 ] || { st "- ABORT: missing $NEWG or .md5"; exit 3; }
  MD5=$(cut -c1-32 $NEWG.md5); [ "$(md5sum $NEWG | cut -c1-32)" = "$MD5" ] || { st "- ABORT: laptop md5 mismatch $NEWG"; exit 3; }
  gc=$($PYG -I $P/gguf_check.py $NEWG $REFG); grc=$?; echo "$gc" > $I/gguf_check.json
  [ $grc = 0 ] || { st "- ABORT: tokenizer/arch differs from rsn_v1 (corpora are token ids): $gc"; exit 3; }
  SZ=$(stat -c %s $NEWG); st "- model $NAME $SZ bytes md5 $MD5; tokenizer = rsn_v1 (gguf_check ok)"
  if [ $MODE = --check ]; then
    [ -s $LAT/deploy25/known_good/htpd_profile ] && { render $LAT/deploy25/known_good/htpd_profile $I/htpd_profile.dryrun
      st "- dry-run profile diff vs deploy25 known_good:"; diff <(sed 's/\r$//' $LAT/deploy25/known_good/htpd_profile) $I/htpd_profile.dryrun | sed 's/^/    /' | tee -a $I/STATUS.md; }
    st "- CHECK OK (no board access)"; exit 0; fi
fi

# ---------- 1. board / other jobs free ----------
[ -e $LAT/DEMO_NOW ] && { st "- ABORT: DEMO_NOW"; exit 3; }
busy(){ pgrep -af 'deploy2[0-5][a-z0-9_]*\.sh|lab_run\.sh|lab_ab\.sh|ndk29_job' | grep -v "^$$ " | grep -q . && { echo "WSL deploy/lab job"; return 0; }
  n=$(powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | % { \$_.CommandLine } | Select-String -Pattern 'deplo[y]2[0-5][0-9a-z_]*\.sh|la[b]_run\.sh' | Measure-Object | % Count" < /dev/null 2>/dev/null | tr -d '\r ')
  [ "${n:-0}" != 0 ] && { echo "Windows deploy/lab job"; return 0; }
  sh_ "ps -A -o ARGS=" | grep -q "lab_ab.sh" && { echo "board lab window"; return 0; }
  [ -e $MM/BOARD_LOCK ] && [ $(( $(date +%s) - $(stat -c %Y $MM/BOARD_LOCK) )) -lt 10800 ] && { echo "BOARD_LOCK $(cat $MM/BOARD_LOCK)"; return 0; }
  return 1; }
i=0; while why=$(busy); do [ $((i % 10)) = 0 ] && st "- waiting: $why"; i=$((i+1)); [ $i -gt 60 ] && { st "- ABORT: board busy 60 min ($why)"; exit 3; }; sleep 60; done
echo deploy26 > $MM/BOARD_LOCK
touch $NP/PAUSE; trap "rm -f $NP/PAUSE; [ \"\$(cat $MM/BOARD_LOCK 2>/dev/null)\" = deploy26 ] && rm -f $MM/BOARD_LOCK" EXIT
while [ -e $NP/BUSY ]; do sleep 5; done

# ---------- manual rollback ----------
if [ $MODE = --rollback ]; then
  echo "# Deploy 27 manual rollback ($(TZ=Asia/Kolkata date +%H:%M) IST)" >> $I/STATUS.md
  [ -s $I/known_good/htpd_profile ] || { st "- ABORT: no known_good profile"; exit 3; }
  r=$(stop_app); [ "$r" = STOPPED ] || { st "- ABORT: app not stopped ($r)"; start_app; exit 3; }
  put_profile $I/known_good/htpd_profile && st "- 4B profile restored" || st "- PROFILE PUSH FAILED"
  start_app; (cd $RF/scripts && python3 -I chaos2.py chaos 1 60); st "- rollback chaos 1 rc=$?; $(sh_ "grep -E '^(bin|reasoner_model|chat_think)=' $W/htpd_profile" | tr '\n' ' ')"; exit 0
fi

# ---------- 2. snapshot + push (app stopped) ----------
[ "$(sh_ "md5sum /data/local/tmp/llama.cpp/lib_rp29/libggml-hexagon.so" | cut -c1-32)" = c4e4598412e54469e9f387935de595bb ] || { st "- ABORT: lib_rp29 md5"; exit 3; }
[ "$(sh_ "[ -x $BIN/htpd_v9f ] && [ -s $OLD ] && echo ok" | tail -1)" = ok ] || { st "- ABORT: htpd_v9f or the 4B GGUF missing on the board"; exit 3; }
$A pull $W/htpd_profile "$(w $I/known_good/htpd_profile)" > /dev/null; sed -i 's/\r$//' $I/known_good/htpd_profile
grep -q "^reasoner_model=$OLD$" $I/known_good/htpd_profile || { st "- ABORT: live profile is not the 4B ($(grep ^reasoner_model= $I/known_good/htpd_profile))"; exit 3; }
grep -q "^bin=$BIN/htpd_v9f$" $I/known_good/htpd_profile || { st "- ABORT: live bin is not htpd_v9f"; exit 3; }
st "- snapshot: profile $(md5sum $I/known_good/htpd_profile | cut -c1-8) (4B, htpd_v9f)"
if [ "$(sh_ "md5sum $BG 2>/dev/null" | cut -c1-32)" != "$MD5" ]; then
  fr=$(sh_ "df -k $G | tail -1" | awk '{print int($4/1024)}'); need=$(( SZ / 1048576 + 1536 ))
  [ "${fr:-0}" -ge $need ] || { st "- ABORT: board free ${fr:-?} MB < $need MB in $G"; exit 3; }
  r=$(stop_app); log "stop for push: $r"
  [ "$r" = STOPPED ] || { st "- ABORT: app not stopped for the push ($r)"; start_app; exit 3; }
  t0=$(date +%s); $A push "$(w $NEWG)" $BG.part > /dev/null
  if [ "$(sh_ "md5sum $BG.part" | cut -c1-32)" = "$MD5" ]; then sh_ "mv -f $BG.part $BG && echo $MD5 > $BG.md5"; st "- pushed $BG md5 ok ($(( $(date +%s) - t0 )) s)"
  else sh_ "rm -f $BG.part"; st "- ABORT: board md5 mismatch after push"; start_app; exit 3; fi
  APP_DOWN=1
else st "- $BG already on the board (md5 ok)"; APP_DOWN=0; fi

# ---------- 3. lab window: 2B on RWH q10-q39 (q10 = warm-up), live htpd_v9f env, app stopped ----------
LABOK=1
if [ $MODE != --skip-lab ]; then
  ENV=$(grep '^env=' $I/known_good/htpd_profile | cut -d= -f2- | tr ' ' '\n' | grep -vE '^(HTPD_REASON_IDLE_MS|HTPD_REASON_CORPUS_LIVE|HTPD_CHAT_CORPUS)=' | tr '\n' ' ')
  printf '#!/system/bin/sh\ncd %s/lab\nREQS="10 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39" sh lab_ab.sh %s "v3b,htpd_v9f,%s,%s HTPD_REASON_CORPUS_LIVE=%s/lab/%s_live.jsonl"\n' \
    $R $LAB $NAME "$ENV" $R $LAB > $I/run_lab26.sh
  sed 's/\r$//' $LAT/lab_ab.sh > $I/lab_ab.sh
  sh_ "mkdir -p $R/lab; rm -rf $R/lab/$LAB $R/lab/${LAB}_live.jsonl"
  $A push "$(w $I/lab_ab.sh)" $R/lab/lab_ab.sh > /dev/null; $A push "$(w $I/run_lab26.sh)" $R/lab/run_lab26.sh > /dev/null
  $A push "$(w $RF/bench/agents10.json)" $R/lab/agents10.json > /dev/null
  [ "$(sh_ "ls $R/rreq_split | wc -l" | tail -1)" -ge 40 ] || $A push "$(w $RF/bench/rreq_split)" $R/ > /dev/null
  st "- lab $LAB start (2B, q10-q39, htpd_v9f + live env, <= 55 C per request)"
  sh_ "cd $R/lab && (setsid nohup sh run_lab26.sh > /dev/null 2>&1 < /dev/null &)"; sleep 30; t0=$(date +%s)
  while ! sh_ "tail -1 $R/lab/$LAB/ab.log 2>/dev/null" | grep -q "=== lab ab done"; do
    [ -e $LAT/DEMO_NOW ] && sh_ "touch $R/lab/ABORT"
    [ $(( $(date +%s) - t0 )) -gt $WINDOW_MAX ] && sh_ "touch $R/lab/ABORT"
    if ! sh_ "ps -A -o ARGS=" | grep -q "lab_ab.sh $LAB"; then st "- lab script gone without done"; break; fi
    sleep 30; done
  rm -rf $I/$LAB; $A pull $R/lab/$LAB "$(w $I)" > /dev/null
  cp $RF/raw/acc_v2/sp3_q*_*.json $I/$LAB/ 2>/dev/null   # 4B reference: rsn_v1 sp3, same 30 prompts (2026-10-28 board run)
  (cd $RF/scripts && REF=sp3 python3 -I split_acc.py $I/$LAB 10) > $I/lab_acc.md
  st "- lab: $(grep -E '^\| (sp3|v3b) ' $I/lab_acc.md | tr '\n' ' ')"
  st "- lab heat/RAM: max t $(awk -F'[ =]' '{print $3}' $I/$LAB/telemetry.log | sort -n | tail -1) C, min avail $(awk -F'[ =]' '{print $5}' $I/$LAB/telemetry.log | sort -n | head -1) MB; $(grep -cE 'HEAT|ABORT' $I/$LAB/ab.log) heat/abort lines"
  LABV=$(python3 - $I/lab_acc.md $LAB_TOL <<'PY'
import sys
rows = {}
for l in open(sys.argv[1]):
    c = [x.strip() for x in l.strip().strip("|").split("|")]
    if len(c) >= 10 and c[0] in ("sp3", "v3b"): rows[c[0]] = dict(n=int(c[1]), parse=int(c[2]), sev=int(c[3]), lab=int(c[4]), s=float(c[9]))
v1, b = rows.get("sp3"), rows.get("v3b"); tol = int(sys.argv[2])
ok = bool(v1 and b and b["n"] >= 30 and b["parse"] == b["n"] and b["sev"] >= v1["sev"] - tol and b["lab"] >= v1["lab"] - tol)
print("PASS" if ok else "FAIL", v1, b)
PY
)
  st "- lab accuracy guard (2B parse 30/30, sev/label=gold >= 4B - $LAB_TOL): $LABV"
  [ "${LABV%% *}" = PASS ] || LABOK=0
  APP_DOWN=0   # lab_ab.sh restarts the app (4B profile) at its end
fi
if [ $MODE = --force-lab ] || [ $LABOK = 0 ]; then
  [ $APP_DOWN = 1 ] && start_app
  st "- NOT PROMOTED ($([ $MODE = --force-lab ] && echo 'lab-only run' || echo 'lab accuracy guard FAIL')); 4B stays live; 2B file kept at $BG"
  st "- board now: $(sh_ "grep -E '^(bin|reasoner_model)=' $W/htpd_profile" | tr '\n' ' ')"; exit $([ $MODE = --force-lab ] && echo 0 || echo 1)
fi

# ---------- 4. promote: 2B profile, clean restart ----------
REF4=$(ls -t $RF/raw/fastcheck_*.json 2>/dev/null | head -1); [ -n "$REF4" ] && st "- 4B reference fastcheck: $(tr -d '\n' < $REF4 | cut -c1-200)"
render $I/known_good/htpd_profile $I/htpd_profile.2b
st "- profile change: $(diff $I/known_good/htpd_profile $I/htpd_profile.2b | grep '^[<>]' | cut -c1-140 | tr '\n' ' ')"
r=$(stop_app); log "stop for promote: $r"
[ "$r" = STOPPED ] || { st "- NOT DEPLOYED: app not stopped ($r)"; start_app; exit 3; }
sh_ "cd $W && { [ -e reason_corpus_live_2b.jsonl ] || cp reason_corpus_live.jsonl reason_corpus_live_2b.jsonl 2>/dev/null; [ -e chat_corpus_2b.jsonl ] || cp chat_corpus.jsonl chat_corpus_2b.jsonl 2>/dev/null; true; }"
ok=1; crc=-; frc=-; frc2=-; put_profile $I/htpd_profile.2b || ok=0
[ $ok = 1 ] && { start_app || ok=0; }; sleep 20
cat > $I/tel.sh <<'T'
t=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1)
n=$(for z in /sys/class/thermal/thermal_zone*; do case "$(cat $z/type)" in *nsp*|*NSP*) cat $z/temp;; esac; done | sort -rn | head -1)
a=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo); r=0
for p in $(pidof htpd_v9f); do r=$(awk '/VmRSS/ {print int($2/1024)}' /proc/$p/status); done
echo "t=$((${t:-0}/1000)) nsp=$((${n:-0}/1000)) avail=$a htpd_rss=$r"
T
sed -i 's/\r$//' $I/tel.sh; $A push "$(w $I/tel.sh)" $R/tel26.sh > /dev/null
( while :; do echo "$(date +%T) $(sh_ "sh $R/tel26.sh")" >> $I/telemetry.log; sleep 5; done ) & TEL=$!
trap "kill $TEL 2>/dev/null; rm -f $NP/PAUSE; [ \"\$(cat $MM/BOARD_LOCK 2>/dev/null)\" = deploy26 ] && rm -f $MM/BOARD_LOCK" EXIT
if [ $ok = 1 ]; then
  sh_ "grep 'reasoner slot' $W/state/htpd.log | tail -1" | grep -q "$NAME" || { st "- htpd reasoner slot is not the 2B"; ok=0; }
fi
if [ $ok = 1 ]; then
  (cd $RF/scripts && python3 -I chaos2.py chaos 2 150); crc=$?
  fc=$(cd $RF/scripts && python3 -I fastcheck.py); frc=$?
  log "chaos rc=$crc fastcheck rc=$frc $fc"; [ $crc = 0 ] && [ $frc = 0 ] || ok=0
fi
if [ $ok = 1 ]; then
  fc2=$(cd $RF/scripts && python3 -I fastcheck.py); frc2=$?
  log "fastcheck2 rc=$frc2 $fc2"; [ $frc2 = 0 ] || ok=0
fi
if [ $ok = 1 ]; then  # the AI update must have come from the 2B (the app's model label is still the hard-coded 4B name)
  rl=$(sh_ "grep 'reasoner loaded in' $W/state/htpd.log | tail -1"); log "last reasoner load: $rl"
  echo "$rl" | grep -q "$NAME" || { st "- last reasoner load is not the 2B"; ok=0; }
  st "- reasoner per request (htpd.log): $(sh_ "grep -E 'reasoner loaded in|reason stream 0:' $W/state/htpd.log | tail -4" | cut -c1-110 | tr '\n' ' ')"
fi
if [ $ok = 1 ]; then
  sh_ "curl -s -X POST http://127.0.0.1:8000/api/chat/warm" > /dev/null; sleep 15
  python3 $MM/chatcheck.py "Which domains have open incidents right now?" "How many HVAC incidents in the last 48 hours?" "Which incident needs my attention first?" "Why could the CO2 and HVAC problems be connected?" "Close all open incidents." > $I/chat.txt
  while read l; do st "- chat: $l"; done < $I/chat.txt
  grep -qE "^FAIL|error True|could not find an answer" $I/chat.txt && st "- CHAT WARNING: see chat lines (owner: fix forward, no rollback for chat)"
fi
kill $TEL 2>/dev/null
st "- telemetry during the app check: max t $(grep -o 't=[0-9]*' $I/telemetry.log | cut -d= -f2 | sort -n | tail -1) C, max NSP $(grep -o 'nsp=[0-9]*' $I/telemetry.log | cut -d= -f2 | sort -n | tail -1) C, min MemAvailable $(grep -o 'avail=[0-9]*' $I/telemetry.log | cut -d= -f2 | sort -n | head -1) MB, max htpd RSS $(grep -o 'rss=[0-9]*' $I/telemetry.log | cut -d= -f2 | sort -n | tail -1) MB"
if [ $ok = 1 ]; then
  st "- DEPLOYED: rsn_v3 2B ($BG, md5 $MD5), chat_think=adaptive; chaos 2 rc=0; fastcheck $fc; fastcheck2 $fc2"
else
  r=$(stop_app); log "rollback stop: $r"
  put_profile $I/known_good/htpd_profile && log "4B profile restored" || log "PROFILE RESTORE PUSH FAILED"
  start_app; (cd $RF/scripts && python3 -I chaos2.py chaos 1 60); rrc=$?
  st "- FAILED (chaos rc=$crc fastcheck rc=$frc/$frc2) -> 4B profile restored; re-check chaos 1 rc=$rrc; 2B file kept at $BG"
fi
st "- board now: $(sh_ "grep -E '^(bin|reasoner_model|chat_think)=' $W/htpd_profile" | tr '\n' ' ')"
log "=== deploy26 done"
[ $ok = 1 ]
