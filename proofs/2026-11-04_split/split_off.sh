#!/usr/bin/env bash
# split_off.sh (WSL): EVAL FALLBACK, takes about 10 s, no app restart. It removes chat_url and chat_think from htpd_profile,
# which the app reads on every call, so chat goes back to the 4B on the NPU with the 9-tool header, as in deploy27. It then
# stops the GPU llama-server. The split APK stays installed: with chat_url unset it sends htpd the same requests as
# before (unit test). Full revert to APK e0ccda2b: proofs/2026-11-04_split/deploy28/known_good (see README).
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; W=/data/local/tmp/smart_city_edge
sh_(){ "$A" shell "$@" | tr -d '\r'; }
sh_ "grep -vE '^(chat_url|chat_think|chat_device)=' $W/htpd_profile > $W/htpd_profile.part && mv -f $W/htpd_profile.part $W/htpd_profile"
sh_ "sh /data/local/tmp/chatgpu/chat_gpu.sh stop"
echo "profile now: $(sh_ "grep -cE '^(chat_url|chat_think|chat_device)=' $W/htpd_profile") split keys (0 = off); llama-server: $(sh_ "pidof llama-server || echo none")"
