#!/usr/bin/env bash
# Small same-session A/B (2026-10-29 03:50 IST): htpd_v8x2 vs htpd_v8x3, rsn_v1, split 3, prompts q12-q14 (+q12 warm-up),
# interleaved x2 x3 x2 x3, so board heat/order can't explain a difference. ab_board.sh stops the app first and restarts it.
# Decision is written to x2x3_ab.result only; deploy stays v8x3 unless v8x3 is >= 4% slower on matched prompts.
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; RF=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-27_reasoner_fast
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; K=$M/BOARD_LOCK; RB=/data/local/tmp/rfast
exec >> $M/x2x3_ab.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
while [ -e $K ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; do sleep 60; done
echo x2x3 > $K; trap 'rm -f $K' EXIT
printf '#!/system/bin/sh\ncd %s; [ -d ab ] && mv ab ab_prev_$(date +%%H%%M%%S)\nREQS="12 12 13 14" sh ab_board.sh "spxa2,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1" "spxa3,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1" "spxb2,htpd_v8x2,-,GGML_HEXAGON_OPPOLL=1" "spxb3,htpd_v8x3,-,GGML_HEXAGON_OPPOLL=1"\n' $RB > $M/run_x2x3.sh
$A push "$(wslpath -w $M/run_x2x3.sh)" $RB/run_x2x3.sh > /dev/null
$A shell "cd $RB; (setsid nohup sh run_x2x3.sh > /dev/null 2>&1 < /dev/null &)"; log "started"; sleep 120
until $A shell "tail -1 $RB/ab/ab.log 2>/dev/null" | tr -d '\r' | grep -q "=== ab done"; do sleep 30; done
D=$M/x2x3_raw; rm -rf $D; $A pull $RB/ab "$(wslpath -w $M)" > /dev/null; mv $M/ab $D
python3 - $D <<'P' | tee $M/x2x3_ab.result
import glob, json, os, re, sys, collections
t = collections.defaultdict(list)
for p in glob.glob(os.path.join(sys.argv[1], "spx*_q*_*.json")):
    m = re.match(r"spx([ab])([23])_q(\d+)_(\d+)\.json", os.path.basename(p))
    if not m or m.group(4) == "0": continue
    o = next((json.loads(l) for l in open(p) if '"total_ms"' in l), None)
    if o: t[m.group(2)].append(o["total_ms"] / 1000)
x2, x3 = t["2"], t["3"]
if x2 and x3:
    a, b = sum(x2) / len(x2), sum(x3) / len(x3)
    print(f"v8x2 mean {a:.1f} s (n={len(x2)})  v8x3 mean {b:.1f} s (n={len(x3)})  diff {100*(b-a)/a:+.1f}%")
    print("VERDICT", "v8x3 slower: consider v8x2" if b > a * 1.04 else "no real difference: keep v8x3 (safety)")
else: print("VERDICT incomplete run")
P
log "done"
