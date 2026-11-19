#!/usr/bin/env bash
# split_on.sh (WSL): starts the GPU 2B chat server, waits for /health, and only then adds chat_think=adaptive and
# chat_url to htpd_profile. The app reads the profile live, so no restart is needed. Undo: split_off.sh.
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge; S=/data/local/tmp/chatgpu
sh_(){ "$A" shell "$@" | tr -d '\r'; }
w0=$(sh_ "grep -c 'pre-warm done' $S/chat_gpu.log 2>/dev/null" | tail -1)
timeout 20 "$A" shell "cd $S && setsid nohup sh chat_gpu.sh start > /dev/null 2>&1 < /dev/null &" > /dev/null
up=0; for i in $(seq 1 60); do sleep 5; [ "$(sh_ "curl -s -m 3 http://127.0.0.1:8090/health")" = '{"status":"ok"}' ] && { up=1; break; }; done
[ $up = 1 ] || { echo "GPU server not up after 300 s -> left off"; sh_ "sh $S/chat_gpu.sh stop"; exit 1; }
# chat goes to the server only after its header pre-warm (chat_gpu.sh, warm.json): a question sent before it queued behind
# the cold prefill (rehearsal 2026-11-04: 45 s for the first answer). Up to 180 s; past that, switch anyway.
[ -n "$(sh_ "ls $S/warm.json 2>/dev/null")" ] && for j in $(seq 1 36); do
  [ "$(sh_ "grep -c 'pre-warm done' $S/chat_gpu.log" | tail -1)" -gt "${w0:-0}" ] && break; sleep 5; done
sh_ "grep -vE '^(chat_url|chat_think|chat_device)=' $W/htpd_profile > $W/htpd_profile.part && printf 'chat_think=adaptive\nchat_url=http://127.0.0.1:8090\nchat_device=%s\n' \$(cat $S/device 2>/dev/null || echo gpu) >> $W/htpd_profile.part && mv -f $W/htpd_profile.part $W/htpd_profile"
echo "split on: GPU up after $((i*5)) s; profile: $(sh_ "grep -E '^(chat_url|chat_think|chat_device)=' $W/htpd_profile" | tr '\n' ' ')"
