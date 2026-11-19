#!/usr/bin/env bash
# gpu_stage.sh (WSL): eval-only 2B chat on the GPU, stage 1 = files + coexistence test, live app keeps running (4B, APK e0ccda2b).
#  1. app stopped (one NPU client; big files only with the app down): push 2B r2 GGUF, llama-server, chat_gpu.sh (.part+md5+mv); app back.
#  2. chat_gpu start next to the running app; wait for the server; telemetry (MemAvailable, Normal zone, kgsl, temps).
#  3. coexistence: fastcheck (critical incident -> 4B on the NPU while the 2B sits on the GPU) + 3 GPU chat completions
#     with the real 15-tool header, one of them during the incident. Any guard kill / app failure -> chat_gpu stop.
# Never reboots. Results: proofs/2026-11-04_split/gpu/STAGE.md
set -u
Q=/mnt/c/Users/hp/Desktop/qidk; P=$Q/proofs/2026-11-04_split/gpu; RF=$Q/proofs/2026-10-27_reasoner_fast
A=$Q/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; S=/data/local/tmp/chatgpu; G=/data/local/tmp/gpu
GG=$Q/Code/models_stage/rsn_v3_2b_r2_q4_0.gguf; BG=$G/rsn_v3_2b_r2_q4_0.gguf
OUT=$P/STAGE.md; exec >> $P/gpu_stage.log 2>&1 < /dev/null
st(){ echo "$*" >> $OUT; echo "$(date -u +%T) $*"; }
w(){ wslpath -w "$1"; }
sh_(){ "$A" shell "$@" | tr -d '\r'; }
stop_app(){ sh_ 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pidof htpd_v9f htpd_v9e htpd); do kill -TERM $p; done
  i=0; while [ $i -lt 120 ] && ps -A -o NAME= | grep -qE "^(htpd|edge-agent)"; do sleep 1; i=$((i+1)); done
  sleep 30; if ps -A -o NAME= | grep -qE "^(htpd|edge-agent|genie)"; then echo STILL; else echo STOPPED; fi'; }
start_app(){ sh_ 'am start -n com.iiith.smartcityedge/.MainActivity >/dev/null 2>&1'; for i in $(seq 1 60); do sleep 5
  [ "$(sh_ "curl -s -m 5 http://127.0.0.1:8000/api/status" | head -c 1)" = "{" ] && return 0; done; return 1; }
push(){ # $1 local, $2 board path
  m=$(md5sum "$1" | cut -c1-32); [ "$(sh_ "md5sum $2 2>/dev/null" | cut -c1-32)" = "$m" ] && { st "- $2 already there"; return 0; }
  "$A" push "$(w "$1")" "$2.part" > /dev/null; [ "$(sh_ "md5sum $2.part" | cut -c1-32)" = "$m" ] && sh_ "mv -f $2.part $2" && st "- pushed $2 ($m)" && return 0
  sh_ "rm -f $2.part"; st "- ABORT push md5 $2"; return 1; }
tele(){ sh_ "echo avail=\$(awk '/MemAvailable/ {print int(\$2/1024)}' /proc/meminfo)MB kgsl=\$((\$(cat /sys/class/kgsl/kgsl/page_alloc)/1048576))MB t=\$(cat /sys/class/thermal/thermal_zone*/temp | sort -rn | head -1 | cut -c1-2)C"; }
comp(){ # $1 label: one /completion with the real header + a question; prints seconds and the reply head
  python3 - "$Q/Code/smart-city-edge-agent/app/backend/chat_header15.txt" "$1" <<'EOF' > /tmp/req_$$.json
import json, sys
h = open(sys.argv[1], encoding="utf-8").read()
q = {"cold": "Which sensors are faulty right now?", "warm": "How many incidents in the last 24 hours?", "during": "Is the CO2 in KH level 3 normal?"}[sys.argv[2]]
p = h.rstrip("\n") + "\n<|im_end|>\n<|im_start|>user\n" + q + "<|im_end|>\n<|im_start|>assistant\n<think>\n"
print(json.dumps({"prompt": p, "n_predict": 64, "temperature": 0, "top_k": 1, "cache_prompt": True}))
EOF
  "$A" push "$(w /tmp/req_$$.json)" $S/req.json > /dev/null
  t0=$(date +%s.%N); r=$(sh_ "curl -s -m 300 -H 'Content-Type: application/json' -d @$S/req.json http://127.0.0.1:8090/completion")
  t1=$(date +%s.%N); echo "$(echo "$t1 - $t0" | bc | cut -c1-5) s | $(echo "$r" | python3 -c "import json,sys
try:
  d=json.load(sys.stdin); t=d.get('timings',{}); print('pp %d tok %.0f t/s, gen %d tok %.1f t/s | %s' % (t.get('prompt_n',0), t.get('prompt_per_second',0), t.get('predicted_n',0), t.get('predicted_per_second',0), d['content'][:80].replace(chr(10),' ')))
except Exception as e: print('ERR', str(e)[:80])")"; }

echo "# GPU chat stage 1 ($(TZ=Asia/Kolkata date +%H:%M) IST)" > $OUT
[ -s $GG ] && { [ -s $P/srv/llama-server ] || [ -s $P/llama-server ]; } || { st "- ABORT: missing gguf or llama-server"; exit 1; }
st "- before: $(tele)"
r=$(stop_app); [ "$r" = STOPPED ] || { st "- ABORT: app not stopped ($r)"; start_app; exit 1; }
sh_ "mkdir -p $S"
if [ -s $P/srv/llama-server ]; then  # native_build.sh: server + its own libs
  sh_ "mkdir -p $S/lib"; prc=0; push $P/srv/llama-server $S/llama-server || prc=1
  for f in $P/srv/lib/*.so; do push $f $S/lib/$(basename $f) || prc=1; done
else push $P/llama-server $S/llama-server; prc=$?; fi
push $GG $BG && push $P/chat_gpu.sh $S/chat_gpu.sh && [ $prc = 0 ]; prc=$?
sh_ "chmod 755 $S/llama-server"
start_app || st "- WARN: app not answering after restart"; [ $prc = 0 ] || exit 1
sleep 60; st "- app up, agents model resident: $(tele)"
sh_ "cd $S && setsid nohup sh chat_gpu.sh start > /dev/null 2>&1 < /dev/null &"; up=0
for i in $(seq 1 60); do sleep 5; [ "$(sh_ "curl -s -m 3 http://127.0.0.1:8090/health")" = '{"status":"ok"}' ] && { up=1; break; }; done
st "- chat_gpu up=$up after $((i*5)) s: $(tele)"; sh_ "tail -3 $S/chat_gpu.log; grep -E 'error|failed|offload|buffer size' $S/server.log | tail -6" | sed 's/^/    /' >> $OUT
[ $up = 1 ] || { sh_ "sh $S/chat_gpu.sh stop"; st "- FAIL: server did not come up -> stopped"; exit 1; }
st "- chat cold: $(comp cold)"; st "- chat warm: $(comp warm)"; st "- after chats: $(tele)"
( cd $RF/scripts && python3 -I fastcheck.py > $P/fastcheck_coexist.json 2>&1; echo "rc=$?" >> $P/fastcheck_coexist.json ) &
FC=$!; sleep 25; st "- during incident: $(tele)"; st "- chat during incident: $(comp during)"; wait $FC
st "- fastcheck with 2B resident on GPU: $(tr -d '\n' < $P/fastcheck_coexist.json | cut -c1-260)"
st "- after incident: $(tele); server: $(sh_ "sh $S/chat_gpu.sh status" | head -1)"
sh_ "grep -c 'GUARD KILL' $S/chat_gpu.log" | sed 's/^/- guard kills: /' >> $OUT
st "- stage 1 done (server left running; stop: adb shell sh $S/chat_gpu.sh stop)"
