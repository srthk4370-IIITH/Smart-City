ADB=/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe
S="C:/Users/hp/AppData/Local/Temp/claude/C--Users-hp-Desktop-qidk/125df7ac-c9eb-46de-b63b-ce87f4c7e8ce/scratchpad/ab.py"
run() { # $1 tag  $2 binary  $3 env  $4 base
  MSYS_NO_PATHCONV=1 "$ADB" shell "pkill -x htpd; pkill -x htpd.v1; pkill -x htpd.v2; pkill -x htpd.v3; pkill -x htpd.v4; pkill -x htpd.v5; sleep 1; t=99; while [ \$t -gt 55 ]; do t=0; for z in /sys/class/thermal/thermal_zone*/temp; do x=\$(cat \$z); [ \$x -gt \$t ] && t=\$x; done; t=\$((t/1000)); [ \$t -gt 55 ] && sleep 10; done; cd /data/local/tmp/llama.cpp; (LD_LIBRARY_PATH=./lib ADSP_LIBRARY_PATH=./lib GGML_HEXAGON_FA_STREAMS=1 HTPD_SPEC=0 $3 setsid nohup ./bin/$2 -m /data/local/tmp/gpu/ft_device_q4exact.gguf --agents 13 --agent-ctx 768 --synth-ctx 4096 --ubatch 512 > /data/local/tmp/htpd_ab.log 2>&1 < /dev/null &); for i in \$(seq 1 60); do grep -q 'htpd: ready' /data/local/tmp/htpd_ab.log && break; sleep 2; done"
  "$ADB" forward tcp:8091 tcp:8091 >/dev/null
  py -3 "$S" "$1" $4
}
"$ADB" shell am force-stop com.iiith.smartcityedge
MSYS_NO_PATHCONV=1 "$ADB" shell 'pkill -x edge-agent; pkill -x htpd; pkill -x genied'
run v4 htpd.v5 "HTPD_LEGACY_PREFILL=1 GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_DRAFT=1" ""
run v5pc htpd.v5 "HTPD_LEGACY_PREFILL=1 GGML_HEXAGON_HMX_PIPE_ALL=1 HTPD_DRAFT=1 HTPD_PREFIX_CACHE=1" v4
