#!/usr/bin/env bash
# gpu_tune.sh (WSL): llama-server flag sweep for the 2B GPU chat, run while the app does NOT yet send chat to the GPU.
# Each config: fresh server on :8095, one cold request (15-tool header + Q0), then 4 warm requests (Q1..Q4, same header).
# Records prefill tokens re-done, total seconds, gen t/s, and the reply text (greedy; must match config A).
# Stops chat_gpu (the stage-1 server) first and restarts it at the end. Results: tune/TUNE.md, tune/raw/*.json
set -u
T=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split/gpu/tune; Q=/mnt/c/Users/hp/Desktop/qidk
A=$Q/Code/platform-tools/adb.exe; S=/data/local/tmp/chatgpu; M=/data/local/tmp/gpu/rsn_v3_2b_r2_q4_0.gguf
mkdir -p $T/raw; exec >> $T/tune.log 2>&1 < /dev/null
sh_(){ "$A" shell "$@" | tr -d '\r'; }
python3 - "$Q/Code/smart-city-edge-agent/app/backend/chat_header15.txt" "$T/raw" <<'EOF'
import json, sys
h = open(sys.argv[1], encoding="utf-8").read().rstrip("\n")
qs = ["Which sensors are faulty right now?", "How many incidents in the last 24 hours?", "Is the CO2 in KH level 3 normal?",
      "Has the KH level 2 AC unit 24 had repeated problems?", "Give me a quick status of the whole campus in two lines."]
for i, q in enumerate(qs):
    p = h + "\n<|im_end|>\n<|im_start|>user\n" + q + "<|im_end|>\n<|im_start|>assistant\n<think>\n"
    json.dump({"prompt": p, "n_predict": 96, "temperature": 0, "top_k": 1, "cache_prompt": True}, open("%s/req%d.json" % (sys.argv[2], i), "w"))
EOF
sh_ "mkdir -p $S/tune"; for i in 0 1 2 3 4; do "$A" push "$(wslpath -w $T/raw/req$i.json)" $S/tune/req$i.json > /dev/null; done
sh_ "sh $S/chat_gpu.sh stop" ; sleep 3
echo "
# round 2 ($(TZ=Asia/Kolkata date +%H:%M) IST)" >> $T/TUNE.md
echo "| config | cold s | warm s (Q1..Q4) | re-prefill tok | gen t/s | same text as A |" >> $T/TUNE.md
echo "|---|---|---|---|---|---|" >> $T/TUNE.md
run() { # $1 name, rest = extra flags
  n=$1; shift
  timeout 15 "$A" shell "cd $S && LD_LIBRARY_PATH=$S/lib:/vendor/lib64 GGML_OPENCL_KERNEL_CACHE_DIR=$S/clcache setsid nohup sh -c 'echo 1000 > /proc/self/oom_score_adj; exec ./llama-server -m $M --device GPUOpenCL -ngl 99 -c 8192 -np 1 -t 2 --host 127.0.0.1 --port 8095 --no-webui -cram 256 $*' > $S/tune/$n.log 2>&1 < /dev/null &" > /dev/null
  up=0; for i in $(seq 1 40); do sleep 3; [ "$(sh_ "curl -s -m 3 http://127.0.0.1:8095/health")" = '{"status":"ok"}' ] && { up=1; break; }; done
  if [ $up = 1 ]; then
    for i in 0 1 2 3 4; do sh_ "curl -s -m 300 -H 'Content-Type: application/json' -d @$S/tune/req$i.json http://127.0.0.1:8095/completion" > $T/raw/${n}_$i.json; done
  fi
  sh_ "for p in \$(pidof llama-server); do grep -q 8095 /proc/\$p/cmdline && kill -9 \$p; done"; sleep 3
  python3 - "$T/raw" "$n" $up <<'EOF' >> $T/TUNE.md
import json, sys
d, n, up = sys.argv[1], sys.argv[2], sys.argv[3]
if up != "1": print("| %s | server did not start | | | | |" % n); sys.exit()
r = []
for i in range(5):
    try: r.append(json.load(open("%s/%s_%d.json" % (d, n, i))))
    except Exception: r.append({})
t = lambda x: (x.get("timings", {}).get("prompt_ms", 0) + x.get("timings", {}).get("predicted_ms", 0)) / 1000
same = []
for i in range(5):
    try: same.append(r[i]["content"] == json.load(open("%s/A_%d.json" % (d, i)))["content"])
    except Exception: same.append(None)
print("| %s | %.1f | %s | %s | %s | %s |" % (n, t(r[0]), " ".join("%.1f" % t(x) for x in r[1:]),
      " ".join(str(x.get("timings", {}).get("prompt_n", "?")) for x in r[1:]),
      " ".join("%.1f" % x.get("timings", {}).get("predicted_per_second", 0) for x in r), "".join("Y" if s else ("?" if s is None else "N") for s in same)))
EOF
  echo "$(date +%T) $n done"
}
run G_t4_ub128 -t 4 -tb 4 -cms 0 -ub 128
run H_t6_ub128 -t 6 -tb 6 -cms 0 -ub 128
run I_t4_ub64 -t 4 -tb 4 -cms 0 -ub 64
timeout 20 "$A" shell "cd $S && setsid nohup sh chat_gpu.sh start > /dev/null 2>&1 < /dev/null &" > /dev/null
echo "- chat_gpu restarted (stage-1 flags)" >> $T/TUNE.md; echo "=== tune done"
