#!/usr/bin/env bash
V=/mnt/c/Users/hp/Desktop/qidk/proofs; L=$V/2026-10-29_rsn_v3/GPU_LOCK
for i in $(seq 30); do [ -e $L ] || break; sleep 10; done
[ -e $L ] && { echo LOCKED; cat $L; exit 1; }
echo "speed_test $(date -Is) pid=$$" > $L
S=$HOME/speedtest; mkdir -p $S
python3 - <<EOF
import json,random
rows=[json.loads(l) for l in open("$V/2026-11-20_rsn_big/data/final_big/train_new.jsonl")]
random.seed(7); rows.sort(key=lambda r:len(json.dumps(r)))
n=len(rows); t=n//3; st=max(1,t//16)
pick=rows[:t:st][:16]+rows[t:2*t:st][:16]+rows[2*t::st][:16]
random.shuffle(pick); print(len(pick),[len(json.dumps(r))//1000 for r in pick])
open("$S/s48.jsonl","w").write("\n".join(json.dumps(r) for r in pick)+"\n")
EOF
nvidia-smi --query-gpu=memory.used,temperature.gpu --format=csv; free -m|head -2
